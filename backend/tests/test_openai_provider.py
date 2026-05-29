"""OpenAIProvider 스트리밍 경계 회귀 테스트 — F2(잘림)·F3(깨진 인자)·F4(재시도).

실제 네트워크 없이 fake 스트림/클라이언트를 주입해 검증한다. async 테스트는
pytest-asyncio 없이도 돌도록 동기 래퍼에서 asyncio.run 으로 실행한다.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent.providers.openai as op  # noqa: E402
from agent.models import (  # noqa: E402
    MALFORMED_TOOL_ARGS_KEY,
    DeltaEvent,
    DoneEvent,
    ToolCallEvent,
)
from agent.providers.openai import OpenAIProvider  # noqa: E402
from tests._runner import run_tests  # noqa: E402


# ---------------------------------------------------------------------------
# fake OpenAI 스트리밍 chunk / client
# ---------------------------------------------------------------------------


class _FakeFn:
    def __init__(self, name: str | None, arguments: str | None) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCallDelta:
    def __init__(
        self, index: int, *, id: str | None = None, name=None, arguments=None
    ) -> None:
        self.index = index
        self.id = id
        self.function = _FakeFn(name, arguments)


class _FakeDelta:
    def __init__(self, *, content=None, tool_calls=None, reasoning=None) -> None:
        self.content = content
        self.tool_calls = tool_calls
        if reasoning is not None:
            self.reasoning_content = reasoning


class _FakeChoice:
    def __init__(self, delta: _FakeDelta, finish_reason: str | None) -> None:
        self.delta = delta
        self.finish_reason = finish_reason


class _FakeChunk:
    def __init__(self, choices: list[_FakeChoice]) -> None:
        self.choices = choices


def _chunk(*, content=None, tool_calls=None, finish_reason=None, reasoning=None):
    return _FakeChunk(
        [
            _FakeChoice(
                _FakeDelta(content=content, tool_calls=tool_calls, reasoning=reasoning),
                finish_reason,
            )
        ]
    )


def _make_stream(chunks):
    async def _gen():
        for c in chunks:
            yield c

    return _gen()


class _FakeCompletions:
    """behavior() 가 매 create 호출마다 stream 을 반환하거나 예외를 던진다."""

    def __init__(self, behavior) -> None:
        self._behavior = behavior

    async def create(self, **kwargs):
        return self._behavior()


def _provider_with(behavior) -> OpenAIProvider:
    p = OpenAIProvider(api_key="x", model="m")
    p._client = type(
        "C", (), {"chat": type("Ch", (), {"completions": _FakeCompletions(behavior)})()}
    )()
    return p


def _drain(provider) -> list:
    async def _run():
        return [ev async for ev in provider.astream([], [])]

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# F2 — 잘림(finish_reason=length) 시에도 tool_call flush + DoneEvent 보장
# ---------------------------------------------------------------------------


def test_truncated_stream_still_emits_tool_call_and_done() -> None:
    chunks = [
        _chunk(
            tool_calls=[
                _FakeToolCallDelta(
                    0, id="c1", name="save_artifact", arguments='{"a":1}'
                )
            ]
        ),
        _chunk(finish_reason="length"),  # 잘림 — 과거엔 tool_call 이 증발했다.
    ]
    events = _drain(_provider_with(lambda: _make_stream(chunks)))

    tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert len(tool_calls) == 1, [type(e).__name__ for e in events]
    assert tool_calls[0].call.name == "save_artifact"
    assert tool_calls[0].call.arguments == {"a": 1}
    assert isinstance(events[-1], DoneEvent)


def test_normal_stop_emits_delta_and_done() -> None:
    chunks = [_chunk(content="안녕"), _chunk(finish_reason="stop")]
    events = _drain(_provider_with(lambda: _make_stream(chunks)))
    assert any(isinstance(e, DeltaEvent) and e.content == "안녕" for e in events)
    assert isinstance(events[-1], DoneEvent)
    assert not any(isinstance(e, ToolCallEvent) for e in events)


# ---------------------------------------------------------------------------
# F3 — 깨진 인자 JSON 은 {} 로 뭉개지 않고 MALFORMED 마커로 보존
# ---------------------------------------------------------------------------


def test_malformed_tool_args_preserved_with_marker() -> None:
    chunks = [
        _chunk(
            tool_calls=[
                _FakeToolCallDelta(
                    0, id="c1", name="exec_code", arguments='{"code": "x='
                )
            ]
        ),
        _chunk(finish_reason="tool_calls"),
    ]
    events = _drain(_provider_with(lambda: _make_stream(chunks)))
    tc = [e for e in events if isinstance(e, ToolCallEvent)][0]
    assert MALFORMED_TOOL_ARGS_KEY in tc.call.arguments
    assert isinstance(events[-1], DoneEvent)


def test_empty_args_is_valid_empty_dict() -> None:
    # 인자 없는 정상 호출 — 빈 문자열은 {} 이지 MALFORMED 가 아니다.
    chunks = [
        _chunk(tool_calls=[_FakeToolCallDelta(0, id="c1", name="now", arguments="")]),
        _chunk(finish_reason="tool_calls"),
    ]
    events = _drain(_provider_with(lambda: _make_stream(chunks)))
    tc = [e for e in events if isinstance(e, ToolCallEvent)][0]
    assert tc.call.arguments == {}


# ---------------------------------------------------------------------------
# F4 — 스트림 생성 일시 오류 백오프 재시도
# ---------------------------------------------------------------------------


def test_retries_transient_error_then_succeeds() -> None:
    _orig_base, _orig_uniform = op._RETRY_BASE_DELAY, op.random.uniform
    op._RETRY_BASE_DELAY = 0
    op.random.uniform = lambda a, b: 0  # 지연 0 — 테스트 즉시 진행
    try:
        state = {"n": 0}

        def behavior():
            if state["n"] < 2:
                state["n"] += 1
                raise op.APITimeoutError.__new__(op.APITimeoutError)
            return _make_stream([_chunk(content="복구됨", finish_reason="stop")])

        events = _drain(_provider_with(behavior))
        assert state["n"] == 2  # 2회 재시도 후 성공
        assert any(isinstance(e, DeltaEvent) and e.content == "복구됨" for e in events)
    finally:
        op._RETRY_BASE_DELAY, op.random.uniform = _orig_base, _orig_uniform


def test_retries_exhausted_propagates() -> None:
    _orig_base, _orig_uniform = op._RETRY_BASE_DELAY, op.random.uniform
    op._RETRY_BASE_DELAY = 0
    op.random.uniform = lambda a, b: 0
    try:

        def behavior():
            raise op.RateLimitError.__new__(op.RateLimitError)

        raised = False
        try:
            _drain(_provider_with(behavior))
        except op.RateLimitError:
            raised = True
        assert raised
    finally:
        op._RETRY_BASE_DELAY, op.random.uniform = _orig_base, _orig_uniform


if __name__ == "__main__":
    run_tests(globals())
