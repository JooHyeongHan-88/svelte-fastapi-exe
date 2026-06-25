"""tracer 확장 API 통합 검증 — sessions/turns/trace 라운드트립 + 경로 가드.

TestClient 로 확장 라우터를 직접 구동한다. 라우터 모듈은 운영과 동일하게 파일 경로로
적재(spec_from_file_location)해 실제 마운트 경로와의 회귀를 막는다. RESULT_DIR 은
tmp_path 로 monkeypatch 한다 (router 모듈 바인딩 + result_store 양쪽). dev 라 Origin 통과.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_SESSION = "tracer-sample-abcd1234"
_TURN = "20260625-000000-000"
_REL = f"result/{_SESSION}/_trace/{_TURN}.jsonl"
_ROUTER_PY = Path(__file__).resolve().parents[1] / "router.py"


def _load_router_module():
    spec = importlib.util.spec_from_file_location("ext_tracer_router_test", _ROUTER_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_trace(trace_dir: Path) -> None:
    trace_dir.mkdir(parents=True)
    lines = [
        {
            "turn_id": _TURN,
            "agent_id": "orchestrator",
            "kind": "turn_start",
            "payload": {"user_message": "지금 몇 시야?"},
        },
        {
            "turn_id": _TURN,
            "agent_id": "orchestrator",
            "iteration": 0,
            "kind": "provider_request",
            "payload": {"model": "gpt-4o", "messages": []},
        },
        "this-is-a-corrupted-line",  # 손상 줄 — skipped 로 집계돼야 한다
    ]
    with (trace_dir / f"{_TURN}.jsonl").open("w", encoding="utf-8") as fh:
        for ln in lines:
            fh.write((ln if isinstance(ln, str) else json.dumps(ln)) + "\n")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    _write_trace(tmp_path / _SESSION / "_trace")
    module = _load_router_module()
    monkeypatch.setattr("core.result_store.RESULT_DIR", tmp_path)
    monkeypatch.setattr(module, "RESULT_DIR", tmp_path)
    app = FastAPI()
    app.include_router(module.get_router())
    return TestClient(app)


def test_list_sessions(client: TestClient) -> None:
    resp = client.get("/api/ext/tracer/sessions")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 1
    assert data[0]["session"] == _SESSION
    assert data[0]["turns"] == 1


def test_list_turns(client: TestClient) -> None:
    resp = client.get("/api/ext/tracer/turns", params={"session": _SESSION})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == _TURN
    assert data[0]["path"] == _REL
    assert data[0]["preview"] == "지금 몇 시야?"


def test_turn_preview_blank_user_message_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # turn_start.user_message 가 공백뿐이면 preview 는 빈 문자열 — 프론트가 턴 ID 로 폴백.
    session = "blank-preview-session"
    trace_dir = tmp_path / session / "_trace"
    trace_dir.mkdir(parents=True)
    line = {
        "turn_id": _TURN,
        "agent_id": "orchestrator",
        "kind": "turn_start",
        "payload": {"user_message": "   "},
    }
    (trace_dir / f"{_TURN}.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")

    module = _load_router_module()
    monkeypatch.setattr("core.result_store.RESULT_DIR", tmp_path)
    monkeypatch.setattr(module, "RESULT_DIR", tmp_path)
    app = FastAPI()
    app.include_router(module.get_router())
    client = TestClient(app)

    resp = client.get("/api/ext/tracer/turns", params={"session": session})
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["preview"] == ""


def test_read_trace_parses_and_counts_skipped(client: TestClient) -> None:
    resp = client.get("/api/ext/tracer/trace", params={"path": _REL})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["events"]) == 2
    assert data["skipped"] == 1
    assert data["events"][0]["kind"] == "turn_start"


def test_turns_rejects_traversal(client: TestClient) -> None:
    resp = client.get("/api/ext/tracer/turns", params={"session": "../etc"})
    assert resp.status_code == 400


def test_trace_rejects_non_trace_path(client: TestClient, tmp_path: Path) -> None:
    # _trace 폴더 밖의 jsonl 은 거부 (디렉터리명 검사).
    other = tmp_path / _SESSION / "other.jsonl"
    other.write_text("{}\n", encoding="utf-8")
    resp = client.get(
        "/api/ext/tracer/trace", params={"path": f"result/{_SESSION}/other.jsonl"}
    )
    assert resp.status_code == 400
