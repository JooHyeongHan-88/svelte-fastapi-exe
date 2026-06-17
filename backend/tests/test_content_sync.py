"""SKILLS/AGENTS/PROMPTS 런타임 콘텐츠 동기화 검증.

- 채널→브랜치 매핑(qa→dev, prod→main)과 오버라이드.
- 비활성 게이트(비-frozen·플래그 off·레포 미설정)에서 네트워크 0회 + 빈 dict.
- 증분(불변 sha → blob fetch 생략) · stale 파일 제거.
- path-traversal·비-.md 파일명 거부.
- 효과 디렉터리 선택(완전한 manifest → 디렉터리, 누락 → 번들).
- degradation: 오프라인이어도 last-good 으로 폴백, 부팅 무중단.
"""

from __future__ import annotations

import base64

import pytest

import core.content_sync as content_sync
from core import config


class _FakeResp:
    """httpx.Response 의 최소 대역 — json()·raise_for_status() 만."""

    def __init__(self, payload: object, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> object:
        return self._payload


class _FakeClient:
    """Contents/Blobs API 응답을 흉내내고 blob fetch 횟수를 기록한다."""

    def __init__(self, listings: dict[str, list[dict]], blobs: dict[str, str]) -> None:
        self._listings = listings
        self._blobs = blobs
        self.blob_fetches: list[str] = []

    def get(
        self, url: str, params: dict | None = None, headers: dict | None = None
    ) -> _FakeResp:
        if "/contents/" in url:
            dir_name = url.rsplit("/contents/", 1)[1]
            return _FakeResp(self._listings.get(dir_name, []))
        if "/git/blobs/" in url:
            sha = url.rsplit("/git/blobs/", 1)[1]
            self.blob_fetches.append(sha)
            encoded = base64.b64encode(self._blobs[sha].encode("utf-8")).decode("ascii")
            return _FakeResp({"encoding": "base64", "content": encoded})
        raise AssertionError(f"unexpected url: {url}")

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _entry(name: str, sha: str) -> dict:
    return {"name": name, "sha": sha, "type": "file"}


def _set_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "GITHUB_API_BASE", "https://ghe/api/v3")
    monkeypatch.setattr(config, "REPO_OWNER", "o")
    monkeypatch.setattr(config, "REPO_NAME", "r")


# --------------------------------------------------------------------------- #
# 채널 → 브랜치 매핑
# --------------------------------------------------------------------------- #


def test_target_branch_qa_maps_to_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "CONTENT_SYNC_BRANCH", "")
    monkeypatch.setattr(config, "BUILD_CHANNEL", "qa")
    assert content_sync._target_branch() == "dev"


def test_target_branch_prod_maps_to_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "CONTENT_SYNC_BRANCH", "")
    monkeypatch.setattr(config, "BUILD_CHANNEL", "prod")
    assert content_sync._target_branch() == "main"


def test_target_branch_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "CONTENT_SYNC_BRANCH", "feature/canary")
    monkeypatch.setattr(config, "BUILD_CHANNEL", "prod")
    assert content_sync._target_branch() == "feature/canary"


# --------------------------------------------------------------------------- #
# 비활성 게이트
# --------------------------------------------------------------------------- #


def test_sync_disabled_when_not_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """비-frozen(dev)이면 httpx 를 만들지 않고 빈 dict 를 반환한다."""

    def _explode(**kwargs: object) -> None:
        raise AssertionError("dev 는 네트워크 호출을 하면 안 된다")

    monkeypatch.setattr(content_sync.sys, "frozen", False, raising=False)
    monkeypatch.setattr(content_sync.httpx, "Client", _explode)

    assert content_sync.sync_agent_content() == {}


def test_is_enabled_requires_owner_and_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(content_sync.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config, "CONTENT_SYNC_ENABLED", True)
    monkeypatch.setattr(config, "REPO_OWNER", "")
    monkeypatch.setattr(config, "REPO_NAME", "r")
    assert content_sync._is_enabled() is False


