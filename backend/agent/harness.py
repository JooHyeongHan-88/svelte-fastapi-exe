"""Agent harness — provider 와 도구 사이의 turn 실행 루프 (계층형 멀티 에이전트 버전).

run_turn 한 번 = 사용자 입력 1건에 대한 응답 1턴.

흐름:
    1. state_store 에서 AgentState (todo/missing_slots) 를 로드.
    2. PromptRegistry(base+safety+orchestrator) + SkillRegistry.select() 결과 + AGENTS 카탈로그
       + state 요약을 합쳐 오케스트레이터 system prompt 를 동적 조립.
    3. _run_agent_turn (공통 provider→tool 루프) 을 depth=0 으로 호출.
       - delta / tool_call / done 이벤트를 그대로 흘려보냄.
       - tool_call 분기:
           * add_todo / complete_todo → harness 가 직접 AgentState 갱신.
           * call_sub_agent (오케스트레이터 전용) → _dispatch_sub_agent 로 격리 실행.
           * 그 외 도구 → 슬롯 가드 → 통과 시 _execute_tool, 누락 시 AskUserEvent.
    4. 서브 에이전트는 격리된 messages 와 specs(call_sub_agent 제외) 로 자체 turn 을
       수행하고, 모든 raw 이벤트를 AgentProgressEvent 로 래핑해 yield. 마지막 응답에서
       "Task Summary:" 헤더를 추출해 AgentReturnEvent.summary 로 반환.
    5. 턴 종료 시 store.append + state_store.set + DoneEvent.

불변 계약:
    - provider.astream 의 delta/tool_call/done 이벤트 흐름
    - AsyncIterator[StreamEvent] 시그니처
    - 마지막에 DoneEvent yield, 예외는 ErrorEvent 로 변환
    - 서브 에이전트의 상세 메시지는 ConversationStore 에 영속화하지 않음 (컨텍스트 격리)
"""

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, ClassVar

from agent.config import MAX_AGENT_DEPTH
from agent.guard import check_required_slots
from agent.models import (
    AgentProgressEvent,
    AgentReturnEvent,
    AgentState,
    AgentSwitchEvent,
    AskUserEvent,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    Message,
    ReasoningEvent,
    SkillActiveEvent,
    StreamEvent,
    TodoItem,
    TodoStatus,
    TodoUpdateEvent,
    ToolCall,
    ToolCallEvent,
    ToolResultEvent,
    ToolSpec,
)
from agent.registries.agents import Agent, AgentRegistry
from agent.registries.prompts import PromptRegistry
from agent.registries.skills import Skill, SkillRegistry
from agent.registries.tools import (
    PLANNER_ADD_TODO,
    PLANNER_COMPLETE_TODO,
    SUB_AGENT_DISPATCH,
    ToolRegistry,
)
from agent.stores.agent_state import AgentStateStore
from agent.stores.conversation import ConversationStore

logger = logging.getLogger(__name__)

ORCHESTRATOR_ID = "orchestrator"
TASK_SUMMARY_HEADER = "Task Summary:"


# ---------------------------------------------------------------------------
# TurnBudget — 한 사용자 턴 단위 provider 호출 상한 + 연속 호출 가드
# ---------------------------------------------------------------------------


@dataclass
class TurnBudget:
    """한 사용자 turn 에서 허용하는 provider 호출 총량.

    오케스트레이터 + 모든 (재귀) 서브 에이전트 호출 합산. 상한 도달 시 ErrorEvent
    로 안전 종료. 같은 서브 에이전트 연속 호출 가드도 함께 관리한다.
    """

    max_calls: int
    used: int = 0
    last_dispatched_agent: str | None = None
    consecutive_count: int = 0

    MAX_CONSECUTIVE_SAME_AGENT: ClassVar[int] = 3

    def try_consume(self) -> bool:
        """provider 호출 1회 소비. False 면 상한 도달."""
        if self.used >= self.max_calls:
            return False
        self.used += 1
        return True

    def check_dispatch(self, agent_name: str) -> str | None:
        """같은 에이전트 연속 호출 가드. 차단 시 사유 문자열, 통과 시 None."""
        if agent_name == self.last_dispatched_agent:
            self.consecutive_count += 1
            if self.consecutive_count > self.MAX_CONSECUTIVE_SAME_AGENT:
                return (
                    f"[loop-guard] '{agent_name}' 가 "
                    f"{self.MAX_CONSECUTIVE_SAME_AGENT}회 연속 호출되어 차단됨"
                )
        else:
            self.last_dispatched_agent = agent_name
            self.consecutive_count = 1
        return None


