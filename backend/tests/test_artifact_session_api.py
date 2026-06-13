"""세션 산출물 용량 집계·동반 삭제 검증 — 사이드바 용량 표시 + 세션 삭제 정리.

result_store 의 ``session_usage_by_client`` / ``delete_session_artifacts`` 단위 동작과
``GET /api/artifact/usage`` · ``DELETE /api/artifact/session`` HTTP 경계를 함께 확인한다.
핵심 회귀 잠금: 세션 rename 으로 ``{title}-{cid8}`` 폴더가 여러 개여도 같은 cid8 로
합산·삭제되어야 한다 (산출물은 제목이 아니라 client_id 기준으로 묶이기 때문).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.artifact import router as artifact_router
from core.result_store import delete_session_artifacts, session_usage_by_client

# client_id[:8] 이 폴더 접미사가 된다. A 는 rename 으로 폴더 2개, B 는 1개.
_CID_A = "abcd1234-1111-2222-3333-444444444444"
_CID_B = "deadbeef-5555-6666-7777-888888888888"

_SIZE_A1 = 100
_SIZE_A2 = 50
_SIZE_B = 30


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """tmp_path 를 RESULT_DIR 로 두고 세션 폴더 트리를 만든 뒤 클라이언트 반환.

    - 분석-abcd1234 / 보고서-abcd1234 : 같은 client_id(rename) → cid8 'abcd1234' 합산.
    - 리포트-deadbeef : 다른 client_id → 분리.
    - stray.txt / no-suffix : cid8 접미사가 없어 집계·삭제 대상이 아니다.
    """
    monkeypatch.setattr("core.result_store.RESULT_DIR", tmp_path)

    (tmp_path / "분석-abcd1234" / "20260101-000000").mkdir(parents=True)
    (tmp_path / "분석-abcd1234" / "20260101-000000" / "chart.png").write_bytes(
        b"a" * _SIZE_A1
    )
    (tmp_path / "보고서-abcd1234" / "20260102-000000").mkdir(parents=True)
    (tmp_path / "보고서-abcd1234" / "20260102-000000" / "data.parquet").write_bytes(
        b"b" * _SIZE_A2
    )
    (tmp_path / "리포트-deadbeef" / "20260103-000000").mkdir(parents=True)
    (tmp_path / "리포트-deadbeef" / "20260103-000000" / "note.md").write_bytes(
        b"c" * _SIZE_B
    )
    # cid8 접미사가 없는 잡음 — 집계/삭제에 끼면 안 된다.
    (tmp_path / "stray.txt").write_bytes(b"x" * 999)
    (tmp_path / "no-suffix-dir").mkdir()

    app = FastAPI()
    app.include_router(artifact_router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# session_usage_by_client (단위) + /api/artifact/usage (HTTP)
# ---------------------------------------------------------------------------


def test_usage_merges_renamed_folders_by_cid8(client: TestClient) -> None:
    """rename 으로 폴더가 둘이어도 같은 cid8 로 합산, 다른 세션은 분리된다."""
    usage = session_usage_by_client()

    assert usage["abcd1234"] == _SIZE_A1 + _SIZE_A2
    assert usage["deadbeef"] == _SIZE_B
    # 접미사 없는 잡음은 키로 등장하지 않는다.
    assert set(usage) == {"abcd1234", "deadbeef"}


def test_usage_endpoint_returns_map(client: TestClient) -> None:
    resp = client.get("/api/artifact/usage")
    assert resp.status_code == 200, resp.text

    usage = resp.json()["usage"]
    assert usage["abcd1234"] == _SIZE_A1 + _SIZE_A2
    assert usage["deadbeef"] == _SIZE_B


# ---------------------------------------------------------------------------
# delete_session_artifacts (단위) + DELETE /api/artifact/session (HTTP)
# ---------------------------------------------------------------------------


def test_delete_removes_only_matching_client(
    client: TestClient, tmp_path: Path
) -> None:
    """해당 cid8 폴더만(rename 변형 포함) 삭제하고 다른 세션은 보존한다."""
    resp = client.delete("/api/artifact/session", params={"client_id": _CID_A})
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["ok"] is True
    assert body["removed_dirs"] == 2  # 분석 + 보고서
    assert body["freed_bytes"] == _SIZE_A1 + _SIZE_A2

    assert not (tmp_path / "분석-abcd1234").exists()
    assert not (tmp_path / "보고서-abcd1234").exists()
    # 다른 client_id 와 잡음 파일은 그대로.
    assert (tmp_path / "리포트-deadbeef").exists()
    assert (tmp_path / "stray.txt").exists()


def test_delete_unknown_client_is_noop(client: TestClient) -> None:
    resp = client.delete(
        "/api/artifact/session",
        params={"client_id": "00000000-no-such-session"},
    )
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["removed_dirs"] == 0
    assert body["freed_bytes"] == 0


def test_delete_function_returns_counts(client: TestClient, tmp_path: Path) -> None:
    """단위 함수가 (삭제 폴더 수, 해제 bytes) 를 정확히 돌려준다."""
    removed, freed = delete_session_artifacts(_CID_B)

    assert removed == 1
    assert freed == _SIZE_B
    assert not (tmp_path / "리포트-deadbeef").exists()
    # A 세션은 손대지 않았다.
    assert (tmp_path / "분석-abcd1234").exists()
