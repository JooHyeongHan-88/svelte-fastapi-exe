"""반복 예산 임박 wind-down — hard-cut 전에 LLM 에게 마무리를 지시한다 (R7).

실패 없이 작업이 진행 중인데 반복 상한(max_iterations)·turn budget 만 소진되어
사용자 노출 단계(display_*)가 잘리는 시나리오 방지. 검증 항목:
- 남은 호출(반복 상한·budget 중 작은 쪽)이 임계(2회) 이하로 떨어지는 시점에
  [System] wind-down 메시지가 정확히 1회 주입된다.
- 지시를 따라 도구를 멈추고 텍스트로 응답한 턴은 ErrorEvent 없이 정상 종료된다.
- wind-down 메시지는 turn-local — 대화 히스토리에 영속되지 않는다.
"""

from __future__ import annotations

from agent import harness
from agent.models import (
    AgentState,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    ToolCall,
    ToolCallEvent,
)
from agent.registries.agents import registry as agent_registry
from agent.registries.prompts import registry as prompt_registry
from agent.registries.skills import registry as skill_registry
from agent.registries.tools import registry
from agent.stores.conversation import ConversationStore

# 주입 지시문 식별 토큰 — 문구 전체를 결합하지 않고 핵심 구절만 검사한다.
_WIND_DOWN_TOKEN = "반복 예산"


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


def _saw_wind_down(messages) -> bool:  # noqa: ANN001
    return any(
        m.role == "user"
        and (m.content or "").startswith("[System]")
        and _WIND_DOWN_TOKEN in (m.content or "")
        for m in messages
    )


class _PlanningProvider:
    """매 호출 add_todo 를 반복하다 wind-down 지시를 받으면 텍스트로 종료하는 가짜 LLM.

    실 LLM 의 '진행은 성공 중인데 예산이 모자라는' 패턴을 재현한다 — 지시를 따르는
    순응 모델 기준으로 턴이 fallback 없이 깔끔하게 닫히는지 본다.
    """

    def __init__(self) -> None:
        self.call_count = 0
        self.wind_down_seen_at: list[int] = []

    async def astream(self, messages, tools):  # noqa: ANN001
        self.call_count += 1
        if _saw_wind_down(messages):
            self.wind_down_seen_at.append(self.call_count)
            yield DeltaEvent(content="마무리 요약입니다.")
            yield DoneEvent()
            return
        yield ToolCallEvent(
            call=ToolCall(
                id=f"c{self.call_count}",
                name="add_todo",
                arguments={"items": [{"description": f"단계 {self.call_count}"}]},
            )
        )
        yield DoneEvent()


class _ShortTaskProvider:
    """2번째 호출에서 자연 종료하는 가짜 LLM — 예산이 넉넉할 때 비발화 검증용."""

    def __init__(self) -> None:
        self.saw_wind_down = False
        self.call_count = 0

    async def astream(self, messages, tools):  # noqa: ANN001
        self.call_count += 1
        if _saw_wind_down(messages):
            self.saw_wind_down = True
        if self.call_count == 1:
            yield ToolCallEvent(
                call=ToolCall(
                    id="c1",
                    name="add_todo",
                    arguments={"items": [{"description": "단계 1"}]},
                )
            )
            yield DoneEvent()
            return
        yield DeltaEvent(content="완료했습니다.")
        yield DoneEvent()


async def _run_turn(
    client_id: str,
    provider,  # noqa: ANN001
    *,
    max_iterations: int,
    max_agent_calls: int,
) -> tuple[list, ConversationStore]:
    agent_registry.load()
    skill_registry.load()
    store = ConversationStore(max_history=40)
    events = [
        ev
        async for ev in harness.run_turn(
            client_id,
            "포아송 작업을 이어서 진행해줘",
            store=store,
            state_store=_MemStateStore(),
            skill_registry=skill_registry,
            prompt_registry=prompt_registry,
            registry=registry,
            agent_registry=agent_registry,
            provider=provider,
            max_iterations=max_iterations,
            max_agent_calls=max_agent_calls,
        )
    ]
    return events, store


async def test_wind_down_injected_when_iterations_run_low() -> None:
    """반복 상한이 빡빡한 쪽 — 남은 2회 시점(4번째 호출)에 지시가 주입된다."""
    provider = _PlanningProvider()
    events, _ = await _run_turn(
        "wind-down-iter", provider, max_iterations=5, max_agent_calls=20
    )

    assert provider.wind_down_seen_at, "wind-down 메시지가 주입되지 않음"
    assert provider.wind_down_seen_at[0] == 4
    # 지시를 따라 텍스트로 종료 → fallback/budget ErrorEvent 없음.
    assert not [e for e in events if isinstance(e, ErrorEvent)]


async def test_wind_down_triggered_by_turn_budget() -> None:
    """반복 상한은 넉넉해도 turn budget 이 먼저 임계에 닿으면 발화한다."""
    provider = _PlanningProvider()
    events, _ = await _run_turn(
        "wind-down-budget", provider, max_iterations=10, max_agent_calls=3
    )

    assert provider.wind_down_seen_at and provider.wind_down_seen_at[0] == 2
    assert not [e for e in events if isinstance(e, ErrorEvent)]


async def test_wind_down_not_persisted_to_history() -> None:
    """wind-down 지시문은 turn-local — 히스토리에 남지 않는다 (fallback 메시지와 동일 정책)."""
    provider = _PlanningProvider()
    _, store = await _run_turn(
        "wind-down-history", provider, max_iterations=5, max_agent_calls=20
    )

    history = store.get_history("wind-down-history")
    assert all(_WIND_DOWN_TOKEN not in (m.content or "") for m in history)
    # 마무리 텍스트 응답 자체는 정상 영속된다.
    assert any(
        m.role == "assistant" and "마무리 요약" in (m.content or "") for m in history
    )


async def test_no_wind_down_when_budget_ample() -> None:
    """예산이 충분히 남은 짧은 턴에는 wind-down 이 발화하지 않는다."""
    provider = _ShortTaskProvider()
    events, _ = await _run_turn(
        "wind-down-ample", provider, max_iterations=8, max_agent_calls=20
    )

    assert provider.saw_wind_down is False
    assert provider.call_count == 2
    assert not [e for e in events if isinstance(e, ErrorEvent)]
