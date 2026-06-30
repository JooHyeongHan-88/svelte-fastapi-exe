"""summarize-then-drop 롤링 압축 + objective 캡처 + `# 이전 진행 요약` 섹션 검증.

슬라이딩 윈도우(MAX_HISTORY)가 메시지를 버릴 때 그 내용을 LLM 으로 요약해
state.progress_summary 에 접어 망각을 방지한다. 첫 턴 user_message 는 state.objective
로 1회 박제되고, 둘은 다음 턴부터 `# 이전 진행 요약` 섹션으로 재주입된다.
"""

from __future__ import annotations

from agent import harness
from agent.harness.loop import _COMPACTION_SYSTEM_PROMPT
from agent.models import AgentState, DeltaEvent, DoneEvent
from agent.registries.agents import registry as agent_registry
from agent.registries.prompts import registry as prompt_registry
from agent.registries.skills import registry as skill_registry
from agent.registries.tools import registry
from agent.stores.conversation import ConversationStore

_FIXED_SUMMARY = "원래 목표와 중간 결정(지역 X 제외)을 보존한 압축 요약."


class _MemStateStore:
    def __init__(self) -> None:
        self.states: dict[str, AgentState] = {}

    def get(self, client_id: str) -> AgentState:
        return self.states.setdefault(client_id, AgentState())

    def set(self, client_id: str, state: AgentState) -> None:
        self.states[client_id] = state

    def reset(self, client_id: str) -> None:
        self.states.pop(client_id, None)


class _CompactingProvider:
    """압축 system prompt 를 보면 고정 요약을 반환, 그 외엔 평범한 텍스트로 종료하는 가짜 LLM."""

    def __init__(self) -> None:
        self.compaction_calls = 0
        self.last_main_system_prompt: str | None = None

    async def astream(self, messages, tools):  # noqa: ANN001, ARG002
        system = messages[0].content if messages else ""
        if system == _COMPACTION_SYSTEM_PROMPT:
            self.compaction_calls += 1
            yield DeltaEvent(content=_FIXED_SUMMARY)
            yield DoneEvent()
            return
        self.last_main_system_prompt = system
        yield DeltaEvent(content="네, 진행하겠습니다.")
        yield DoneEvent()


async def _drive(store, state_store, provider, client_id: str, msg: str) -> None:
    async for _ in harness.run_turn(
        client_id,
        msg,
        store=store,
        state_store=state_store,
        skill_registry=skill_registry,
        prompt_registry=prompt_registry,
        registry=registry,
        agent_registry=agent_registry,
        provider=provider,
        max_iterations=4,
        max_agent_calls=10,
    ):
        pass


async def test_objective_captured_on_first_turn_only() -> None:
    agent_registry.load()
    skill_registry.load()
    store = ConversationStore(max_history=2)
    state_store = _MemStateStore()
    provider = _CompactingProvider()
    cid = "obj-1"

    await _drive(store, state_store, provider, cid, "지역별 매출 분석을 시작하자")
    state = state_store.get(cid)
    assert state.objective == "지역별 매출 분석을 시작하자"
    assert state.progress_summary is None  # 아직 드롭 없음 → 압축 미발생
    assert provider.compaction_calls == 0

    # 두 번째 턴 메시지는 objective 를 덮어쓰지 않는다(1회 박제).
    await _drive(store, state_store, provider, cid, "다른 메시지")
    assert state_store.get(cid).objective == "지역별 매출 분석을 시작하자"


async def test_compaction_populates_progress_summary() -> None:
    agent_registry.load()
    skill_registry.load()
    store = ConversationStore(max_history=2)  # 턴당 2메시지 → 2턴째부터 오버플로
    state_store = _MemStateStore()
    provider = _CompactingProvider()
    cid = "compact-1"

    await _drive(store, state_store, provider, cid, "지역별 매출 분석을 시작하자")
    await _drive(store, state_store, provider, cid, "이어서 진행")  # 오버플로 → 압축

    assert provider.compaction_calls >= 1
    assert state_store.get(cid).progress_summary == _FIXED_SUMMARY


async def test_progress_section_injected_next_turn() -> None:
    agent_registry.load()
    skill_registry.load()
    store = ConversationStore(max_history=2)
    state_store = _MemStateStore()
    provider = _CompactingProvider()
    cid = "section-1"

    await _drive(store, state_store, provider, cid, "지역별 매출 분석을 시작하자")
    await _drive(store, state_store, provider, cid, "이어서 진행")  # 압축 발생
    await _drive(store, state_store, provider, cid, "세 번째 질문")  # 섹션 재주입

    prompt = provider.last_main_system_prompt or ""
    assert "# 이전 진행 요약" in prompt
    assert "원래 목표: 지역별 매출 분석을 시작하자" in prompt
    assert _FIXED_SUMMARY in prompt