# ---------------------------------------------------------------------------
# 진입점 — run_turn (오케스트레이터)
# ---------------------------------------------------------------------------


async def run_turn(
    client_id: str,
    user_message: str,
    *,
    store: ConversationStore,
    state_store: AgentStateStore,
    skill_registry: SkillRegistry,
    prompt_registry: PromptRegistry,
    registry: ToolRegistry,
    provider,
    system_prompt_fallback: str,
    max_iterations: int,
    agent_registry: AgentRegistry | None = None,
    max_agent_calls: int = 10,
    force_skills: list[str] | None = None,
) -> AsyncIterator[StreamEvent]:
    """사용자 메시지 1건에 대한 응답 이벤트 스트림을 생성한다.

    Args:
        client_id: 세션 식별자 — store / state_store 키.
        user_message: 사용자 입력 본문.
        store: 대화 히스토리 인메모리 저장소.
        state_store: 디스크 영속 AgentState 저장소.
        skill_registry: SKILLS/*.md 트리거 라우터.
        prompt_registry: PROMPTS/*.md 베이스 합성기.
        registry: ToolRegistry — provider 노출 + 실행.
        provider: astream(messages, tools) 를 구현한 LLM 어댑터.
        system_prompt_fallback: PROMPTS/ 비어 있을 때 사용할 폴백 텍스트.
        max_iterations: 한 에이전트 turn 내 provider→tool→provider 반복 상한.
        agent_registry: AGENTS/*.md 카탈로그. None 이거나 비어 있으면 단층 동작
            (기존 SKILLS 직접 라우팅) — 하위호환.
        max_agent_calls: 한 사용자 turn 전체에서 허용하는 provider 호출 합계.
        force_skills: 슬래시 커맨드로 명시된 skill 이름들. 지정 시 trigger 매칭
            대신 이 목록을 그대로 활성화한다.

    Yields:
        StreamEvent: delta / tool_call / tool_result / ask_user / todo_update
            / skill_active / reasoning / agent:switch / agent:progress
            / agent:return / done / error.
    """
    history = store.get_history(client_id)
    state = state_store.get(client_id)
    user_msg = Message(role="user", content=user_message)
    turn_messages: list[Message] = [user_msg]

    try:
        if force_skills:
            skills = skill_registry.get_by_names(force_skills)
        else:
            skills = skill_registry.select(
                user_message, available_tools=registry.names()
            )
        state.active_skills = [s.meta.name for s in skills]

        has_agents = agent_registry is not None and len(agent_registry.list_meta()) > 0

        if has_agents:
            composed_system = _compose_orchestrator_system_prompt(
                base=prompt_registry.compose(
                    fallback=system_prompt_fallback, include_orchestrator=True
                ),
                skills=skills,
                state=state,
                agent_registry=agent_registry,
            )
        else:
            # 하위호환 — AGENTS 가 없으면 orchestrator.md 제외하고 단층 동작.
            composed_system = _compose_system_prompt(
                prompt_registry.compose(
                    fallback=system_prompt_fallback, include_orchestrator=False
                ),
                skills,
                state,
            )

        messages: list[Message] = [
            Message(role="system", content=composed_system),
            *history,
            user_msg,
        ]

        if skills:
            yield SkillActiveEvent(skills=[s.meta.name for s in skills])

        if state.todo_list:
            yield TodoUpdateEvent(todos=list(state.todo_list))

        # 오케스트레이터는 전체 도구 노출. (AGENTS 없으면 call_sub_agent 도 제거.)
        orchestrator_specs = (
            registry.specs()
            if has_agents
            else [s for s in registry.specs() if s.name != SUB_AGENT_DISPATCH]
        )

        budget = TurnBudget(max_calls=max_agent_calls)

        async for ev in _run_agent_turn(
            agent_id=ORCHESTRATOR_ID,
            messages=messages,
            turn_messages=turn_messages,
            provider=provider,
            registry=registry,
            sub_specs=orchestrator_specs,
            agent_registry=agent_registry,
            prompt_registry=prompt_registry,
            skill_registry=skill_registry,
            budget=budget,
            depth=0,
            state=state,
            max_iterations=max_iterations,
        ):
            yield ev

        store.append(client_id, *turn_messages)
        state_store.set(client_id, state)
        yield DoneEvent()

    except Exception as exc:  # noqa: BLE001 — 사용자에게 에러 이벤트로 변환해 전달
        logger.exception("harness run_turn failed")
        yield ErrorEvent(message=str(exc))


