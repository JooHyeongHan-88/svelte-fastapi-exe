"""GitHub(Enterprise) REST API 공용 헬퍼 — 인증 헤더·매체 타입·TLS 검증.

updater(릴리즈 자동 업데이트)와 content_sync(SKILLS/AGENTS/PROMPTS 런타임 동기화)가
같은 private GHE 레포를 REST API 로 읽는다. 인증·TLS 설정을 한 곳에 모아 두 소비자가
동일한 규약(Authorization: token <PAT>, Windows 시스템 CA, API 버전 핀)을 공유한다.

private 레포의 에셋/콘텐츠는 브라우저 다운로드 URL(`.../download/...`)이나 raw 호스트로는
받을 수 없다 — 그 경로는 웹 세션 쿠키 인증만 받아 PAT 헤더를 무시하고 404 를 돌려준다.
반드시 REST API(`.../api/v3/repos/...`) 에 PAT 헤더를 실어 인증해야 한다.
"""

from __future__ import annotations

import ssl
import sys

from core import config

# GitHub REST API 매체 타입. JSON 은 메타·디렉터리 목록·blob, octet-stream 은 에셋 바이너리.
JSON_ACCEPT = "application/vnd.github+json"
ASSET_ACCEPT = "application/octet-stream"
API_VERSION = "2022-11-28"


def auth_headers() -> dict[str, str]:
    """private GHE repo 읽기용 Authorization 헤더.

    config.REPO_READ_TOKEN(읽기 전용 PAT)이 설정돼 있으면 GitHub 규약의
    `Authorization: token <PAT>` 헤더를 반환한다. 비어 있으면 빈 dict 를 반환해
    익명 GET(public 저장소)으로 동작한다.

    Returns:
        dict[str, str]: 토큰이 있으면 Authorization 헤더, 없으면 빈 dict.
    """
    if config.REPO_READ_TOKEN:
        return {"Authorization": f"token {config.REPO_READ_TOKEN}"}
    return {}


def api_headers(accept: str) -> dict[str, str]:
    """GitHub REST API 요청 헤더 (인증 + 매체 타입 + API 버전).

    Args:
        accept: Accept 헤더 값. 메타·디렉터리·blob 은 `JSON_ACCEPT`,
            에셋 바이너리 다운로드는 `ASSET_ACCEPT` 를 넘긴다.

    Returns:
        dict[str, str]: Accept·API 버전 헤더에 인증 헤더를 합친 dict.
    """
    headers = {
        "Accept": accept,
        "X-GitHub-Api-Version": API_VERSION,
    }
    headers.update(auth_headers())
    return headers


def _make_ssl_verify() -> bool | ssl.SSLContext:
    """httpx SSL 검증 설정.

    APP_REPO_TLS_VERIFY=false: 검증 비활성화 (내부망 자체 서명 인증서 최후 수단).
    Windows: certifi 대신 Windows 인증서 저장소를 써서 회사 내부 CA 를 자동 신뢰한다.
    certifi 는 Windows 인증서 저장소를 읽지 않아 기업 내부 CA 가 누락될 수 있다.

    Returns:
        False(검증 비활성), ssl.SSLContext(Windows 시스템 CA), 또는 True(certifi 기본값).
    """
    if not config.REPO_TLS_VERIFY:
        return False
    if sys.platform == "win32":
        return ssl.create_default_context()
    return True


SSL_VERIFY: bool | ssl.SSLContext = _make_ssl_verify()
