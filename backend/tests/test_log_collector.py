"""Loki 사용 로그 수집기(LokiLogCollector·TurnLogTap) 검증.

- 미설정(base_url 빈 값) 시 완전 no-op — 워커 미기동, 큐 없음.
- emit() 은 절대 블로킹/raise 하지 않는다 (큐 포화 시 조용히 드롭).
- 배치 push body 가 Loki 스키마(stream 라벨 저-카디널리티 / values 라인)를 따른다.
- TurnLogTap 이 StreamEvent 흐름을 올바른 이벤트로 변환한다(delta 누적·tool 카운트 등).
- push 실패(HTTPError/OSError)는 삼켜지고 앱을 방해하지 않는다.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agent.models import (
    AgentProgressEvent,
    AgentSwitchEvent,
    DeltaEvent,
    ErrorEvent,
    ToolCall,
    ToolCallEvent,
    ToolResultEvent,
)
from core.log_collector import LokiLogCollector, TurnLogTap, _truncate


def _make_collector(base_url: str = "https://loki.example.com") -> LokiLogCollector:
    return LokiLogCollector(
        base_url,
        user="tester",
        app="SENPIA",
        env="qa",
        ssl_verify=True,
        timeout=5,
    )


# ---------------------------------------------------------------------------
# 비활성 게이트 — base_url 빈 값
# ---------------------------------------------------------------------------


def test_disabled_when_base_url_empty() -> None:
    collector = _make_collector(base_url="")
    assert collector.enabled is False


def test_start_is_noop_when_disabled() -> None:
    collector = _make_collector(base_url="")
    collector.start()
    assert collector._worker is None
    assert collector._queue is None


def test_emit_before_start_does_not_raise() -> None:
    """워커 미기동 상태(큐=None)에서 emit 은 조용히 무시된다."""
    collector = _make_collector()
    collector.emit("user_query", session="s1", text="hello")  # raise 없어야 함


@pytest.mark.asyncio
async def test_aclose_before_start_is_noop() -> None:
    collector = _make_collector(base_url="")
    await collector.aclose()  # 워커가 없으므로 즉시 반환, 에러 없음


# ---------------------------------------------------------------------------
# emit() — 절대 블로킹/raise 하지 않음, 큐 포화 시 드롭
# ---------------------------------------------------------------------------


def test_emit_drops_silently_when_queue_full() -> None:
    collector = _make_collector()
    collector._queue = asyncio.Queue(maxsize=1)
    collector.emit("tool_call", session="s1", tool="a")
    collector.emit("tool_call", session="s1", tool="b")  # 큐 포화 — 드롭, raise 없음
    assert collector._queue.qsize() == 1


# ---------------------------------------------------------------------------
# push body 스키마 — 라벨 저-카디널리티, session 은 라인에만
# ---------------------------------------------------------------------------


def test_to_body_groups_by_event_label_and_keeps_session_out_of_stream() -> None:
    collector = _make_collector()
    collector._queue = asyncio.Queue()
    collector.emit("tool_call", session="session-uuid-1", tool="exec_code", args="x")
    collector.emit("user_query", session="session-uuid-2", text="hi")

    entries = [collector._queue.get_nowait(), collector._queue.get_nowait()]
    body = collector._to_body(entries)

    streams = {s["stream"]["event"]: s for s in body["streams"]}
    assert set(streams) == {"tool_call", "user_query"}

    tool_call_stream = streams["tool_call"]
    # 라벨은 저-카디널리티 4종만 — session(UUID) 은 라벨에 없어야 한다.
    assert set(tool_call_stream["stream"]) == {"app", "user", "env", "event"}
    assert tool_call_stream["stream"]["app"] == "SENPIA"
    assert tool_call_stream["stream"]["user"] == "tester"
    assert tool_call_stream["stream"]["env"] == "qa"

    ts, line = tool_call_stream["values"][0]
    assert ts.isdigit()
    payload = json.loads(line)
    assert payload["session"] == "session-uuid-1"
    assert payload["tool"] == "exec_code"


def test_to_body_truncates_long_string_fields() -> None:
    collector = _make_collector()
    collector._queue = asyncio.Queue()
    huge = "x" * 50_000
    collector.emit("assistant_reply", session="s1", text=huge)
    body = collector._to_body([collector._queue.get_nowait()])
    line = body["streams"][0]["values"][0][1]
    payload = json.loads(line)
    assert len(payload["text"]) < len(huge)
    assert payload["text"].endswith("…(truncated)")


def test_truncate_helper_is_idempotent_under_limit() -> None:
    assert _truncate("short") == "short"


# ---------------------------------------------------------------------------
# push — 성공/실패 (best-effort, 예외를 삼킨다)
# ---------------------------------------------------------------------------


class _RecordingClient:
    """httpx.AsyncClient 의 최소 대역 — post() 호출만 기록."""

    def __init__(self, raise_exc: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._raise_exc = raise_exc

    async def post(self, url: str, json: dict) -> httpx.Response:
        self.calls.append({"url": url, "json": json})
        if self._raise_exc is not None:
            raise self._raise_exc
        return httpx.Response(204, request=httpx.Request("POST", url))


@pytest.mark.asyncio
async def test_push_posts_to_loki_push_endpoint() -> None:
    collector = _make_collector()
    collector._client = _RecordingClient()
    collector._queue = asyncio.Queue()
    collector.emit("turn_end", session="s1", cancelled=False)
    entries = [collector._queue.get_nowait()]

    await collector._push(entries)

    assert (
        collector._client.calls[0]["url"] == "https://loki.example.com/loki/api/v1/push"
    )


@pytest.mark.asyncio
async def test_push_swallows_http_error_without_raising() -> None:
    collector = _make_collector()
    collector._client = _RecordingClient(raise_exc=httpx.ConnectError("down"))
    collector._queue = asyncio.Queue()
    collector.emit("turn_end", session="s1", cancelled=False)
    entries = [collector._queue.get_nowait()]

    await collector._push(entries)  # raise 없어야 함 — best-effort


@pytest.mark.asyncio
async def test_push_swallows_os_error_without_raising() -> None:
    collector = _make_collector()
    collector._client = _RecordingClient(raise_exc=OSError("network unreachable"))
    collector._queue = asyncio.Queue()
    collector.emit("turn_end", session="s1", cancelled=False)
    entries = [collector._queue.get_nowait()]

    await collector._push(entries)  # raise 없어야 함


@pytest.mark.asyncio
async def test_push_noop_when_client_absent() -> None:
    collector = _make_collector()
    collector._client = None
    await collector._push([])  # 초기화 전 방어 — raise 없어야 함


# ---------------------------------------------------------------------------
# start()/aclose() 생애주기 — 실제 event loop 필요
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_launches_worker_and_aclose_flushes_and_stops() -> None:
    collector = _make_collector()
    collector.start()
    assert collector._worker is not None
    assert collector.enabled is True

    pushed: list[list] = []

    async def _fake_push(batch: list) -> None:
        pushed.append(batch)

    collector._push = _fake_push  # type: ignore[method-assign]
    collector.emit("turn_end", session="s1", cancelled=False)

    await collector.aclose()

    assert collector._worker is None
    # 워커 실행 중 flush 되었거나, drain 경로에서 최소 1회 push 되었어야 한다.
    assert sum(len(b) for b in pushed) >= 1


# ---------------------------------------------------------------------------
# TurnLogTap — StreamEvent → 사용 로그 변환
# ---------------------------------------------------------------------------


class _CapturingCollector:
    """LokiLogCollector 대역 — emit 호출을 그대로 기록."""

    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    def emit(self, event: str, **fields: object) -> None:
        self.emitted.append((event, fields))


def test_tap_query_emits_user_query() -> None:
    collector = _CapturingCollector()
    tap = TurnLogTap(collector, session="s1")
    tap.query("안녕하세요", title="첫 대화")
    assert collector.emitted == [
        ("user_query", {"session": "s1", "text": "안녕하세요", "title": "첫 대화"})
    ]


def test_tap_accumulates_delta_into_single_assistant_reply() -> None:
    collector = _CapturingCollector()
    tap = TurnLogTap(collector, session="s1")
    tap.observe(DeltaEvent(content="안"))
    tap.observe(DeltaEvent(content="녕"))
    tap.finish(cancelled=False)

    replies = [e for e in collector.emitted if e[0] == "assistant_reply"]
    assert len(replies) == 1
    assert replies[0][1]["text"] == "안녕"


def test_tap_skips_empty_assistant_reply() -> None:
    """delta 가 전혀 없으면 assistant_reply 를 남기지 않는다(빈 로그 라인 방지)."""
    collector = _CapturingCollector()
    tap = TurnLogTap(collector, session="s1")
    tap.finish(cancelled=False)
    assert not [e for e in collector.emitted if e[0] == "assistant_reply"]


def test_tap_counts_tool_calls_and_errors_into_turn_end() -> None:
    collector = _CapturingCollector()
    tap = TurnLogTap(collector, session="s1")
    tap.observe(
        ToolCallEvent(
            call=ToolCall(id="1", name="exec_code", arguments={"code": "1+1"})
        )
    )
    tap.observe(
        ToolResultEvent(tool_call_id="1", name="exec_code", result="2", is_error=False)
    )
    tap.observe(
        ToolResultEvent(
            tool_call_id="2", name="broken_tool", result="fail", is_error=True
        )
    )
    tap.finish(cancelled=False)

    turn_end = next(e for e in collector.emitted if e[0] == "turn_end")[1]
    assert turn_end["tool_calls"] == 1
    assert turn_end["errors"] == 1
    assert turn_end["cancelled"] is False

    tool_call_logs = [e for e in collector.emitted if e[0] == "tool_call"]
    assert tool_call_logs[0][1]["tool"] == "exec_code"
    assert json.loads(tool_call_logs[0][1]["args"]) == {"code": "1+1"}


def test_tap_reports_cancelled_turn() -> None:
    collector = _CapturingCollector()
    tap = TurnLogTap(collector, session="s1")
    tap.finish(cancelled=True)
    turn_end = next(e for e in collector.emitted if e[0] == "turn_end")[1]
    assert turn_end["cancelled"] is True


def test_tap_emits_subagent_switch() -> None:
    collector = _CapturingCollector()
    tap = TurnLogTap(collector, session="s1")
    tap.observe(
        AgentSwitchEvent(
            from_agent="orchestrator", to_agent="coding_agent", reason="delegate"
        )
    )
    switch = next(e for e in collector.emitted if e[0] == "subagent")[1]
    assert switch["to_agent"] == "coding_agent"


def test_tap_emits_error_event() -> None:
    collector = _CapturingCollector()
    tap = TurnLogTap(collector, session="s1")
    tap.observe(ErrorEvent(message="boom", is_fallback=True))
    error = next(e for e in collector.emitted if e[0] == "error")[1]
    assert error["message"] == "boom"
    assert error["is_fallback"] is True


def test_tap_unwraps_subagent_progress_tool_call() -> None:
    """AgentProgressEvent 로 래핑된 서브에이전트 tool_call 도 집계에 포함된다."""
    collector = _CapturingCollector()
    tap = TurnLogTap(collector, session="s1")
    tap.observe(
        AgentProgressEvent(
            agent_id="coding_agent",
            inner_type="tool_call",
            inner_payload={
                "call": {"id": "1", "name": "save_artifact", "arguments": {}}
            },
        )
    )
    tap.finish(cancelled=False)

    turn_end = next(e for e in collector.emitted if e[0] == "turn_end")[1]
    assert turn_end["tool_calls"] == 1

    tool_call_log = next(e for e in collector.emitted if e[0] == "tool_call")[1]
    assert tool_call_log["tool"] == "save_artifact"
    assert tool_call_log["agent"] == "coding_agent"