# ---------------------------------------------------------------------------
# 공통 turn 루프 — 오케스트레이터 / 서브 에이전트 공용
# ---------------------------------------------------------------------------


async def _run_agent_turn(
    *,
    agent_id: str,
    messages: list[Message],
    turn_messages: list[Message] | None,
    provider,
    registry: ToolRegistry,
    sub_specs: list[ToolSpec],
    agent_registry: AgentRegistry | None,
    prompt_registry: PromptRegistry,
    skill_registry: SkillRegistry,
    budget: TurnBudget,
    depth: int,
    state: AgentState | None,
    max_iterations: int,
) -> AsyncIterator[StreamEvent]:
    """provider→tool 반복 루프 (agent_id 무관 공통).

    Args:
        agent_id: 'orchestrator' 또는 서브 에이전트 이름. 로깅·이벤트 라벨용.
        messages: in-place 누적되는 LLM 컨텍스트 (호출자 소유).
        turn_messages: 영속화 대상 메시지 누적 버퍼. 서브 에이전트는 None (격리).
        provider: LLM 어댑터.
        registry: ToolRegistry (도구 실행자).
        sub_specs: provider 에게 노출할 도구 스펙 (서브는 call_sub_agent 제외).
        agent_registry: 서브 디스패치용. None 이면 call_sub_agent 분기 비활성.
        prompt_registry: 서브 에이전트 system prompt 합성용.
        skill_registry: 서브 에이전트 SKILL 본문 lazy load 용.
        budget: 한 사용자 turn 단위 호출 카운터.
        depth: 0=orchestrator, 1=sub-agent, 2+ 차단 (MAX_AGENT_DEPTH).
        state: planner 도구 활성 여부. 서브 에이전트는 None (PLANNER 도구 미사용).
        max_iterations: 이 turn 내 provider→tool 반복 상한.

    Yields:
        StreamEvent: delta / tool_call / tool_result / reasoning / ask_user
            / todo_update / agent:switch / agent:progress / agent:return / error.
    """
    assistant_buffer: list[str] = []
    pending_tool_calls: list[ToolCall] = []

    for iteration in range(max_iterations):
        del iteration

        if not budget.try_consume():
            yield ErrorEvent(
                message=f"[budget] {agent_id}: provider 호출 상한({budget.max_calls}) 초과"
            )
            return

        assistant_buffer.clear()
        pending_tool_calls.clear()

        async for event in provider.astream(messages, sub_specs):
            if event.type == "delta":
                assistant_buffer.append(event.content)
                yield event
                continue

            if event.type == "tool_call":
                pending_tool_calls.append(event.call)
                yield event
                continue

            if event.type == "reasoning":
                yield event
                continue

            if event.type == "done":
                break

            yield event
            return

        assistant_text = "".join(assistant_buffer)

        if not pending_tool_calls:
            if assistant_text and turn_messages is not None:
                turn_messages.append(Message(role="assistant", content=assistant_text))
            return

        assistant_msg = Message(
            role="assistant",
            content=assistant_text,
            tool_calls=list(pending_tool_calls),
        )
        messages.append(assistant_msg)
        if turn_messages is not None:
            turn_messages.append(assistant_msg)

        interrupted = False
        for call in pending_tool_calls:
            # PLANNER 도구는 state 가 있을 때만 (서브 에이전트는 state=None).
            if call.name == PLANNER_ADD_TODO and state is not None:
                result_text = _handle_add_todo(state, call.arguments)
                _append_tool_result(messages, turn_messages, call, result_text)
                yield ToolResultEvent(
                    tool_call_id=call.id, name=call.name, result=result_text
                )
                yield TodoUpdateEvent(todos=list(state.todo_list))
                continue

            if call.name == PLANNER_COMPLETE_TODO and state is not None:
                result_text = _handle_complete_todo(state, call.arguments)
                _append_tool_result(messages, turn_messages, call, result_text)
                yield ToolResultEvent(
                    tool_call_id=call.id, name=call.name, result=result_text
                )
                yield TodoUpdateEvent(todos=list(state.todo_list))
                continue

            # 서브 에이전트 디스패치 — async generator nesting 으로 통과.
            if call.name == SUB_AGENT_DISPATCH and agent_registry is not None:
                guard = check_required_slots(call.arguments, registry.get(call.name))
                if not guard.ok:
                    first = guard.missing[0]
                    if state is not None:
                        state.missing_slots = {m.key: m.question for m in guard.missing}
                        state.pending_tool = call.name
                        state.pending_args = dict(call.arguments)
                    _append_tool_result(
                        messages,
                        turn_messages,
                        call,
                        f"[guard] missing required slots: {[m.key for m in guard.missing]}",
                    )
                    yield AskUserEvent(
                        question=first.question,
                        slot_key=first.key,
                        options=first.options,
                        tool_name=call.name,
                    )
                    interrupted = True
                    break

                captured_summary = (
                    f"[error] {call.arguments.get('agent_name', '?')}: "
                    "sub-agent 가 요약을 반환하지 않음"
                )
                async for sub_ev in _dispatch_sub_agent(
                    call=call,
                    parent_agent_id=agent_id,
                    agent_registry=agent_registry,
                    skill_registry=skill_registry,
                    prompt_registry=prompt_registry,
                    registry=registry,
                    provider=provider,
                    budget=budget,
                    depth=depth + 1,
                    max_iterations=max_iterations,
                ):
                    yield sub_ev
                    if isinstance(sub_ev, AgentReturnEvent):
                        captured_summary = sub_ev.summary

                _append_tool_result(messages, turn_messages, call, captured_summary)
                yield ToolResultEvent(
                    tool_call_id=call.id, name=call.name, result=captured_summary
                )
                continue

            tool = registry.get(call.name)
            guard = check_required_slots(call.arguments, tool)
            if not guard.ok:
                first = guard.missing[0]
                if state is not None:
                    state.missing_slots = {m.key: m.question for m in guard.missing}
                    state.pending_tool = call.name
                    state.pending_args = dict(call.arguments)
                _append_tool_result(
                    messages,
                    turn_messages,
                    call,
                    f"[guard] missing required slots: {[m.key for m in guard.missing]}",
                )
                yield AskUserEvent(
                    question=first.question,
                    slot_key=first.key,
                    options=first.options,
                    tool_name=call.name,
                )
                interrupted = True
                break

            result_text = await _execute_tool(call, registry)
            _append_tool_result(messages, turn_messages, call, result_text)
            yield ToolResultEvent(
                tool_call_id=call.id, name=call.name, result=result_text
            )

            if state is not None:
                _mark_running_todo_done(state, call.name, result_text)
                if state.pending_tool == call.name:
                    state.pending_tool = None
                    state.pending_args = {}
                    state.missing_slots = {}

        if interrupted:
            return
    else:
        logger.warning(
            "agent harness reached max_iterations=%d (agent=%s)",
            max_iterations,
            agent_id,
        )


