"""SKILLS/AGENTS/PROMPTS 마크다운 런타임 동기화 (GitHub 브랜치 → frozen EXE).

frozen EXE 가 기동 시 매핑된 GitHub 브랜치에서 최신 .md 를 가져와 %APPDATA%/content/ 에
저장하고, 레지스트리가 그걸 읽게 한다. EXE 재빌드 없이 콘텐츠만 갱신하기 위함이다.

채널 → 브랜치 매핑: qa→dev, prod→main (APP_CONTENT_SYNC_BRANCH 로 오버라이드). dev(비-frozen)는
동기화하지 않고 로컬 워킹트리 + mtime 핫리로드를 유지한다.

견고성:
    - 어떤 실패(네트워크·404·TLS·파싱)도 raise 하지 않고 last-good→번들로 degrade — 부팅 무중단.
    - 라이브 디렉터리는 모든 fetch 가 성공한 뒤에만 갱신한다(all-or-nothing) — 반쪽 동기화로
      PROMPTS↔SKILLS 가 어긋나는 상태를 방지.
    - private 레포라 Contents/Blobs REST API + PAT 헤더로만 받는다(raw·브라우저 URL 은 PAT 를
      무시하고 404 — update_architecture.md "절대 변경 금지 ②"와 동일 교훈).
"""

from __future__ import annotations

import base64
import json
import logging
import sys
import time
from pathlib import Path

import httpx

from core import config, github_api

logger = logging.getLogger(__name__)

# 동기화 대상 디렉터리 — 레지스트리(prompts/skills/agents)가 읽는 마크다운 루트.
_SYNCED_DIRS: tuple[str, ...] = ("PROMPTS", "SKILLS", "AGENTS")

# 콘텐츠 디렉터리에 함께 저장하는 동기화 상태 파일 (브랜치·파일별 blob sha).
_MANIFEST_NAME = ".manifest.json"

# 채널 → 기본 브랜치. 알 수 없는 채널은 main(가장 보수적).
_CHANNEL_BRANCH: dict[str, str] = {"qa": "dev", "prod": "main"}


def sync_agent_content() -> dict[str, Path]:
    """기동 시 콘텐츠를 동기화하고, 레지스트리가 쓸 효과 디렉터리를 돌려준다.

    비활성(비-frozen·토큰/레포 미설정·플래그 off)이거나 동기화에 쓸 만한 콘텐츠가 없으면
    빈 dict 를 반환해 호출부가 번들(MEIPASS) 콘텐츠를 그대로 쓰게 한다.

    Returns:
        dict[str, Path]: {"PROMPTS": Path, "SKILLS": Path, "AGENTS": Path} 또는
            번들 폴백을 의미하는 빈 dict.
    """
    if not _is_enabled():
        return {}

    branch = _target_branch()
    content_dir = config.CONTENT_DIR

    try:
        with httpx.Client(
            timeout=config.CONTENT_SYNC_TIMEOUT,
            follow_redirects=True,
            verify=github_api.SSL_VERIFY,
        ) as client:
            _sync_with_client(client, branch, content_dir)
    except Exception as exc:
        # 실패해도 부팅을 막지 않는다 — last-good 또는 번들로 degrade.
        logger.warning(
            "content sync failed (%s) — falling back to last-good/bundled content", exc
        )

    return _effective_dirs(content_dir)


def _is_enabled() -> bool:
    """런타임 콘텐츠 동기화를 시도할 조건인지 판정한다(네트워크 전 게이트)."""
    if not getattr(sys, "frozen", False):
        return False  # dev 는 로컬 워킹트리 + 핫리로드 유지.
    if not config.CONTENT_SYNC_ENABLED:
        return False
    # owner/repo 가 비면 GITHUB_API_BASE 유도가 실패한 것 — 무의미한 호출을 막는다.
    return bool(config.REPO_OWNER and config.REPO_NAME)


def _target_branch() -> str:
    """동기화 대상 브랜치 — 오버라이드 우선, 없으면 채널 매핑(qa→dev, prod→main)."""
    if config.CONTENT_SYNC_BRANCH:
        return config.CONTENT_SYNC_BRANCH
    return _CHANNEL_BRANCH.get(config.BUILD_CHANNEL, "main")


def _sync_with_client(client: httpx.Client, branch: str, content_dir: Path) -> None:
    """원격 브랜치의 .md 를 증분 fetch 해 content_dir 에 반영한다.

    모든 디렉터리 목록·변경 blob 을 먼저 메모리에 모은 뒤(예외는 여기서 전파) 한꺼번에
    디스크에 쓴다 — 중간 실패 시 라이브 디렉터리를 건드리지 않기 위함(all-or-nothing).

    Args:
        client: 인증·TLS 가 적용된 httpx.Client.
        branch: 동기화 대상 브랜치명.
        content_dir: 콘텐츠 저장 루트(config.CONTENT_DIR).

    Raises:
        httpx.HTTPStatusError: 브랜치·디렉터리 부재(404 포함) 또는 API 오류.
        ValueError: blob 인코딩이 base64 가 아닐 때.
    """
    old_manifest = _load_manifest(content_dir)
    old_files = (
        old_manifest.get("files", {}) if old_manifest.get("branch") == branch else {}
    )

    new_files: dict[str, str] = {}  # relpath -> blob sha
    to_write: dict[str, bytes] = {}  # relpath -> content (변경/신규만)

    for dir_name in _SYNCED_DIRS:
        for relpath, sha in _list_dir(client, branch, dir_name):
            new_files[relpath] = sha
            # 증분: sha 동일 + 파일 현존이면 blob fetch 생략.
            if old_files.get(relpath) == sha and (content_dir / relpath).is_file():
                continue
            to_write[relpath] = _fetch_blob(client, sha)

    # 여기까지 예외 없이 도달했을 때만 디스크 반영.
    _apply_to_disk(content_dir, new_files, to_write)
    _write_manifest(content_dir, branch, new_files)
    logger.info(
        "content synced from %s (%d files, %d updated)",
        branch,
        len(new_files),
        len(to_write),
    )


