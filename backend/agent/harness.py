"""Agent harness — provider 와 도구 사이의 turn 실행 루프 (고도화 버전).

run_turn 한 번 = 사용자 입력 1건에 대한 응답 1턴.

흐름:
    1. state_store 에서 AgentState (todo/missing_slots) 를 로드.
    2. PromptRegistry(base+safety) + SkillRegistry.select() 결과 + state 요약을 합쳐
       system prompt 를 동적 조립.
    3. provider.astream 이벤트를 그대로 흘려보내되, tool_call 은 분기:
         - add_todo / complete_todo → harness 가 직접 AgentState 갱신
         - 그 외 도구 → 슬롯 가드 → 통과 시 _execute_tool, 누락 시 AskUserEvent
    4. 슬롯 답변 라우팅은 LLM 에게 위임 — system prompt 의 "Pending Slot" 블록을 보고
       LLM 이 같은 도구를 다시 호출하면 정상 실행 경로로 통과, 무시하면 자동 폐기.
    5. 턴 종료 시 store.append + state_store.set + DoneEvent.

불변 계약 (깨면 안 됨):
    - provider.astream 의 delta/tool_call/done 이벤트 흐름
    - AsyncIterator[StreamEvent] 시그니처
    - 마지막에 DoneEvent yield, 예외는 ErrorEvent 로 변환
"""

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from agent.guard import check_required_slots
from agent.models import (
    AgentState,
    AskUserEvent,
    DoneEvent,
    ErrorEvent,
    Message,
    SkillActiveEvent,
    StreamEvent,
    TodoItem,
    TodoStatus,
    TodoUpdateEvent,
    ToolCall,
    ToolResultEvent,
)
from agent.registries.prompts import PromptRegistry
from agent.registries.skills import Skill, SkillRegistry
from agent.registries.tools import PLANNER_ADD_TODO, PLANNER_COMPLETE_TODO, ToolRegistry
from agent.stores.agent_state import AgentStateStore
from agent.stores.conversation import ConversationStore

