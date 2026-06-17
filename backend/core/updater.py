"""자동 업데이트.

GitHub(Enterprise) Releases 의 REST API 로 최신 릴리즈를 조회하고, latest.json 에셋을
파싱해 새 버전이 있으면 sha256 검증 후 번들된 updater.exe 로 self-replace 를 트리거한다.

private 레포에서는 브라우저 다운로드 URL(`.../releases/latest/download/...`)이 PAT 헤더
인증을 무시하고 404 를 돌려준다(웹 세션 쿠키 전용 경로). 그래서 메타·에셋 모두 REST API
(`.../api/v3/repos/.../releases/...`)로 받는다 — 에셋 다운로드는 `Accept:
application/octet-stream` 헤더가 있어야 메타데이터 JSON 이 아닌 바이너리 본문이 온다.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from core import browser, config
from core.github_api import ASSET_ACCEPT as _GITHUB_ASSET_ACCEPT
from core.github_api import JSON_ACCEPT as _GITHUB_JSON_ACCEPT
from core.github_api import SSL_VERIFY as _SSL_VERIFY
from core.github_api import api_headers as _api_headers
from core.version import APP_VERSION
from core.config import (
    REPO_BASE_URL,
    UPDATE_CHECK_CACHE_TTL,
    UPDATE_CHECK_TIMEOUT,
    UPDATE_DOWNLOAD_TIMEOUT,
)

# 릴리즈에 첨부되는 업데이트 메타 에셋 파일명 (release.ps1 이 생성·업로드).
_MANIFEST_ASSET_NAME = "latest.json"

# 인증 헤더·TLS·매체 타입은 github_api 로 공용화됐다(content_sync 와 공유).
# 모듈 로컬 별칭으로 기존 호출부·테스트가 그대로 동작한다.


def _latest_release_url() -> str:
    """최신(비-prerelease) 릴리즈 메타를 조회하는 REST API URL."""
    return (
        f"{config.GITHUB_API_BASE}/repos/"
        f"{config.REPO_OWNER}/{config.REPO_NAME}/releases/latest"
    )


def _resolve_asset_api_url(release: dict, name: str) -> Optional[str]:
    """릴리즈 응답의 assets[] 에서 파일명으로 에셋의 API 다운로드 URL 을 찾는다.

    브라우저 URL(`browser_download_url`)이 아니라 PAT 헤더 인증이 통하는 API
    에셋 URL(`url` = `.../releases/assets/{id}`)을 돌려준다.

    Args:
        release: `releases/latest` 응답 JSON.
        name: 찾을 에셋 파일명 (예: "latest.json", "MyAgent.exe").

    Returns:
        Optional[str]: 일치하는 에셋의 API URL, 없으면 None.
    """
    for asset in release.get("assets", []):
        if asset.get("name") == name:
            return asset.get("url")
    return None


def _exe_asset_name(meta: dict) -> str:
    """latest.json 의 url 에서 EXE 에셋 파일명만 추출한다.

    url 은 브라우저 경로(`.../releases/download/v.../MyAgent.exe`)라 직접 다운로드에는
    못 쓰지만, 끝의 파일명은 릴리즈 assets[] 에서 API URL 을 역참조하는 키로 쓴다.

    Args:
        meta: 파싱된 latest.json.

    Returns:
        str: EXE 에셋 파일명 (예: "MyAgent.exe").
    """
    return Path(urlparse(meta["url"]).path).name


# in-memory cache
_cache_lock = threading.Lock()
_cache: dict = {"at": 0.0, "data": None}

# 진행상태 (프론트엔드 폴링용)
_state_lock = threading.Lock()
_state: dict = {
    "status": "idle",  # idle | downloading | verifying | staging | restarting | error
    "progress": 0,
    "total": 0,
    "message": "",
    "target_version": None,
}


def _set_state(**kwargs) -> None:
    with _state_lock:
        _state.update(kwargs)


def get_state() -> dict:
    with _state_lock:
        return dict(_state)


def current_version() -> str:
    return APP_VERSION


def _parse_version(v: str) -> tuple[int, ...]:
    parts = []

    for chunk in v.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            # pre-release suffix 등은 무시. 단순 비교만 수행.
            digits = "".join(c for c in chunk if c.isdigit())
            parts.append(int(digits) if digits else 0)

    return tuple(parts)


def _is_newer(latest: str, current: str) -> bool:
    return _parse_version(latest) > _parse_version(current)


def _validate_meta(meta: dict) -> Optional[str]:
    for key in ("version", "url", "sha256"):
        if not isinstance(meta.get(key), str) or not meta[key]:
            return f"missing or invalid field: {key}"

    url = meta["url"]
    if not url.startswith(REPO_BASE_URL + "/"):
        return f"url not under REPO_BASE_URL: {url}"

    sha = meta["sha256"]
    if len(sha) != 64 or any(c not in "0123456789abcdefABCDEF" for c in sha):
        return "sha256 not a 64-char hex string"

    return None


def _fetch_release_and_meta(client: httpx.Client) -> dict:
    """최신 릴리즈 메타를 조회하고 latest.json 에셋을 받아 파싱한다.

    ① `releases/latest` REST API 로 릴리즈 응답을 받고
    ② 그 assets[] 에서 latest.json 에셋의 API URL 을 찾아
    ③ octet-stream 헤더로 본문(=업데이트 메타)을 다운로드해 파싱한다.

    파싱된 메타에는 다운로드 단계가 쓸 EXE 에셋 API URL 을 `_download_url` 키로
    함께 실어 둔다(같은 릴리즈 응답에서 역참조 — 재조회 불필요).

    Args:
        client: 인증·TLS 설정이 적용된 httpx.Client.

    Returns:
        dict: 파싱된 latest.json + `_download_url`(내부 키).

    Raises:
        FileNotFoundError: 릴리즈에 latest.json 또는 EXE 에셋이 없을 때.
        httpx.HTTPStatusError: API 응답이 4xx/5xx 일 때.
    """
    r = client.get(_latest_release_url(), headers=_api_headers(_GITHUB_JSON_ACCEPT))
    r.raise_for_status()
    release = r.json()

    manifest_url = _resolve_asset_api_url(release, _MANIFEST_ASSET_NAME)
    if manifest_url is None:
        raise FileNotFoundError(
            f"{_MANIFEST_ASSET_NAME} asset not found in latest release"
        )

    rm = client.get(manifest_url, headers=_api_headers(_GITHUB_ASSET_ACCEPT))
    rm.raise_for_status()
    meta = rm.json()

    download_url = _resolve_asset_api_url(release, _exe_asset_name(meta))
    if download_url is None:
        raise FileNotFoundError(
            f"EXE asset '{_exe_asset_name(meta)}' not found in latest release"
        )
    meta["_download_url"] = download_url
    return meta


def check_latest(force: bool = False) -> dict:
    """최신 릴리즈 조회. 실패는 update_available=False 로 silently 반환."""
    # QA 빌드는 자동 업데이트를 받지 않는다 — 네트워크 호출 없이 즉시 차단.
    # QA EXE 는 prerelease 라 prod latest 포인터에도 안 잡히지만, 폴링 자체를 막아
    # 검증 중인 빌드가 의도치 않게 교체되는 것을 방지한다.
    if config.BUILD_CHANNEL == "qa":
        return {
            "current": APP_VERSION,
            "latest": None,
            "update_available": False,
            "error": None,
        }

    now = time.time()

    with _cache_lock:
        cached = _cache["data"]
        cached_at = _cache["at"]

    if not force and cached is not None and now - cached_at < UPDATE_CHECK_CACHE_TTL:
        return _build_check_response(cached)

    try:
        with httpx.Client(
            timeout=UPDATE_CHECK_TIMEOUT, follow_redirects=True, verify=_SSL_VERIFY
        ) as client:
            meta = _fetch_release_and_meta(client)
    except Exception as e:
        print(f"update check failed: {e}")
        return {
            "current": APP_VERSION,
            "latest": None,
            "update_available": False,
            "error": "check_failed",
        }

    err = _validate_meta(meta)
    if err is not None:
        print(f"latest.json invalid: {err}")
        return {
            "current": APP_VERSION,
            "latest": None,
            "update_available": False,
            "error": "invalid_metadata",
        }

    with _cache_lock:
        _cache["data"] = meta
        _cache["at"] = now

    return _build_check_response(meta)


def _build_check_response(meta: dict) -> dict:
    latest = meta["version"]

    return {
        "current": APP_VERSION,
        "latest": latest,
        "update_available": _is_newer(latest, APP_VERSION),
        "notes": meta.get("notes", ""),
        "size": meta.get("size", 0),
        "released_at": meta.get("released_at"),
    }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)

    return h.hexdigest()


def _verify_signature(path: Path) -> bool:
    # 코드 서명 도입 시 여기에 signtool/Authenticode 검증을 추가한다.
    # 현재는 sha256 무결성으로만 검증하므로 통과.
    _ = path
    return True


def _download(url: str, dest: Path, expected_size: int) -> None:
    _set_state(
        status="downloading", progress=0, total=expected_size, message="다운로드 중..."
    )

    with httpx.Client(
        timeout=UPDATE_DOWNLOAD_TIMEOUT, follow_redirects=True, verify=_SSL_VERIFY
    ) as client:
        # API 에셋 URL 은 octet-stream Accept 헤더가 있어야 바이너리 본문을 준다(없으면
        # 에셋 메타데이터 JSON 반환). 서명된 URL 로 302 redirect 되며, httpx 는 cross-host
        # redirect 시 Authorization 을 자동 제거한다(서명 URL 은 토큰 불필요) — 안전.
        with client.stream("GET", url, headers=_api_headers(_GITHUB_ASSET_ACCEPT)) as r:
            r.raise_for_status()
            written = 0

            with dest.open("wb") as f:
                for chunk in r.iter_bytes(chunk_size=1024 * 256):
                    f.write(chunk)
                    written += len(chunk)
                    _set_state(progress=written)


def _current_exe_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()

    # frozen 이 아닌 dev 환경에서는 self-replace 가 의미 없음.
    raise RuntimeError("self-update is only supported in the packaged exe")


def _updater_exe_path() -> Path:
    # App.spec 의 datas 에 의해 sys._MEIPASS/updater/Updater.exe 로 풀린다.
    base = Path(getattr(sys, "_MEIPASS", "."))
    return base / "updater" / "Updater.exe"


def apply_update() -> dict:
    """체크 → 다운로드 → 검증 → updater.exe 기동 → graceful shutdown.

    반환 시점은 updater 부트스트랩 prepare 가 완료된 직후이며,
    실제 종료는 백그라운드에서 진행된다.
    """
    if not getattr(sys, "frozen", False):
        return {"ok": False, "error": "not_frozen"}

    with _cache_lock:
        meta = _cache["data"]

    if meta is None:
        # 캐시 비어 있으면 강제 갱신.
        check_latest(force=True)
        with _cache_lock:
            meta = _cache["data"]

    if meta is None:
        return {"ok": False, "error": "no_metadata"}

    if not _is_newer(meta["version"], APP_VERSION):
        return {"ok": False, "error": "already_latest"}

    # check_latest 가 릴리즈 assets[] 에서 역참조해 stash 한 EXE 에셋 API URL.
    # 브라우저 url 은 private 레포에서 PAT 인증이 안 되므로 다운로드에 쓰지 않는다.
    download_url = meta.get("_download_url")
    if not download_url:
        return {"ok": False, "error": "no_download_url"}

    _set_state(target_version=meta["version"])

    try:
        current_exe = _current_exe_path()
        updater_exe = _updater_exe_path()

        if not updater_exe.is_file():
            _set_state(status="error", message="updater.exe 누락")
            return {"ok": False, "error": "updater_missing"}

        # tempfile.mkdtemp 로 별도 디렉터리 — 다운로드 실패 시 통째 정리 쉬움.
        tmpdir = Path(tempfile.mkdtemp(prefix="app-upd-"))
        # 임시 파일명을 실행 중인 EXE 이름 기반으로 생성 (하드코딩 배제).
        new_exe_tmp = tmpdir / (Path(sys.executable).stem + ".new.exe")

        _download(download_url, new_exe_tmp, meta.get("size", 0))

        _set_state(status="verifying", message="무결성 검증 중...")
        actual_sha = _sha256_file(new_exe_tmp)

        if actual_sha.lower() != meta["sha256"].lower():
            try:
                new_exe_tmp.unlink(missing_ok=True)
            finally:
                pass
            _set_state(status="error", message="sha256 불일치")
            return {"ok": False, "error": "sha256_mismatch"}

        if not _verify_signature(new_exe_tmp):
            _set_state(status="error", message="서명 검증 실패")
            return {"ok": False, "error": "signature_invalid"}

        # 같은 볼륨이면 os.replace 가 atomic.
        # 교체 대상 스테이징 경로도 실행 EXE 이름 기반으로 생성.
        new_exe = current_exe.parent / (current_exe.stem + ".new.exe")
        try:
            os.replace(new_exe_tmp, new_exe)
        except OSError:
            # 다른 볼륨 (예: tmp 가 다른 드라이브) 대비 fallback.
            import shutil

            shutil.move(str(new_exe_tmp), str(new_exe))

        _set_state(status="staging", message="재시작 준비 중...")

        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200

        subprocess.Popen(
            [
                str(updater_exe),
                str(os.getpid()),
                str(new_exe),
                str(current_exe),
            ],
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )

        _set_state(status="restarting", message="서버 종료 후 교체합니다...")

        # 백그라운드에서 잠시 후 shutdown — 현재 요청 응답이 먼저 돌아가도록.
        def _delayed_shutdown():
            time.sleep(1.0)
            browser.request_shutdown()

        threading.Thread(target=_delayed_shutdown, daemon=True).start()

        return {"ok": True, "target_version": meta["version"]}

    except Exception as e:
        _set_state(status="error", message=str(e))
        return {"ok": False, "error": "exception", "detail": str(e)}