# ---------------------------------------------------------------------------
# 서브 에이전트 디스패치
# ---------------------------------------------------------------------------


async def _dispatch_sub_agent(
    *,
    call: ToolCall,
    parent_agent_id: str,
    agent_registry: AgentRegistry,
    skill_registry: SkillRegistry,
    prompt_registry: PromptRegistry,
    registry: ToolRegistry,
    provider,
    budget: TurnBudget,
    depth: int,
    max_iterations: int,
) -> AsyncIterator[StreamEvent]:
    """서브 에이전트 turn 을 격리된 컨텍스트에서 실행.

    AgentSwitch → AgentProgress×N → AgentReturn 순으로 yield. 부모 _run_agent_turn
    이 AgentReturnEvent.summary 를 캡처해 tool_result 로 변환한다.
    """
    agent_name = (call.arguments or {}).get("agent_name", "")
    task = (call.arguments or {}).get("task", "")

    # 깊이 가드 (J-1): 서브 에이전트가 또 위임을 시도하는 경우 차단.
    if depth > MAX_AGENT_DEPTH:
        yield AgentReturnEvent(
            from_agent=agent_name or "?",
            summary=f"[depth-guard] depth={depth} 초과로 위임 거부",
        )
        return

    block_reason = budget.check_dispatch(agent_name)
    if block_reason:
        yield AgentReturnEvent(from_agent=agent_name, summary=block_reason)
        return

    agent = agent_registry.get_by_name(agent_name)
    if agent is None:
        yield AgentReturnEvent(
            from_agent=agent_name or "?",
            summary=f"[error] unknown agent: '{agent_name}'",
        )
        return

    yield AgentSwitchEvent(
        from_agent=parent_agent_id,
        to_agent=agent.meta.name,
        reason=task[:80],
    )

    # 격리된 system prompt — base + safety + agent body + 학습 SKILL body.
    sub_system = _compose_sub_agent_system_prompt(
        base=prompt_registry.compose(fallback="", include_orchestrator=False),
        agent=agent_registry._ensure_body(agent),
        skill_bodies=_resolve_agent_skills(agent, skill_registry),
    )
    sub_messages: list[Message] = [
        Message(role="system", content=sub_system),
        Message(role="user", content=task),
    ]
    sub_specs = _filter_specs_for_sub_agent(registry.specs(), agent)

    last_assistant_text: list[str] = []
    async for ev in _run_agent_turn(
        agent_id=agent.meta.name,
        messages=sub_messages,
        turn_messages=None,
        provider=provider,
        registry=registry,
        sub_specs=sub_specs,
        agent_registry=agent_registry,
        prompt_registry=prompt_registry,
        skill_registry=skill_registry,
        budget=budget,
        depth=depth,
        state=None,
        max_iterations=max_iterations,
    ):
        if isinstance(ev, DeltaEvent):
            last_assistant_text.append(ev.content)
            yield AgentProgressEvent(
                agent_id=agent.meta.name,
                inner_type=ev.type,
                inner_payload=ev.model_dump(exclude={"type"}),
            )
            continue

        if isinstance(ev, (ToolCallEvent, ToolResultEvent, ReasoningEvent)):
            yield AgentProgressEvent(
                agent_id=agent.meta.name,
                inner_type=ev.type,
                inner_payload=ev.model_dump(exclude={"type"}),
            )
            continue

        if isinstance(ev, AskUserEvent):
            # J-2: 서브 에이전트 슬롯 가드 발동 — 작업 포기, 요약에 명시.
            yield AgentReturnEvent(
                from_agent=agent.meta.name,
                summary=(
                    f"[interrupted] {agent.meta.name} 가 필수 정보 부족으로 작업을 "
                    f"완료할 수 없음: {ev.question}"
                ),
            )
            return

        if isinstance(ev, ErrorEvent):
            yield AgentReturnEvent(
                from_agent=agent.meta.name,
                summary=f"[error] {agent.meta.name}: {ev.message}",
            )
            return

        # 그 외(SkillActiveEvent / TodoUpdateEvent 등)는 서브에선 발생하지 않으나
        # 안전을 위해 silent drop. (state=None 이므로 도달하지 않음.)

    summary = _extract_task_summary(
        "".join(last_assistant_text).strip(), agent.meta.name
    )
    yield AgentReturnEvent(from_agent=agent.meta.name, summary=summary)


