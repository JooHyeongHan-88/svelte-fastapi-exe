"""빌드 채널·인증 헤더·GitHub REST API 에셋 해석 — updater 검증.

- QA 빌드는 check_latest 가 네트워크 호출 없이 update_available=False 로 즉시 차단.
- github_api.auth_headers 는 REPO_READ_TOKEN 유무에 따라 Authorization 헤더를 분기한다.
- github_api.api_headers 는 인증 + Accept(JSON/octet-stream) + API 버전 헤더를 합친다.
- _resolve_asset_api_url 은 릴리즈 assets[] 에서 파일명으로 API URL 을 역참조한다.
- _exe_asset_name 은 latest.json 의 브라우저 url 에서 EXE 파일명만 추출한다.
"""

from __future__ import annotations

import pytest

import core.updater as updater
from core import config, github_api


def test_qa_channel_blocks_check_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QA 채널이면 httpx 를 만들지 않고 update_available=False 를 즉시 반환한다."""

    class _ExplodingClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("QA 채널은 네트워크 호출을 하면 안 된다")

    monkeypatch.setattr(config, "BUILD_CHANNEL", "qa")
    monkeypatch.setattr(updater.httpx, "Client", _ExplodingClient)

    result = updater.check_latest(force=True)

    assert result["update_available"] is False
    assert result["latest"] is None
    assert result["error"] is None


def test_auth_headers_present_when_token_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """읽기 토큰이 있으면 GitHub 규약의 token 헤더를 만든다."""
    monkeypatch.setattr(config, "REPO_READ_TOKEN", "ghp_example")

    assert github_api.auth_headers() == {"Authorization": "token ghp_example"}


def test_auth_headers_empty_when_token_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """토큰이 비어 있으면 빈 dict — 익명 GET(public 저장소 한정)."""
    monkeypatch.setattr(config, "REPO_READ_TOKEN", "")

    assert github_api.auth_headers() == {}


def test_api_headers_merge_accept_and_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """api_headers 는 Accept·API 버전·인증 헤더를 하나로 합친다."""
    monkeypatch.setattr(config, "REPO_READ_TOKEN", "ghp_example")

    headers = github_api.api_headers(github_api.ASSET_ACCEPT)

    assert headers["Accept"] == "application/octet-stream"
    assert headers["X-GitHub-Api-Version"] == github_api.API_VERSION
    assert headers["Authorization"] == "token ghp_example"


def test_resolve_asset_api_url_matches_by_name() -> None:
    """assets[] 에서 파일명으로 브라우저가 아닌 API URL(url)을 역참조한다."""
    release = {
        "assets": [
            {
                "name": "latest.json",
                "url": "https://ghe/api/v3/repos/o/r/releases/assets/11",
                "browser_download_url": "https://ghe/o/r/releases/download/v1/latest.json",
            },
            {
                "name": "MyAgent.exe",
                "url": "https://ghe/api/v3/repos/o/r/releases/assets/22",
                "browser_download_url": "https://ghe/o/r/releases/download/v1/MyAgent.exe",
            },
        ]
    }

    assert (
        updater._resolve_asset_api_url(release, "MyAgent.exe")
        == "https://ghe/api/v3/repos/o/r/releases/assets/22"
    )
    assert updater._resolve_asset_api_url(release, "absent.exe") is None


def test_exe_asset_name_extracts_filename_from_browser_url() -> None:
    """latest.json 의 브라우저 url 끝 파일명을 EXE 에셋 키로 추출한다."""
    meta = {"url": "https://ghe/o/r/releases/download/v0.2.0/MyAgent.exe"}

    assert updater._exe_asset_name(meta) == "MyAgent.exe"


def test_fetch_release_and_meta_resolves_download_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """릴리즈 응답에서 latest.json 을 받고 EXE 다운로드 URL 을 stash 한다."""
    monkeypatch.setattr(config, "GITHUB_API_BASE", "https://ghe/api/v3")
    monkeypatch.setattr(config, "REPO_OWNER", "o")
    monkeypatch.setattr(config, "REPO_NAME", "r")

    release = {
        "assets": [
            {
                "name": "latest.json",
                "url": "https://ghe/api/v3/repos/o/r/releases/assets/11",
            },
            {
                "name": "MyAgent.exe",
                "url": "https://ghe/api/v3/repos/o/r/releases/assets/22",
            },
        ]
    }
    manifest = {
        "version": "0.2.0",
        "url": "https://ghe/o/r/releases/download/v0.2.0/MyAgent.exe",
        "sha256": "a" * 64,
        "size": 123,
    }

    class _Resp:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    class _FakeClient:
        def get(self, url: str, headers: dict) -> _Resp:  # noqa: ANN001
            if url.endswith("/releases/latest"):
                return _Resp(release)
            if url.endswith("/assets/11"):
                return _Resp(manifest)
            raise AssertionError(f"unexpected url: {url}")

    meta = updater._fetch_release_and_meta(_FakeClient())

    assert meta["version"] == "0.2.0"
    assert meta["_download_url"] == "https://ghe/api/v3/repos/o/r/releases/assets/22"
