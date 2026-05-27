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

import asyncio
import logging
import uuid
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, ClassVar

from agent.config import MAX_AGENT_DEPTH
from agent.guard import validate_tool_args
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
    SkillCompleteEvent,
    StreamEvent,
    TodoItem,
    TodoStatus,
    TodoUpdateEvent,
    ToolCall,
    ToolCallEvent,
    ToolResult,
    ToolResultEvent,
    ToolSpec,
)
from agent.registries.agents import Agent, AgentRegistry
from agent.registries.prompts import PromptRegistry
from agent.registries.skills import Skill, SkillRegistry
from agent.registries.tools import (
    ASK_USER,
    COMPLETE_SUB_AGENT,
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

# todo 가 더 이상 진행되지 않는 최종 상태.
_TERMINAL_STATUSES: frozenset[TodoStatus] = frozenset(
    {TodoStatus.COMPLETED, TodoStatus.FAILED, TodoStatus.SKIPPED}
)


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
    max_iterations: int,
    agent_registry: AgentRegistry | None = None,
    max_agent_calls: int = 10,
    force_skills: list[str] | None = None,
    session_title: str = "",
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
    # 세션 컨텍스트를 contextvars 에 저장 — 도구·프로바이더가 산출물 경로 해소 시 참조.
    from core.result_store import set_session_context

    set_session_context(client_id, session_title)

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
                base=prompt_registry.compose(include_orchestrator=True),
                skills=skills,
                state=state,
                agent_registry=agent_registry,
            )
        else:
            # 하위호환 — AGENTS 가 없으면 orchestrator.md 제외하고 단층 동작.
            composed_system = _compose_system_prompt(
                prompt_registry.compose(include_orchestrator=False),
                skills,
                state,
            )

        # pending_question 은 직전 턴 ask_user 의 잔재 — 시스템 프롬프트에 1회 주입됐으면
        # 즉시 클리어해야 같은 질문이 두 턴 연속 컨텍스트에 남지 않는다.
        state.pending_question = None

        messages: list[Message] = [
            Message(role="system", content=composed_system),
            *history,
            user_msg,
        ]

        if skills:
            yield SkillActiveEvent(skills=[s.meta.name for s in skills])

        if state.todo_list:
            yield TodoUpdateEvent(todos=list(state.todo_list))

        # 오케스트레이터: COMPLETE_SUB_AGENT 는 서브 에이전트 전용이라 숨김.
        # AGENTS 없으면 SUB_AGENT_DISPATCH 도 제거.
        orchestrator_specs = [
            s
            for s in registry.specs()
            if s.name != COMPLETE_SUB_AGENT
            and (has_agents or s.name != SUB_AGENT_DISPATCH)
        ]

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
            **서브 에이전트 context 에서는 반드시 None 으로 전달해야 한다.** 중첩
            sub-agent 위임을 완전히 차단하는 L0 방어선. _dispatch_sub_agent 가
            이 계약을 보장한다. (_filter_specs_for_sub_agent 의 L1 + depth guard
            의 L2 + sentinel guard 의 L3 가 추가 안전망으로 존재한다.)
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
    # sub-agent context 에서는 agent_registry 가 None 이어야 한다.
    # turn_messages=None 은 "서브 에이전트로 호출됐다"는 관례적 신호.
    assert turn_messages is not None or agent_registry is None, (
        "_run_agent_turn: sub-agent context(turn_messages=None)에서 "
        "agent_registry 가 None 이 아님 — 중첩 sub-agent dispatch 가 열릴 수 있습니다. "
        "_dispatch_sub_agent 가 agent_registry=None 으로 호출하는지 확인하세요."
    )
    assistant_buffer: list[str] = []
    pending_tool_calls: list[ToolCall] = []
    history_calls: set[tuple[str, str]] = set()

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

            if event.type == "skill_active":
                # provider 가 내부 단계 전환 시점에 직접 emit 하는 경우 (mock 시나리오 등).
                # 루프를 끊지 않고 그대로 흘려보낸다.
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
            # complete_subagent — 서브 에이전트 종료 sentinel (turn_messages=None 이 서브 에이전트 지표).
            if call.name == COMPLETE_SUB_AGENT and turn_messages is None:
                result_text = (call.arguments or {}).get("summary", "")
                _append_tool_result(messages, turn_messages, call, result_text)
                yield ToolResultEvent(
                    tool_call_id=call.id, name=call.name, result=result_text
                )
                return  # 서브 에이전트 완료 — _dispatch_sub_agent 가 ToolResultEvent 를 캡처

            # PLANNER 도구는 state 가 있을 때만 (서브 에이전트도 sub_state 가 주입되므로 동작함).
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
                if _all_todos_terminal(state):
                    yield _build_skill_complete_event(state)
                continue

            # ask_user sentinel — LLM 능동 보완 질문. tool_result placeholder 한 줄 + AskUserEvent 후 turn 중단.
            if call.name == ASK_USER:
                args = call.arguments or {}
                question = (args.get("question") or "").strip()
                options = args.get("options")
                input_type = args.get("input_type", "both")

                # 정규화: options 가 비어 있으면 자유입력만, 비정상 input_type 은 both 로 폴백.
                if not options:
                    options = None
                    input_type = "text"
                elif input_type not in ("choice", "text", "both"):
                    input_type = "both"

                if state is not None:
                    state.pending_question = question

                placeholder = f"[ask_user] 사용자에게 질문을 던졌습니다: {question}"
                _append_tool_result(messages, turn_messages, call, placeholder)
                yield ToolResultEvent(
                    tool_call_id=call.id, name=call.name, result=placeholder
                )
                yield AskUserEvent(
                    question=question,
                    slot_key=ASK_USER,
                    options=options,
                    tool_name=ASK_USER,
                    input_type=input_type,
                )
                interrupted = True
                break

            # 서브 에이전트 디스패치 — async generator nesting 으로 통과.
            if call.name == SUB_AGENT_DISPATCH and agent_registry is not None:
                guard = validate_tool_args(call.arguments, registry.get(call.name))
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
                        input_type="both" if first.options else "text",
                    )
                    interrupted = True
                    break

                captured_summary = (
                    f"[error] {call.arguments.get('agent_name', '?')}: "
                    "sub-agent 가 요약을 반환하지 않음"
                )
                sub_interrupted = False
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
                    orchestrator_state=state,
                ):
                    yield sub_ev
                    if isinstance(sub_ev, AgentReturnEvent):
                        # todo_log 와 통계를 포함한 구조화 텍스트로 LLM 컨텍스트에 주입.
                        captured_summary = _format_sub_agent_result(sub_ev)
                    elif isinstance(sub_ev, AskUserEvent):
                        # 서브 에이전트 슬롯 부족 — 사용자 질문을 그대로 전달 후 중단.
                        sub_interrupted = True

                if sub_interrupted:
                    interrupted = True
                    break

                # 성공적 완료 — pending_sub_agent 초기화
                if state is not None:
                    dispatched_name = (call.arguments or {}).get("agent_name")
                    if state.pending_sub_agent == dispatched_name:
                        state.pending_sub_agent = None
                        state.pending_sub_task = None
                        state.missing_slots = {}

                _append_tool_result(messages, turn_messages, call, captured_summary)
                yield ToolResultEvent(
                    tool_call_id=call.id, name=call.name, result=captured_summary
                )
                continue

            tool = registry.get(call.name)
            guard = validate_tool_args(call.arguments, tool)
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
                    input_type="both" if first.options else "text",
                )
                interrupted = True
                break

            args_str = (
                json.dumps(call.arguments, sort_keys=True) if call.arguments else ""
            )
            call_sig = (call.name, args_str)
            if call_sig in history_calls:
                result_content = "[System] 동일한 인자로 이 도구를 연속해서 호출했습니다. 루프가 감지되었습니다. 이전 실행 결과를 바탕으로 원인을 분석(Root Cause Analysis)하고 완전히 다른 접근 방식을 시도하세요."
                _append_tool_result(messages, turn_messages, call, result_content)
                yield ToolResultEvent(
                    tool_call_id=call.id,
                    name=call.name,
                    result=result_content,
                    is_error=True,
                )
                if state is not None:
                    if state.pending_tool == call.name:
                        state.pending_tool = None
                        state.pending_args = {}
                        state.missing_slots = {}
                continue
            else:
                history_calls.add(call_sig)

            result = await _execute_tool(call, registry)
            _append_tool_result(messages, turn_messages, call, result.content)
            yield ToolResultEvent(
                tool_call_id=call.id,
                name=call.name,
                result=result.content,
                data=result.data,
                is_error=result.is_error,
            )

            if state is not None:
                todo_updated = _mark_running_todo_done(
                    state, call.name, result.content, is_error=result.is_error
                )
                if todo_updated:
                    yield TodoUpdateEvent(todos=list(state.todo_list))
                    if _all_todos_terminal(state):
                        yield _build_skill_complete_event(state)
                if state.pending_tool == call.name:
                    state.pending_tool = None
                    state.pending_args = {}
                    state.missing_slots = {}

        if interrupted:
            return
    else:
        msg = (
            f"[max_iterations] {agent_id}: {max_iterations}회 반복 상한에 도달했습니다. "
            "작업이 완전히 완료되지 않았을 수 있습니다."
        )
        logger.warning(
            "agent harness reached max_iterations=%d (agent=%s)",
            max_iterations,
            agent_id,
        )
        fallback_msg = Message(
            role="user",
            content="[System] 에이전트 반복 상한에 도달했거나 작업이 중단되었습니다. 지금까지 완료한 작업과 실패한 원인을 정리하여 사용자에게 자연어로 최종 답변을 작성하세요. 도구를 호출하지 마세요.",
        )
        messages.append(fallback_msg)

        assistant_buffer.clear()
        async for event in provider.astream(messages, []):
            if event.type == "delta":
                assistant_buffer.append(event.content)
                yield event
            elif event.type == "done":
                break

        assistant_text = "".join(assistant_buffer)
        if assistant_text:
            fallback_response = Message(role="assistant", content=assistant_text)
            messages.append(fallback_response)
            if turn_messages is not None:
                turn_messages.append(fallback_response)
            # 자연어 응답이 생성됐으므로 ErrorEvent 는 프론트에 노출하지 않는다.
            # is_fallback=True 플래그만 보내 UI 가 마지막 메시지를 스타일링하도록 신호.
            yield ErrorEvent(message=msg, is_fallback=True)
        else:
            # fallback LLM 호출 자체가 실패한 경우 — 일반 에러로 노출.
            yield ErrorEvent(message=msg)


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
    orchestrator_state: AgentState | None = None,
) -> AsyncIterator[StreamEvent]:
    """서브 에이전트 turn 을 격리된 컨텍스트에서 실행.

    AgentSwitch → AgentProgress×N → AgentReturn 순으로 yield. 부모 _run_agent_turn
    이 AgentReturnEvent.summary 를 캡처해 tool_result 로 변환한다.

    슬롯 부족(AskUserEvent) 발생 시: orchestrator_state 에 pending_sub_agent 저장 후
    AskUserEvent 를 직접 yield — AgentReturnEvent 없이 종료. 부모 _run_agent_turn
    이 AskUserEvent 를 감지해 해당 턴을 interrupted 처리한다.
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

    # 서브 에이전트가 가지고 진입한 SKILL 목록을 progress 채널로 노출.
    # — UI 가 sub-agent 슬롯 안에 어떤 SKILL 이 활성화됐는지 뱃지로 보여줄 수 있다.
    skill_bodies = _resolve_agent_skills(agent, skill_registry)
    if skill_bodies:
        yield AgentProgressEvent(
            agent_id=agent.meta.name,
            inner_type="skill_active",
            inner_payload={"skills": [s.meta.name for s in skill_bodies]},
        )

    # 격리된 system prompt — base + safety + agent body + 학습 SKILL body.
    sub_system = _compose_sub_agent_system_prompt(
        base=prompt_registry.compose(fallback="", include_orchestrator=False),
        agent=agent_registry._ensure_body(agent),
        skill_bodies=skill_bodies,
    )
    sub_messages: list[Message] = [
        Message(role="system", content=sub_system),
        Message(role="user", content=task),
    ]
    sub_specs = _filter_specs_for_sub_agent(registry.specs(), agent)

    # 서브 에이전트 전용 로컬 상태 — PLANNER 도구 지원용. 디스크에 영속화하지 않음.
    sub_state = AgentState()

    complete_subagent_summary: str | None = None
    last_assistant_text: list[str] = []
    tool_calls_count = 0
    error_count_tracker = 0
    async for ev in _run_agent_turn(
        agent_id=agent.meta.name,
        messages=sub_messages,
        turn_messages=None,
        provider=provider,
        registry=registry,
        sub_specs=sub_specs,
        agent_registry=None,  # sub-agent 는 중첩 dispatch 불가 (L0 방어선)
        prompt_registry=prompt_registry,
        skill_registry=skill_registry,
        budget=budget,
        depth=depth,
        state=sub_state,
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

        if isinstance(ev, ToolResultEvent) and ev.name == COMPLETE_SUB_AGENT:
            # complete_subagent 호출 결과 캡처 — text parsing 대체.
            complete_subagent_summary = ev.result
            yield AgentProgressEvent(
                agent_id=agent.meta.name,
                inner_type=ev.type,
                inner_payload=ev.model_dump(exclude={"type"}),
            )
            continue

        if isinstance(ev, ToolResultEvent):
            # complete_subagent 외 일반 도구 실행 통계 누적.
            tool_calls_count += 1
            if ev.is_error:
                error_count_tracker += 1
            yield AgentProgressEvent(
                agent_id=agent.meta.name,
                inner_type=ev.type,
                inner_payload=ev.model_dump(exclude={"type"}),
            )
            continue

        if isinstance(ev, (ToolCallEvent, ReasoningEvent)):
            yield AgentProgressEvent(
                agent_id=agent.meta.name,
                inner_type=ev.type,
                inner_payload=ev.model_dump(exclude={"type"}),
            )
            continue

        if isinstance(ev, (TodoUpdateEvent, SkillCompleteEvent, SkillActiveEvent)):
            # 서브 에이전트의 PLANNER 상태 변화 / SKILL 활성·완료 신호를 프론트에 전달.
            # SkillActiveEvent 는 provider 가 sub-agent context 에서 직접 yield 한 경우
            # — mock 의 복합 시연 시나리오가 이 경로로 sub-skill 뱃지를 갱신한다.
            yield AgentProgressEvent(
                agent_id=agent.meta.name,
                inner_type=ev.type,
                inner_payload=ev.model_dump(exclude={"type"}),
            )
            continue

        if isinstance(ev, AskUserEvent):
            # 슬롯 부족 또는 ask_user 능동 호출 — orchestrator 에 pending 저장 후 사용자에게 직접 질문.
            if orchestrator_state is not None:
                orchestrator_state.pending_sub_agent = agent.meta.name
                orchestrator_state.pending_sub_task = task
                orchestrator_state.missing_slots = {ev.slot_key: ev.question}
                orchestrator_state.pending_tool = None
                orchestrator_state.pending_args = {}
                # 서브 에이전트가 ask_user sentinel 을 직접 호출한 경우 질문 본문도 기록.
                if ev.tool_name == ASK_USER:
                    orchestrator_state.pending_question = ev.question
            yield ev  # 사용자에게 직접 노출
            return  # AgentReturnEvent 없이 종료 — 부모가 AskUserEvent 를 감지

        if isinstance(ev, ErrorEvent):
            yield AgentReturnEvent(
                from_agent=agent.meta.name,
                summary=f"[error] {agent.meta.name}: {ev.message}",
            )
            return

        # 그 외 이벤트는 silent drop.

    summary = complete_subagent_summary or _extract_task_summary(
        "".join(last_assistant_text).strip(), agent.meta.name
    )
    yield AgentReturnEvent(
        from_agent=agent.meta.name,
        summary=summary,
        todo_log=list(sub_state.todo_list),
        tool_calls_count=tool_calls_count,
        error_count=error_count_tracker,
    )


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

    # 서브 에이전트 pending 이 오케스트레이터 자체 pending 보다 우선.
    if state.pending_sub_agent and state.missing_slots:
        first_q = next(iter(state.missing_slots.values()))
        parts.append(
            "\n# Pending Sub-Agent Slot\n"
            f"직전 턴에 `{state.pending_sub_agent}` 서브 에이전트가 작업 중 "
            f"필요한 정보를 사용자에게 질문했습니다: '{first_q}'.\n"
            f"원래 위임 task: '{state.pending_sub_task}'.\n"
            "사용자의 이번 메시지가 그 응답이라면 즉시 `call_sub_agent` 로 해당 에이전트에게 "
            "사용자가 제공한 정보를 포함해 재위임하세요. "
            "새 주제 전환이면 이 pending 상태를 무시하고 새 요청을 처리하세요."
        )
    elif state.pending_tool and state.missing_slots:
        first_q = next(iter(state.missing_slots.values()))
        parts.append(
            "\n# Pending Slot\n"
            f"당신은 직전 턴에 도구 `{state.pending_tool}` 호출을 위해 "
            f"사용자에게 다음을 물었고 응답을 기다리는 중입니다: '{first_q}'.\n"
            f"부분적으로 채워진 인자: {state.pending_args}.\n"
            "사용자의 이번 메시지가 그 질문에 대한 응답이면 같은 도구를 채워서 다시 호출하세요. "
            "새 주제로 전환된 메시지라면 이 pending 호출을 폐기하고 새 요청을 처리하세요."
        )
    elif state.pending_question:
        # ask_user sentinel 로 능동 질문을 던진 직후 — 사용자의 이번 메시지가 그 답변이다.
        parts.append(
            "\n# Pending User Question\n"
            f"당신은 직전 턴에 사용자에게 다음을 질문했습니다: '{state.pending_question}'.\n"
            "이번 메시지가 그 질문에 대한 답변이라고 가정하고, 받은 답변을 활용해 작업을 이어가세요. "
            "답변이 여전히 모호하면 다시 `ask_user` 를 호출해도 되지만 같은 질문 반복은 금지합니다 — "
            "그 경우엔 가장 합리적인 해석으로 진행하고 결과 보고에서 그 가정을 명시하세요."
        )

    metas = agent_registry.list_meta()
    if metas:
        catalog_lines: list[str] = ["\n# 가용 서브 에이전트 카탈로그"]
        skill_to_agent: dict[str, str] = {}
        for m in metas:
            skills_str = ", ".join(m.skills) if m.skills else "(없음)"
            agent_block: list[str] = [f"- **{m.name}**: {m.description}"]
            if m.role:
                agent_block.append(f"  Role: {m.role}")
            if m.goal:
                agent_block.append(f"  Goal: {m.goal}")
            if m.when_to_delegate:
                # YAML | 블록 입력에 포함된 줄바꿈은 시각적 노이즈가 되므로 한 줄로 정규화.
                inlined = " ".join(m.when_to_delegate.split())
                agent_block.append(f"  When to delegate: {inlined}")
            agent_block.append(f"  전담 스킬: {skills_str}")
            catalog_lines.append("\n".join(agent_block))
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
    identity_lines: list[str] = [f"\n# 당신은 '{agent.meta.name}' 서브 에이전트입니다"]
    if agent.meta.role:
        identity_lines.append(f"- Role: {agent.meta.role}")
    if agent.meta.goal:
        identity_lines.append(f"- Goal: {agent.meta.goal}")
    if len(identity_lines) > 1:
        # role/goal 블록과 body 사이 시각 구분을 위한 빈 줄.
        identity_lines.append("")
    identity_lines.append(agent.body)
    parts.append("\n".join(identity_lines))
    for s in skill_bodies:
        parts.append(f"\n# 학습 Skill: {s.meta.name}\n{s.body}")
    parts.append(
        "\n# 종료 규약 (필수)\n"
        "작업을 완료했으면 반드시 `complete_subagent` 도구를 호출해 결과를 반환하라.\n"
        "summary 파라미터에 수행한 내용과 핵심 결과를 1~3문장으로 기술한다.\n"
        "`complete_subagent` 를 호출하지 않으면 오케스트레이터가 결과를 인식하지 못하므로 "
        "작업 완료 시 마지막 액션으로 반드시 호출해야 한다."
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
    허용 도구:
        - COMPLETE_SUB_AGENT: 서브 에이전트가 완료 시 반드시 호출해야 함.
        - PLANNER_ADD_TODO / PLANNER_COMPLETE_TODO: 서브 에이전트도 자체 작업을
          분해할 수 있도록 허용. sub_state(로컬) 로 관리되므로 오케스트레이터와 분리.
    화이트리스트:
        - agent.meta.tools 비어 있으면 위 금지 외 전체.
        - 비어있지 않으면 그 화이트리스트만 (단 금지 도구는 항상 제외).
    """
    forbidden: frozenset[str] = frozenset({SUB_AGENT_DISPATCH})
    allowed = set(agent.meta.tools)
    out: list[ToolSpec] = []
    for spec in all_specs:
        if spec.name in forbidden:
            continue
        if allowed and spec.name not in allowed:
            continue
        out.append(spec)
    return out


