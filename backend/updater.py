"""자동 업데이트.

Nexus raw repository 의 latest.json 을 조회하고, 새 버전이 있으면
sha256 검증 후 번들된 updater.exe 로 self-replace 를 트리거한다.
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

import httpx

import browser
from _version import __version__
from config import (
    LATEST_JSON_URL,
    NEXUS_BASE_URL,
    UPDATE_CHECK_CACHE_TTL,
    UPDATE_CHECK_TIMEOUT,
    UPDATE_DOWNLOAD_TIMEOUT,
)


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
    return __version__


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
    if not url.startswith(NEXUS_BASE_URL + "/"):
        return f"url not under NEXUS_BASE_URL: {url}"

    sha = meta["sha256"]
    if len(sha) != 64 or any(c not in "0123456789abcdefABCDEF" for c in sha):
        return "sha256 not a 64-char hex string"

    return None


def check_latest(force: bool = False) -> dict:
    """latest.json 조회. 실패는 update_available=False 로 silently 반환."""
    now = time.time()

    with _cache_lock:
        cached = _cache["data"]
        cached_at = _cache["at"]

    if not force and cached is not None and now - cached_at < UPDATE_CHECK_CACHE_TTL:
        return _build_check_response(cached)

    try:
        with httpx.Client(timeout=UPDATE_CHECK_TIMEOUT) as client:
            r = client.get(LATEST_JSON_URL)
            r.raise_for_status()
            meta = r.json()
    except Exception as e:
        print(f"update check failed: {e}")
        return {
            "current": __version__,
            "latest": None,
            "update_available": False,
            "error": "check_failed",
        }

    err = _validate_meta(meta)
    if err is not None:
        print(f"latest.json invalid: {err}")
        return {
            "current": __version__,
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
        "current": __version__,
        "latest": latest,
        "update_available": _is_newer(latest, __version__),
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
    _set_state(status="downloading", progress=0, total=expected_size, message="다운로드 중...")

    with httpx.Client(timeout=UPDATE_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        with client.stream("GET", url) as r:
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

    if not _is_newer(meta["version"], __version__):
        return {"ok": False, "error": "already_latest"}

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

        _download(meta["url"], new_exe_tmp, meta.get("size", 0))

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