logger = logging.getLogger(__name__)


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
        max_iterations: provider→tool→provider 반복 상한.
        force_skills: 슬래시 커맨드로 명시된 skill 이름들. 지정 시 trigger 매칭
            대신 이 목록을 그대로 활성화한다 (UI 에서 사용자가 직접 선택한 경우).

    Yields:
        StreamEvent: delta / tool_call / tool_result / ask_user / todo_update / done / error.
    """
    history = store.get_history(client_id)
    state = state_store.get(client_id)
    user_msg = Message(role="user", content=user_message)
    turn_messages: list[Message] = [user_msg]

    try:
        # force_skills 가 있으면 trigger 매칭을 완전히 우회 — 사용자 명시가 최우선.
        if force_skills:
            skills = skill_registry.get_by_names(force_skills)
        else:
            skills = skill_registry.select(user_message)
        state.active_skills = [s.meta.name for s in skills]
        composed_system = _compose_system_prompt(
            prompt_registry.compose(fallback=system_prompt_fallback),
            skills,
            state,
        )

        messages: list[Message] = [
            Message(role="system", content=composed_system),
            *history,
            user_msg,
        ]

        # 매칭된 스킬이 있으면 프론트에 먼저 알려 뱃지를 즉시 표시한다.
        if skills:
            yield SkillActiveEvent(skills=[s.meta.name for s in skills])

        # 진입 시점에 진행 중 todo 가 있다면 미리 알린다 — UI 후속 작업용.
        if state.todo_list:
            yield TodoUpdateEvent(todos=list(state.todo_list))

        assistant_buffer: list[str] = []
        pending_tool_calls: list[ToolCall] = []

        for iteration in range(max_iterations):
            del iteration

            assistant_buffer.clear()
            pending_tool_calls.clear()

            async for event in provider.astream(messages, registry.specs()):
                if event.type == "delta":
                    assistant_buffer.append(event.content)
                    yield event
                    continue

                if event.type == "tool_call":
                    pending_tool_calls.append(event.call)
                    yield event
                    continue

                if event.type == "done":
                    break

                # provider 가 직접 error 등을 보낸 경우 그대로 전달하고 종료.
                yield event
                return

            assistant_text = "".join(assistant_buffer)

            if not pending_tool_calls:
                if assistant_text:
                    turn_messages.append(
                        Message(role="assistant", content=assistant_text)
                    )
                break

            assistant_msg = Message(
                role="assistant",
                content=assistant_text,
                tool_calls=list(pending_tool_calls),
            )
            messages.append(assistant_msg)
            turn_messages.append(assistant_msg)

            interrupted = False
            for call in pending_tool_calls:
                if call.name == PLANNER_ADD_TODO:
                    result_text = _handle_add_todo(state, call.arguments)
                    _append_tool_result(messages, turn_messages, call, result_text)
                    yield ToolResultEvent(
                        tool_call_id=call.id, name=call.name, result=result_text
                    )
                    yield TodoUpdateEvent(todos=list(state.todo_list))
                    continue

                if call.name == PLANNER_COMPLETE_TODO:
                    result_text = _handle_complete_todo(state, call.arguments)
                    _append_tool_result(messages, turn_messages, call, result_text)
                    yield ToolResultEvent(
                        tool_call_id=call.id, name=call.name, result=result_text
                    )
                    yield TodoUpdateEvent(todos=list(state.todo_list))
                    continue

                tool = registry.get(call.name)
                guard = check_required_slots(call.arguments, tool)
                if not guard.ok:
                    # 가드 발동 — pending_tool 저장 후 사용자에게 되묻고 안전 종료.
                    # LLM 이 같은 턴에 재호출하지 않도록 가드 결과를 tool 응답처럼 끼워 둠.
                    first = guard.missing[0]
                    state.missing_slots = {m.key: m.question for m in guard.missing}
                    state.pending_tool = call.name
                    state.pending_args = dict(call.arguments)

                    _append_tool_result(
                        messages,
                        turn_messages,
                        call,
                        f"[guard] missing required slots: {list(state.missing_slots)}",
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

                _mark_running_todo_done(state, call.name, result_text)

                # 직전 턴 missing_slot 의 보류 도구가 정상 실행됐다 — pending 해제.
                if state.pending_tool == call.name:
                    state.pending_tool = None
                    state.pending_args = {}
                    state.missing_slots = {}

            if interrupted:
                break
        else:
            logger.warning("agent harness reached max_iterations=%d", max_iterations)

        store.append(client_id, *turn_messages)
        state_store.set(client_id, state)
        yield DoneEvent()

    except Exception as exc:  # noqa: BLE001 — 사용자에게 에러 이벤트로 변환해 전달
        logger.exception("harness run_turn failed")
        yield ErrorEvent(message=str(exc))


# ---------------------------------------------------------------------------
# 시스템 프롬프트 조립
# ---------------------------------------------------------------------------


def _compose_system_prompt(
    base: str,
    skills: list[Skill],
    state: AgentState,
) -> str:
    """PROMPTS 베이스 + 선택된 SKILLS 본문 + AgentState 요약을 합성한다.

    Args:
        base: PromptRegistry.compose() 결과 (base.md + safety.md).
        skills: SkillRegistry.select() 매칭 결과.
        state: 현재 client 의 AgentState.

    Returns:
        조립된 system 메시지 본문.
    """
    parts: list[str] = [base] if base else []

    for s in skills:
        parts.append(f"\n# Skill: {s.meta.name}\n{s.body}")

    # 스킬이 2개 이상이면 실행 순서를 plan 으로 먼저 등록하도록 강제한다.
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

    # 슬롯 답변 라우팅을 LLM 에게 위임 — 직전 턴 pending 상태를 명시해 둔다.
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
    """add_todo 호출을 받아 state.todo_list 에 TodoItem 들을 누적한다.

    Args:
        state: 갱신할 AgentState (in-place 수정).
        args: {"items": [{"description": str, "tool_name": str | None}, ...]}.

    Returns:
        tool 응답으로 LLM 에 돌려줄 문자열 (추가된 task_id 목록 또는 에러).
    """
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
    return f"[planner] added {len(added)} todo(s): {added}"


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
    turn_messages: list[Message],
    call: ToolCall,
    result_text: str,
) -> None:
    """LLM 컨텍스트와 영구 히스토리 양쪽에 tool 응답을 동일하게 누적한다."""
    tool_msg = Message(
        role="tool",
        content=result_text,
        tool_call_id=call.id,
    )
    messages.append(tool_msg)
    turn_messages.append(tool_msg)


async def _execute_tool(call: ToolCall, registry: ToolRegistry) -> str:
    tool = registry.get(call.name)
    if tool is None:
        return f"[error] unknown tool: {call.name}"

    try:
        return await tool.run(call.arguments)
    except (ValueError, KeyError, TypeError) as exc:
        return f"[error] {type(exc).__name__}: {exc}"