# ---------------------------------------------------------------------------
# 시스템 프롬프트 조립
# ---------------------------------------------------------------------------


def _compose_orchestrator_system_prompt(
    *,
    base: str,
    skills: list[Skill],
    state: AgentState,
    agent_registry: AgentRegistry,
) -> str:
    """오케스트레이터 system prompt — 기존 조립 + 가용 에이전트 카탈로그 동적 주입."""
    parts: list[str] = [base] if base else []

    for s in skills:
        parts.append(f"\n# Skill: {s.meta.name}\n{s.body}")

    if len(skills) > 1:
        skill_names = ", ".join(f"`{s.meta.name}`" for s in skills)
        parts.append(
            f"\n# 멀티 스킬 실행 지침\n"
            f"현재 {len(skills)}개 스킬이 동시에 활성화되었습니다: {skill_names}.\n"
            f"실제 작업을 시작하기 전에 반드시 `add_todo` 로 각 스킬의 실행 순서와 "
            f"단계를 먼저 등록하세요. 한 스킬의 작업이 완료될 때마다 즉시 "
            f"`complete_todo` 로 표시한 뒤 다음 스킬 작업으로 넘어가세요."
        )

    if state.todo_list:
        rendered = "\n".join(
            f"- [{t.status.value}] ({t.task_id}) {t.description}"
            for t in state.todo_list
        )
        parts.append(f"\n# 현재 To-do\n{rendered}")

    if state.pending_tool and state.missing_slots:
        first_q = next(iter(state.missing_slots.values()))
        parts.append(
            "\n# Pending Slot\n"
            f"당신은 직전 턴에 도구 `{state.pending_tool}` 호출을 위해 "
            f"사용자에게 다음을 물었고 응답을 기다리는 중입니다: '{first_q}'.\n"
            f"부분적으로 채워진 인자: {state.pending_args}.\n"
            "사용자의 이번 메시지가 그 질문에 대한 응답이면 같은 도구를 채워서 다시 호출하세요. "
            "새 주제로 전환된 메시지라면 이 pending 호출을 폐기하고 새 요청을 처리하세요."
        )

    metas = agent_registry.list_meta()
    if metas:
        catalog_lines: list[str] = ["\n# 가용 서브 에이전트 카탈로그"]
        skill_to_agent: dict[str, str] = {}
        for m in metas:
            skills_str = ", ".join(m.skills) if m.skills else "(없음)"
            catalog_lines.append(
                f"- **{m.name}**: {m.description}\n  전담 스킬: {skills_str}"
            )
            for sk in m.skills:
                skill_to_agent.setdefault(sk, m.name)

        if skill_to_agent:
            mapping_lines = [
                f"- '{sk}' 트리거가 들어오면 반드시 `{ag}` 에게 `call_sub_agent` 로 위임"
                for sk, ag in skill_to_agent.items()
            ]
            catalog_lines.append(
                "\n## Case 3 결정론 매핑 (반드시 준수)\n" + "\n".join(mapping_lines)
            )
        parts.append("\n".join(catalog_lines))

    return "\n".join(parts)