def test_is_enabled_when_frozen_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(content_sync.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config, "CONTENT_SYNC_ENABLED", True)
    _set_repo(monkeypatch)
    assert content_sync._is_enabled() is True


# --------------------------------------------------------------------------- #
# 파일명 안전성
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("guide.md", True),
        ("rank_review.md", True),
        ("../escape.md", False),
        ("sub/dir.md", False),
        ("back\\slash.md", False),
        (".hidden.md", False),
        ("notes.txt", False),
        ("", False),
        ("..", False),
    ],
)
def test_is_safe_markdown_name(name: str, expected: bool) -> None:
    assert content_sync._is_safe_markdown_name(name) is expected


# --------------------------------------------------------------------------- #
# 동기화 본체 — 쓰기·증분·stale 제거
# --------------------------------------------------------------------------- #


def test_sync_writes_files_and_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _set_repo(monkeypatch)
    listings = {
        "PROMPTS": [_entry("base.md", "p1")],
        "SKILLS": [_entry("rank.md", "s1")],
        "AGENTS": [_entry("analyst.md", "a1")],
    }
    blobs = {"p1": "# base", "s1": "# rank", "a1": "# analyst"}
    client = _FakeClient(listings, blobs)

    content_sync._sync_with_client(client, "dev", tmp_path)

    assert (tmp_path / "SKILLS" / "rank.md").read_text(encoding="utf-8") == "# rank"
    manifest = content_sync._load_manifest(tmp_path)
    assert manifest["branch"] == "dev"
    assert manifest["files"]["AGENTS/analyst.md"] == "a1"
    assert sorted(client.blob_fetches) == ["a1", "p1", "s1"]


def test_sync_incremental_skips_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _set_repo(monkeypatch)
    listings = {
        "PROMPTS": [_entry("base.md", "p1")],
        "SKILLS": [_entry("rank.md", "s1")],
        "AGENTS": [_entry("analyst.md", "a1")],
    }
    blobs = {"p1": "# base", "s1": "# rank", "a1": "# analyst"}

    content_sync._sync_with_client(_FakeClient(listings, blobs), "dev", tmp_path)

    # 같은 sha 로 재동기화 → blob fetch 0회 (디스크 파일 현존 + sha 일치).
    second = _FakeClient(listings, blobs)
    content_sync._sync_with_client(second, "dev", tmp_path)
    assert second.blob_fetches == []


