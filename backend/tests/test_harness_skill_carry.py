"""pending 동안 SKILL 본문 캐리 — ask_user 턴 경계에서 지침이 증발하지 않게 한다.

SKILL 은 stateless 트리거 라우터라 매 턴 user_message 로 재매칭된다. ask_user 답변
턴의 메시지("2024-01-01" 등)엔 트리거가 없어 select()=[] → 직전 SKILL 본문이 소실되던
빈틈을 메운다. pending 이 살아있는 동안에만 state.active_skills 본문을 다시 들고 가고,
pending 이 없으면(=작업 종료) 캐리하지 않아 영구 sticky 가 되지 않는다.
"""

from __future__ import annotations

from agent import harness
from agent.harness.state.pending import has_pending
from agent.models import AgentState, DeltaEvent, DoneEvent
from agent.registries.agents import registry as agent_registry
from agent.registries.prompts import registry as prompt_registry
from agent.registries.skills import registry as skill_registry
from agent.registries.tools import registry
from agent.stores.conversation import ConversationStore

# 트리거에 걸리지 않는 중립 메시지 — ask_user 답변을 흉내낸다.
_NEUTRAL_ANSWER = "2024-01-01"
_CARRIED_SKILL = "data_summary"


class _SeededStateStore:
    """미리 채운 AgentState 를 돌려주는 인메모리 state store."""

    def __init__(self, state: AgentState) -> None:
        self._state = state

    def get(self, client_id: str) -> AgentState:  # noqa: ARG002
        return self._state

    def set(self, client_id: str, state: AgentState) -> None:  # noqa: ARG002
        self._state = state

    def reset(self, client_id: str) -> None:  # noqa: ARG002
        self._state = AgentState()


class _CapturingProvider:
    """첫 호출의 system prompt(messages[0])를 붙잡고 텍스트로 즉시 종료하는 가짜 LLM."""

    def __init__(self) -> None:
        self.system_prompt: str | None = None

    async def astream(self, messages, tools):  # noqa: ANN001, ARG002
        if self.system_prompt is None:
            self.system_prompt = messages[0].content if messages else ""
        yield DeltaEvent(content="알겠습니다.")
        yield DoneEvent()


async def _capture_system_prompt(client_id: str, state: AgentState) -> str:
    agent_registry.load()
    skill_registry.load()
    provider = _CapturingProvider()
    async for _ in harness.run_turn(
        client_id,
        _NEUTRAL_ANSWER,
        store=ConversationStore(max_history=40),
        state_store=_SeededStateStore(state),
        skill_registry=skill_registry,
        prompt_registry=prompt_registry,
        registry=registry,
        agent_registry=agent_registry,
        provider=provider,
        max_iterations=4,
        max_agent_calls=10,
    ):
        pass
    return provider.system_prompt or ""


def test_has_pending_detects_each_field() -> None:
    assert not has_pending(AgentState())
    assert has_pending(AgentState(pending_tool="fetch"))
    assert has_pending(AgentState(missing_slots={"date": "언제?"}))
    assert has_pending(AgentState(pending_question="기간?"))
    assert has_pending(AgentState(pending_sub_agent="sales_agent"))


async def test_skill_carried_while_pending() -> None:
    # 직전 턴 data_summary 가 active 였고 ask_user(pending_question)로 끊겼다고 가정.
    state = AgentState(
        active_skills=[_CARRIED_SKILL],
        pending_question="요약할 기간을 알려주세요",
    )
    prompt = await _capture_system_prompt("carry-on", state)
    assert f"# Skill: {_CARRIED_SKILL}" in prompt


async def test_skill_not_carried_without_pending() -> None:
    # 같은 active_skills 지만 pending 이 없으면(작업 종료) 캐리하지 않는다 — 영구 sticky 방지.
    state = AgentState(active_skills=[_CARRIED_SKILL])
    prompt = await _capture_system_prompt("carry-off", state)
    assert f"# Skill: {_CARRIED_SKILL}" not in prompt