def _all_todos_terminal(state: AgentState) -> bool:
    """todo_list 가 비어 있지 않고 모든 항목이 terminal 상태인지 확인한다."""
    return bool(state.todo_list) and all(
        item.status in _TERMINAL_STATUSES for item in state.todo_list
    )


def _build_skill_complete_event(state: AgentState) -> SkillCompleteEvent:
    """AgentState 의 todo_list 통계로 SkillCompleteEvent 를 생성한다."""
    return SkillCompleteEvent(
        completed=sum(1 for t in state.todo_list if t.status == TodoStatus.COMPLETED),
        failed=sum(1 for t in state.todo_list if t.status == TodoStatus.FAILED),
        skipped=sum(1 for t in state.todo_list if t.status == TodoStatus.SKIPPED),
    )


def _format_sub_agent_result(event: AgentReturnEvent) -> str:
    """AgentReturnEvent 를 오케스트레이터 LLM 컨텍스트용 구조화 텍스트로 변환.

    todo_log 가 있으면 단계별 성공/실패 기록을 포함하고, 없으면 도구 호출 통계만
    추가한다. 오케스트레이터는 이 텍스트를 tool_result 로 받아 Case 5 보고에 활용한다.
    """
    lines: list[str] = [f"[{event.from_agent} 완료] {event.summary}"]

    status_icon: dict[str, str] = {
        TodoStatus.COMPLETED.value: "✓",
        TodoStatus.FAILED.value: "✗",
        TodoStatus.SKIPPED.value: "–",
    }

    if event.todo_log:
        n_completed = sum(1 for t in event.todo_log if t.status == TodoStatus.COMPLETED)
        n_failed = sum(1 for t in event.todo_log if t.status == TodoStatus.FAILED)
        n_skipped = sum(1 for t in event.todo_log if t.status == TodoStatus.SKIPPED)

        stat_parts = [f"완료 {n_completed}"]
        if n_failed:
            stat_parts.append(f"실패 {n_failed}")
        if n_skipped:
            stat_parts.append(f"건너뜀 {n_skipped}")

        lines.append(f"실행 단계: {len(event.todo_log)}개 ({' · '.join(stat_parts)})")
        for item in event.todo_log:
            icon = status_icon.get(item.status.value, "?")
            detail = f": {item.result_summary}" if item.result_summary else ""
            lines.append(f"  [{icon}] {item.description}{detail}")
    elif event.tool_calls_count > 0:
        stat = f"도구 호출: {event.tool_calls_count}건"
        if event.error_count:
            stat += f" (실패 {event.error_count}건)"
        lines.append(stat)

    return "\n".join(lines)


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
    """complete_todo 호출을 받아 task_id 매칭 todo 의 status 를 갱신.

    status 파라미터로 completed / failed / skipped 를 지정할 수 있다.
    잘못된 값이 오면 completed 로 폴백해 LLM 오타에 관대하게 처리한다.
    """
    task_id = (args.get("task_id") or "").strip()
    summary = (args.get("summary") or "").strip() or None
    raw_status = (args.get("status") or "completed").strip().lower()

    status_map = {
        "completed": TodoStatus.COMPLETED,
        "failed": TodoStatus.FAILED,
        "skipped": TodoStatus.SKIPPED,
    }
    new_status = status_map.get(raw_status, TodoStatus.COMPLETED)

    if not task_id:
        return "[planner] complete_todo: task_id 누락"

    for item in state.todo_list:
        if item.task_id == task_id:
            item.status = new_status
            item.result_summary = summary
            return f"[planner] {new_status.value}: {task_id}"

    return f"[planner] complete_todo: task_id '{task_id}' 를 찾을 수 없음"


