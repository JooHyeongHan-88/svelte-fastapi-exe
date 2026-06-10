"""run_turn 최상위 예외 경로(R1) — 실패 턴 영속 + pending 클리어 + DoneEvent 보장.

provider 영구 오류(401 등)로 턴이 터져도:
    1. 사용자 메시지가 백엔드 히스토리에서 증발하지 않는다.
    2. mid-mutation pending 이 다음 턴 프롬프트를 오염시키지 않는다.
    3. ErrorEvent 뒤에 DoneEvent 가 정확히 1회 따라온다.
    4. 미해결 tool_call 쌍은 영속 전에 placeholder 로 보정된다 (OpenAI 400 방지).
"""

from __future__ import annotations

from agent import harness
from agent.harness import _ERROR_TOOL_PLACEHOLDER, _balance_all_unresolved
from agent.models import (
    AgentState,
    DoneEvent,
    ErrorEvent,
    Message,
    ToolCall,
)
from agent.registries.agents import registry as agent_registry
from agent.registries.prompts import registry as prompt_registry
from agent.registries.skills import registry as skill_registry
from agent.registries.tools import registry
from agent.stores.conversation import ConversationStore


class _MemStateStore:
    """AgentStateStore 의 인메모리 대체 — 디스크 flush 없이 동일 인터페이스."""

    def __init__(self) -> None:
        self.states: dict[str, AgentState] = {}

    def get(self, client_id: str) -> AgentState:
        return self.states.setdefault(client_id, AgentState())

    def set(self, client_id: str, state: AgentState) -> None:
        self.states[client_id] = state

    def reset(self, client_id: str) -> None:
        self.states.pop(client_id, None)


class _ExplodingProvider:
    """astream 첫 이터레이션에서 즉시 예외 — 영구 오류(401 등) 시뮬레이션."""

    async def astream(self, messages, tools):  # noqa: ANN001
        raise RuntimeError("simulated permanent provider failure")
        yield  # pragma: no cover — async generator 마커


async def _run_failing_turn(
    client_id: str, store: ConversationStore, state_store: _MemStateStore
) -> list:
    agent_registry.load()
    skill_registry.load()
    return [
        ev
        async for ev in harness.run_turn(
            client_id,
            "안녕하세요",
            store=store,
            state_store=state_store,
            skill_registry=skill_registry,
            prompt_registry=prompt_registry,
            registry=registry,
            agent_registry=agent_registry,
            provider=_ExplodingProvider(),
            max_iterations=3,
            max_agent_calls=5,
        )
    ]


async def test_error_path_emits_error_then_done() -> None:
    store = ConversationStore(max_history=40)
    state_store = _MemStateStore()

    events = await _run_failing_turn("err-1", store, state_store)

    assert isinstance(events[-1], DoneEvent), "에러 경로에서 DoneEvent 누락"
    error_events = [e for e in events if isinstance(e, ErrorEvent)]
    assert len(error_events) == 1
    # F12: 예외 상세(메시지·키)는 노출하지 않고 타입명만.
    assert "RuntimeError" in error_events[0].message
    assert "simulated" not in error_events[0].message


async def test_error_path_persists_user_message() -> None:
    store = ConversationStore(max_history=40)
    state_store = _MemStateStore()

    await _run_failing_turn("err-2", store, state_store)

    history = store.get_history("err-2")
    assert any(m.role == "user" and m.content == "안녕하세요" for m in history), (
        "실패 턴의 사용자 메시지가 히스토리에서 증발"
    )


async def test_error_path_clears_stale_pending() -> None:
    store = ConversationStore(max_history=40)
    state_store = _MemStateStore()
    state_store.set(
        "err-3",
        AgentState(
            pending_tool="echo",
            pending_args={"text": "hi"},
            missing_slots={"text": "무엇을?"},
            pending_sub_agent="data_agent",
            pending_sub_task="요약",
        ),
    )

    await _run_failing_turn("err-3", store, state_store)

    final = state_store.get("err-3")
    assert final.pending_tool is None
    assert final.pending_args == {}
    assert final.missing_slots == {}
    assert final.pending_sub_agent is None
    assert final.pending_sub_task is None


# ---------------------------------------------------------------------------
# _balance_all_unresolved — 전수 스캔 쌍 보정 단위 검증
# ---------------------------------------------------------------------------


def _assistant(content: str, *calls: ToolCall) -> Message:
    return Message(role="assistant", content=content, tool_calls=list(calls))


def test_balance_all_unresolved_inserts_adjacent_placeholder() -> None:
    """placeholder 는 끝 append 가 아니라 해당 assistant 블록 뒤에 삽입된다."""
    msgs = [
        Message(role="user", content="go"),
        _assistant(
            "",
            ToolCall(id="a1", name="t", arguments={}),
            ToolCall(id="a2", name="t", arguments={}),
        ),
        Message(role="tool", content="ok", tool_call_id="a1"),
        _assistant("후속", ToolCall(id="b1", name="t", arguments={})),
    ]

    _balance_all_unresolved(msgs)

    assert [m.role for m in msgs] == [
        "user",
        "assistant",
        "tool",
        "tool",
        "assistant",
        "tool",
    ]
    assert msgs[3].tool_call_id == "a2"
    assert msgs[3].content == _ERROR_TOOL_PLACEHOLDER
    assert msgs[5].tool_call_id == "b1"


def test_balance_all_unresolved_is_idempotent() -> None:
    msgs = [
        _assistant("", ToolCall(id="x1", name="t", arguments={})),
    ]
    _balance_all_unresolved(msgs)
    _balance_all_unresolved(msgs)
    assert len(msgs) == 2, "재호출 시 placeholder 중복 삽입"


def test_balance_all_unresolved_noop_when_balanced() -> None:
    msgs = [
        Message(role="user", content="go"),
        _assistant("", ToolCall(id="x1", name="t", arguments={})),
        Message(role="tool", content="ok", tool_call_id="x1"),
        Message(role="assistant", content="답변"),
    ]
    before = len(msgs)
    _balance_all_unresolved(msgs)
    assert len(msgs) == before