def _compose_sub_agent_system_prompt(
    *,
    base: str,
    agent: Agent,
    skill_bodies: list[Skill],
) -> str:
    """서브 에이전트 system prompt — 격리된 컨텍스트로 페르소나·스킬 본문 주입.

    구성: safety+base (orchestrator.md 제외) + 에이전트 본문 + 학습 SKILL 본문
    + Task Summary 종료 규약. 'call_sub_agent' 도구는 spec 에서 제거되므로
    LLM 시야에 보이지 않는다 (무한 재귀 방지).
    """
    parts: list[str] = [base] if base else []
    parts.append(f"\n# 당신은 '{agent.meta.name}' 서브 에이전트입니다\n{agent.body}")
    for s in skill_bodies:
        parts.append(f"\n# 학습 Skill: {s.meta.name}\n{s.body}")
    parts.append(
        "\n# 종료 규약 (필수)\n"
        "작업을 마무리할 때 응답의 마지막 단락은 반드시 다음 형식이어야 한다:\n"
        "```\n"
        "Task Summary:\n"
        "- 수행한 작업 요약 1~3줄\n"
        "- 발견한 핵심 사실 또는 다음 단계 제안\n"
        "```\n"
        "이 헤더가 없으면 오케스트레이터가 결과를 인식하지 못한다."
    )
    return "\n".join(parts)


