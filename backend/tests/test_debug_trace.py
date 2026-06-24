"""디버그 트레이스 레코더 + TracingProvider 단위 테스트.

검증 대상:
    - 비활성 시 no-op (파일 미생성·예외 없음)
    - 활성 시 JSONL 스키마(상관키 포함) append
    - api_key 마스킹으로 평문 키 미노출
    - IO 오류 best-effort 흡수
    - TracingProvider 가 이벤트를 변형 없이 통과시키며 in/out 기록
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

from agent.debug import trace
from agent.models import (
    DeltaEvent,
    DoneEvent,
    Message,
    StreamEvent,
    ToolCall,
    ToolCallEvent,
)


@pytest.fixture
def enable_trace(monkeypatch, tmp_path):
    """트레이스를 활성화하고 세션 폴더를 tmp_path 로 격리한다."""
    monkeypatch.setattr(trace, "DEBUG_TRACE_ENABLED", True)
    monkeypatch.setattr(trace, "session_dir", lambda: tmp_path / "session")
    yield tmp_path / "session"


def _read_lines(trace_obj: trace.TurnTrace) -> list[dict]:
    return [json.loads(ln) for ln in trace_obj.path.read_text("utf-8").splitlines()]


def test_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(trace, "DEBUG_TRACE_ENABLED", False)
    monkeypatch.setattr(
        trace, "_active_trace", trace.contextvars.ContextVar("t", default=None)
    )
    assert trace.start_turn_trace() is None
    # 활성 트레이스가 없으면 record 는 조용히 통과한다.
    trace.record("anything", foo="bar")


def test_records_jsonl_with_scope(enable_trace):
    t = trace.start_turn_trace()
    assert t is not None
    with trace.scope(agent_id="orchestrator", depth=0, iteration=2):
        trace.record("turn_start", user_message="안녕")

    rows = _read_lines(t)
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "turn_start"
    assert row["agent_id"] == "orchestrator"
    assert row["depth"] == 0
    assert row["iteration"] == 2
    assert row["payload"]["user_message"] == "안녕"
    assert row["turn_id"] == t.turn_id


def test_scope_restores_after_block(enable_trace):
    trace.start_turn_trace()
    with trace.scope(agent_id="sub", depth=1, iteration=0):
        pass
    # 블록을 벗어나면 기본 scope 로 복원된다.
    assert trace._scope.get().agent_id == ""


def test_mask_url():
    assert trace.mask_url("https://api.example.com/v1") == "https://api.example.com/v1"
    assert "secret" not in trace.mask_url("https://x.com/v1?token=secret")
    assert "•••" in trace.mask_url("https://x.com/v1?api-key=abcd1234")


def test_record_swallows_io_error(enable_trace, monkeypatch):
    t = trace.start_turn_trace()
    assert t is not None

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(trace.json, "dumps", _boom)
    # best-effort — 예외가 전파되지 않아야 한다.
    trace.record("turn_start", x=1)


class _FakeProvider:
    """astream 으로 고정 이벤트 시퀀스를 내보내는 가짜 provider."""

    def __init__(self, events: list[StreamEvent]) -> None:
        self._events = events
        self.seen_messages: list[Message] | None = None

    async def astream(self, messages, tools) -> AsyncIterator[StreamEvent]:
        self.seen_messages = messages
        for ev in self._events:
            yield ev


async def test_tracing_provider_passthrough_and_records(enable_trace):
    t = trace.start_turn_trace()
    assert t is not None
    events: list[StreamEvent] = [
        DeltaEvent(content="안"),
        DeltaEvent(content="녕"),
        ToolCallEvent(call=ToolCall(id="c1", name="save_artifact", arguments={"a": 1})),
        DoneEvent(finish_reason="tool_calls"),
    ]
    inner = _FakeProvider(events)
    wrapped = trace.TracingProvider(
        inner, model="gpt-4o", masked_key="sk-p••••••4f2a", base_url=None
    )
    msgs = [Message(role="user", content="hi")]

    out = [ev async for ev in wrapped.astream(msgs, [])]
    # 이벤트는 변형 없이 동일하게 통과한다.
    assert out == events
    assert inner.seen_messages is msgs

    rows = _read_lines(t)
    kinds = [r["kind"] for r in rows]
    assert kinds == ["provider_request", "provider_response"]
    req = rows[0]["payload"]
    assert req["model"] == "gpt-4o"
    assert req["api_key"] == "sk-p••••••4f2a"
    resp = rows[1]["payload"]
    assert resp["text"] == "안녕"
    assert resp["finish_reason"] == "tool_calls"
    assert resp["tool_calls"][0]["name"] == "save_artifact"


def test_no_plaintext_key_in_trace(enable_trace):
    t = trace.start_turn_trace()
    assert t is not None
    trace.record("provider_request", api_key="sk-p••••••4f2a", model="x")
    raw = t.path.read_text("utf-8")
    assert "sk-proj-realsecret" not in raw
    assert "sk-p••••••4f2a" in raw