def _list_dir(
    client: httpx.Client, branch: str, dir_name: str
) -> list[tuple[str, str]]:
    """Contents API 로 디렉터리의 .md 파일 (relpath, blob sha) 목록을 받는다.

    blob 이 아니거나 .md 가 아니거나 파일명이 안전하지 않은 항목은 건너뛴다.
    디렉터리·브랜치 부재(404)는 raise_for_status 로 전파되어 상위에서 폴백 처리된다.
    """
    url = (
        f"{config.GITHUB_API_BASE}/repos/"
        f"{config.REPO_OWNER}/{config.REPO_NAME}/contents/{dir_name}"
    )
    resp = client.get(
        url,
        params={"ref": branch},
        headers=github_api.api_headers(github_api.JSON_ACCEPT),
    )
    resp.raise_for_status()

    entries: list[tuple[str, str]] = []
    for item in resp.json():
        if item.get("type") != "file":
            continue
        name = item.get("name", "")
        sha = item.get("sha", "")
        if not sha or not _is_safe_markdown_name(name):
            continue
        entries.append((f"{dir_name}/{name}", sha))
    return entries


def _fetch_blob(client: httpx.Client, sha: str) -> bytes:
    """Git Blobs API 로 blob 본문(base64)을 받아 디코드한다."""
    url = (
        f"{config.GITHUB_API_BASE}/repos/"
        f"{config.REPO_OWNER}/{config.REPO_NAME}/git/blobs/{sha}"
    )
    resp = client.get(url, headers=github_api.api_headers(github_api.JSON_ACCEPT))
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("encoding") != "base64":
        raise ValueError(f"unexpected blob encoding: {payload.get('encoding')}")
    return base64.b64decode(payload["content"])


def _is_safe_markdown_name(name: str) -> bool:
    """원격이 준 파일명이 디렉터리 탈출 없는 평범한 .md 인지 검증한다.

    Contents API 의 name 은 단일 파일명이어야 한다 — 경로 구분자·상위 참조·절대경로·
    dotfile 을 거부해 content_dir 밖으로 쓰는 것을 원천 차단한다.
    """
    if not name or name in (".", ".."):
        return False
    if "/" in name or "\\" in name or name.startswith("."):
        return False
    return name.endswith(".md")


def _apply_to_disk(
    content_dir: Path, new_files: dict[str, str], to_write: dict[str, bytes]
) -> None:
    """변경/신규 .md 를 기록하고, 원격에서 사라진 .md 를 제거한다."""
    for relpath, data in to_write.items():
        dest = content_dir / relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    _remove_stale(content_dir, set(new_files))


def _remove_stale(content_dir: Path, keep: set[str]) -> None:
    """라이브 디렉터리에서 원격 목록에 없는 .md 를 삭제해 브랜치와 일치시킨다."""
    for dir_name in _SYNCED_DIRS:
        directory = content_dir / dir_name
        if not directory.is_dir():
            continue
        for md in directory.glob("*.md"):
            if f"{dir_name}/{md.name}" not in keep:
                md.unlink(missing_ok=True)


def _load_manifest(content_dir: Path) -> dict:
    """저장된 manifest 를 읽는다. 없거나 손상 시 빈 dict."""
    try:
        return json.loads((content_dir / _MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_manifest(content_dir: Path, branch: str, files: dict[str, str]) -> None:
    """동기화 상태(브랜치·파일별 sha·시각)를 manifest 로 기록한다."""
    content_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"branch": branch, "files": files, "synced_at": time.time()}
    (content_dir / _MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _effective_dirs(content_dir: Path) -> dict[str, Path]:
    """동기화된 콘텐츠가 정합(완전)할 때만 디렉터리 매핑을 돌려준다.

    manifest 가 가리키는 모든 파일이 디스크에 실존해야 한다 — 이번 동기화가 실패했어도
    직전 성공분(last-good)이 정합하면 그걸 쓴다. 그렇지 않으면 빈 dict(번들 폴백).
    """
    files = _load_manifest(content_dir).get("files")
    if not files:
        return {}
    for relpath in files:
        if not (content_dir / relpath).is_file():
            logger.warning(
                "synced content incomplete (missing %s) — using bundled content",
                relpath,
            )
            return {}
    return {name: content_dir / name for name in _SYNCED_DIRS}