def _resolve_agent_skills(agent: Agent, skill_registry: SkillRegistry) -> list[Skill]:
    """agent.meta.skills 의 이름들을 SkillRegistry 에서 lazy load. 미존재는 무시."""
    if not agent.meta.skills:
        return []
    return skill_registry.get_by_names(agent.meta.skills)


def _filter_specs_for_sub_agent(
    all_specs: list[ToolSpec], agent: Agent
) -> list[ToolSpec]:
    """서브 에이전트에게 노출할 도구 스펙.

    금지 도구:
        - SUB_AGENT_DISPATCH: 무한 재귀 방지 (depth-guard 가 2차 안전망).
        - PLANNER_ADD_TODO / PLANNER_COMPLETE_TODO: state=None 이라 의미 없음.
    화이트리스트:
        - agent.meta.tools 비어 있으면 위 금지 외 전체.
        - 비어있지 않으면 그 화이트리스트만 (단 금지 도구는 항상 제외).
    """
    forbidden: frozenset[str] = frozenset(
        {SUB_AGENT_DISPATCH, PLANNER_ADD_TODO, PLANNER_COMPLETE_TODO}
    )
    allowed = set(agent.meta.tools)
    out: list[ToolSpec] = []
    for spec in all_specs:
        if spec.name in forbidden:
            continue
        if allowed and spec.name not in allowed:
            continue
        out.append(spec)
    return out


def _extract_task_summary(full_text: str, agent_name: str) -> str:
    """서브 에이전트 응답에서 'Task Summary:' 헤더 이후 텍스트 추출.

    헤더가 없으면 마지막 200자를 폴백 요약으로 사용 — LLM 미준수 방어.
    """
    if not full_text:
        return f"[{agent_name}] (빈 응답)"
    if TASK_SUMMARY_HEADER in full_text:
        return full_text.split(TASK_SUMMARY_HEADER, 1)[1].strip() or f"[{agent_name}]"
    return f"[{agent_name}] {full_text[-200:].strip()}"


# ---------------------------------------------------------------------------
# 단층 fallback (하위호환) — AGENTS 가 없을 때
# ---------------------------------------------------------------------------


def _compose_system_prompt(
    base: str,
    skills: list[Skill],
    state: AgentState,
) -> str:
    """PROMPTS 베이스 + 선택된 SKILLS 본문 + AgentState 요약을 합성한다 (단층).

    오케스트레이터 카탈로그 / Case 3 매핑 없이 기존 동작 그대로. agent_registry 가
    None 일 때만 사용 — 하위호환을 위해 보존.
    """
    parts: list[str] = [base] if base else []

    for s in skills:
        parts.append(f"\n# Skill: {s.meta.name}\n{s.body}")

    if len(skills) > 1:
        skill_names = ", ".join(f"`{s.meta.name}`" for s in skills)
        parts.append(
            f"\n# 멀티 스킬 실행 지침\n"
            f"현재 {len(skills)}개 스킬이 동시에 활성화되었습니다: {skill_names}.\n"
            f"실제 작업을 시작하기 전에 반드시 `add_todo` 로 각 스킬의 실행 순서와 단계를 먼저 등록하세요. "
            f"한 스킬의 작업이 완료될 때마다 즉시 `complete_todo` 로 표시한 뒤 다음 스킬 작업으로 넘어가세요."
        )

    if state.todo_list:
        rendered = "\n".join(
            f"- [{t.status.value}] ({t.task_id}) {t.description}"
            for t in state.todo_list
        )
        parts.append(f"\n# 현재 To-do\n{rendered}")

    if state.pending_tool and state.missing_slots:
        first_q = next(iter(state.missing_slots.values()))
        parts.append(
            "\n# Pending Slot\n"
            f"당신은 직전 턴에 도구 `{state.pending_tool}` 호출을 위해 "
            f"사용자에게 다음을 물었고 응답을 기다리는 중입니다: '{first_q}'.\n"
            f"부분적으로 채워진 인자: {state.pending_args}.\n"
            "사용자의 이번 메시지가 그 질문에 대한 응답이면 같은 도구를 채워서 다시 호출하세요. "
            "새 주제로 전환된 메시지라면 이 pending 호출을 폐기하고 새 요청을 처리하세요."
        )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Planner 도구 핸들러 — harness 가 직접 AgentState 를 갱신