def test_sync_refetches_changed_and_removes_stale(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _set_repo(monkeypatch)
    first = {
        "PROMPTS": [_entry("base.md", "p1")],
        "SKILLS": [_entry("rank.md", "s1"), _entry("old.md", "o1")],
        "AGENTS": [_entry("analyst.md", "a1")],
    }
    blobs = {"p1": "# base", "s1": "# rank", "o1": "# old", "a1": "# analyst"}
    content_sync._sync_with_client(_FakeClient(first, blobs), "dev", tmp_path)
    assert (tmp_path / "SKILLS" / "old.md").is_file()

    # rank.md 내용 변경(sha s2) + old.md 제거.
    second_listings = {
        "PROMPTS": [_entry("base.md", "p1")],
        "SKILLS": [_entry("rank.md", "s2")],
        "AGENTS": [_entry("analyst.md", "a1")],
    }
    blobs["s2"] = "# rank v2"
    client = _FakeClient(second_listings, blobs)
    content_sync._sync_with_client(client, "dev", tmp_path)

    assert client.blob_fetches == ["s2"]  # 변경분만
    assert (tmp_path / "SKILLS" / "rank.md").read_text(encoding="utf-8") == "# rank v2"
    assert not (tmp_path / "SKILLS" / "old.md").exists()  # stale 제거


def test_sync_skips_unsafe_and_non_markdown(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _set_repo(monkeypatch)
    listings = {
        "PROMPTS": [
            _entry("base.md", "p1"),
            _entry("readme.txt", "x1"),
            {"name": "nested", "sha": "d1", "type": "dir"},
        ],
        "SKILLS": [],
        "AGENTS": [],
    }
    blobs = {"p1": "# base"}
    client = _FakeClient(listings, blobs)

    content_sync._sync_with_client(client, "dev", tmp_path)

    assert client.blob_fetches == ["p1"]  # .txt·dir 무시
    assert content_sync._load_manifest(tmp_path)["files"] == {"PROMPTS/base.md": "p1"}


# --------------------------------------------------------------------------- #
# 효과 디렉터리 선택
# --------------------------------------------------------------------------- #


def test_effective_dirs_complete(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _set_repo(monkeypatch)
    listings = {
        "PROMPTS": [_entry("base.md", "p1")],
        "SKILLS": [_entry("rank.md", "s1")],
        "AGENTS": [_entry("analyst.md", "a1")],
    }
    blobs = {"p1": "# base", "s1": "# rank", "a1": "# analyst"}
    content_sync._sync_with_client(_FakeClient(listings, blobs), "dev", tmp_path)

    dirs = content_sync._effective_dirs(tmp_path)
    assert dirs == {
        "PROMPTS": tmp_path / "PROMPTS",
        "SKILLS": tmp_path / "SKILLS",
        "AGENTS": tmp_path / "AGENTS",
    }


def test_effective_dirs_incomplete_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _set_repo(monkeypatch)
    listings = {
        "PROMPTS": [_entry("base.md", "p1")],
        "SKILLS": [_entry("rank.md", "s1")],
        "AGENTS": [_entry("analyst.md", "a1")],
    }
    blobs = {"p1": "# base", "s1": "# rank", "a1": "# analyst"}
    content_sync._sync_with_client(_FakeClient(listings, blobs), "dev", tmp_path)

    # manifest 는 그대로지만 파일 하나가 사라지면 불완전 → 빈 dict(번들 폴백).
    (tmp_path / "SKILLS" / "rank.md").unlink()
    assert content_sync._effective_dirs(tmp_path) == {}


def test_effective_dirs_no_manifest(tmp_path) -> None:
    assert content_sync._effective_dirs(tmp_path) == {}


# --------------------------------------------------------------------------- #
# Degradation — 오프라인이어도 last-good 으로 폴백
# --------------------------------------------------------------------------- #


def test_sync_offline_falls_back_to_last_good(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _set_repo(monkeypatch)
    # 1) 직전 성공분(last-good)을 디스크에 만들어 둔다.
    listings = {
        "PROMPTS": [_entry("base.md", "p1")],
        "SKILLS": [_entry("rank.md", "s1")],
        "AGENTS": [_entry("analyst.md", "a1")],
    }
    blobs = {"p1": "# base", "s1": "# rank", "a1": "# analyst"}
    content_sync._sync_with_client(_FakeClient(listings, blobs), "dev", tmp_path)

    # 2) frozen·활성·레포 설정 + 오프라인 클라이언트로 sync_agent_content 전체 경로 실행.
    monkeypatch.setattr(content_sync.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config, "CONTENT_SYNC_ENABLED", True)
    monkeypatch.setattr(config, "CONTENT_DIR", tmp_path)
    monkeypatch.setattr(config, "CONTENT_SYNC_BRANCH", "")
    monkeypatch.setattr(config, "BUILD_CHANNEL", "qa")

    class _OfflineClient:
        def __enter__(self) -> _OfflineClient:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def get(self, *args: object, **kwargs: object) -> None:
            raise content_sync.httpx.ConnectError("offline")

    monkeypatch.setattr(content_sync.httpx, "Client", lambda **kwargs: _OfflineClient())

    dirs = content_sync.sync_agent_content()
    # 동기화는 실패했지만 last-good 이 정합하므로 콘텐츠 디렉터리를 그대로 쓴다.
    assert dirs == {
        "PROMPTS": tmp_path / "PROMPTS",
        "SKILLS": tmp_path / "SKILLS",
        "AGENTS": tmp_path / "AGENTS",
    }