def _mark_running_todo_done(
    state: AgentState, tool_name: str, result_text: str, *, is_error: bool = False
) -> bool:
    """일반 도구 실행 결과를 같은 tool_name 의 활성 todo 에 자동 반영한다.

    PENDING 또는 RUNNING 중 tool_name 이 일치하는 첫 항목을 갱신한다.
    is_error=True 면 FAILED, 아니면 COMPLETED 로 전이한다.

    Returns:
        True: todo 가 실제로 갱신된 경우 (호출자가 TodoUpdateEvent 를 yield 해야 함).
        False: 일치하는 항목 없음.
    """
    target_statuses = {TodoStatus.PENDING, TodoStatus.RUNNING}
    new_status = TodoStatus.FAILED if is_error else TodoStatus.COMPLETED
    for item in state.todo_list:
        if item.status in target_statuses and item.tool_name == tool_name:
            item.status = new_status
            item.result_summary = result_text[:120]
            return True
    return False


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


async def _execute_tool(call: ToolCall, registry: ToolRegistry) -> ToolResult:
    """등록된 도구를 timeout 안에서 실행해 ToolResult 로 표준화한다.

    반환 규약:
        - 도구가 str 반환 → ToolResult(content=str)
        - 도구가 ToolResult 반환 → 그대로
        - timeout / ValueError / KeyError / TypeError → is_error=True ToolResult
        - sentinel 도구가 여기까지 흘러온 경우 (harness 분기 누락) → 명시적 에러
    """
    tool = registry.get(call.name)
    if tool is None:
        return ToolResult(content=f"[error] unknown tool: {call.name}", is_error=True)

    if tool.sentinel:
        # harness 분기가 누락된 프로그래밍 버그 — 조용히 통과하지 말 것.
        return ToolResult(
            content=f"[error] sentinel tool '{call.name}' bypassed harness intercept",
            is_error=True,
        )

    try:
        result = await asyncio.wait_for(
            tool.fn(**(call.arguments or {})), timeout=tool.timeout_seconds
        )
    except asyncio.TimeoutError:
        result = ToolResult(
            content=f"[timeout] {call.name} exceeded {tool.timeout_seconds}s",
            is_error=True,
        )
    except Exception as exc:
        # 도구가 던질 수 있는 예외 범위를 사전에 열거하기 어려우므로 광역 catch 유지.
        # 단, 스택트레이스를 보존해 운영 중 원인 추적이 가능하도록 한다.
        logger.exception("tool '%s' raised an unexpected exception", call.name)
        result = ToolResult(
            content=f"[error] {type(exc).__name__}: {exc}", is_error=True
        )

    if isinstance(result, str):
        result = ToolResult(content=result)
    elif not isinstance(result, ToolResult):
        # 도구가 dict 등 임의 객체를 돌려주면 문자열화해 LLM 컨텍스트에 안전 전달.
        result = ToolResult(
            content=str(result),
            data={"raw": result} if isinstance(result, dict) else None,
        )

    if result.is_error:
        result.content += "\n\n[System] 작업이 실패했습니다. 에러 로그를 읽고 원인을 분석(Root Cause Analysis)한 뒤 최대 1회 더 재시도하세요."

    return result


__all__ = ["run_turn", "TurnBudget", "ORCHESTRATOR_ID"]