# ---------------------------------------------------------------------------


def _handle_add_todo(state: AgentState, args: dict[str, Any]) -> str:
    """add_todo 호출을 받아 state.todo_list 에 TodoItem 들을 누적한다."""
    items = args.get("items") or []
    if not isinstance(items, list) or not items:
        return "[planner] add_todo: items 가 비어 있습니다"

    added: list[str] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        description = (raw.get("description") or "").strip()
        if not description:
            continue
        task_id = uuid.uuid4().hex[:8]
        state.todo_list.append(
            TodoItem(
                task_id=task_id,
                description=description,
                tool_name=raw.get("tool_name") or None,
                status=TodoStatus.PENDING,
            )
        )
        added.append(task_id)

    if not added:
        return "[planner] add_todo: 유효한 description 이 없습니다"

    skipped = len(items) - len(added)
    msg = f"[planner] added {len(added)} todo(s): {added}"
    if skipped > 0:
        msg += f" (skipped {skipped} invalid item(s))"
    return msg


def _handle_complete_todo(state: AgentState, args: dict[str, Any]) -> str:
    """complete_todo 호출을 받아 task_id 매칭 todo 의 status 를 COMPLETED 로 갱신."""
    task_id = (args.get("task_id") or "").strip()
    summary = (args.get("summary") or "").strip() or None

    if not task_id:
        return "[planner] complete_todo: task_id 누락"

    for item in state.todo_list:
        if item.task_id == task_id:
            item.status = TodoStatus.COMPLETED
            item.result_summary = summary
            return f"[planner] completed: {task_id}"

    return f"[planner] complete_todo: task_id '{task_id}' 를 찾을 수 없음"


def _mark_running_todo_done(
    state: AgentState, tool_name: str, result_text: str
) -> None:
    """일반 도구가 실행되면 같은 tool_name 으로 마킹된 RUNNING todo 를 자동 완료한다."""
    for item in state.todo_list:
        if item.status == TodoStatus.RUNNING and item.tool_name == tool_name:
            item.status = TodoStatus.COMPLETED
            item.result_summary = result_text[:120]
            return


# ---------------------------------------------------------------------------
# 메시지 누적 / 도구 실행 헬퍼
# ---------------------------------------------------------------------------


def _append_tool_result(
    messages: list[Message],
    turn_messages: list[Message] | None,
    call: ToolCall,
    result_text: str,
) -> None:
    """LLM 컨텍스트와 영구 히스토리 양쪽에 tool 응답을 동일하게 누적한다.

    서브 에이전트 호출 시 turn_messages=None — 격리 보장.
    """
    tool_msg = Message(
        role="tool",
        content=result_text,
        tool_call_id=call.id,
    )
    messages.append(tool_msg)
    if turn_messages is not None:
        turn_messages.append(tool_msg)


async def _execute_tool(call: ToolCall, registry: ToolRegistry) -> str:
    tool = registry.get(call.name)
    if tool is None:
        return f"[error] unknown tool: {call.name}"

    try:
        return await tool.run(call.arguments)
    except (ValueError, KeyError, TypeError) as exc:
        return f"[error] {type(exc).__name__}: {exc}"


__all__ = ["run_turn", "TurnBudget", "ORCHESTRATOR_ID"]
