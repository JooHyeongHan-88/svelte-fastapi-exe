"""빌드 채널·인증 헤더 — updater 의 채널 분기와 GHE 읽기 토큰 헤더 검증.

- QA 빌드는 check_latest 가 네트워크 호출 없이 update_available=False 로 즉시 차단.
- _auth_headers 는 REPO_READ_TOKEN 유무에 따라 Authorization 헤더를 분기한다.
"""

from __future__ import annotations

import pytest

import core.updater as updater
from core import config


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

    assert updater._auth_headers() == {"Authorization": "token ghp_example"}


def test_auth_headers_empty_when_token_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """토큰이 비어 있으면 빈 dict — 익명 GET(Nexus·공개 저장소 하위호환)."""
    monkeypatch.setattr(config, "REPO_READ_TOKEN", "")

    assert updater._auth_headers() == {}
