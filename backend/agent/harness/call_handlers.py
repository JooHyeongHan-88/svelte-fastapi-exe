"""tool_call 단건 처리 — 3단계 파이프라인 + sentinel 디스패치 테이블.

``_run_agent_turn`` 의 provider→tool 루프가 assistant 가 emit 한 tool_call 하나하나를
이 모듈의 ``_handle_tool_call`` 에 위임한다. 처리는 3단계다:

    1. 특수 호출 처리 — F3 깨진 인자 + sentinel 도구(activate_skill / complete_subagent
       / add_todo / complete_todo / ask_user / call_sub_agent[s_parallel]).
    2. 인자 검증 + 중복 감지 — 일반 도구의 슬롯 가드·루프 가드.
    3. 정상 도구 실행 — ``_execute_tool`` + 결과 todo 반영.

모든 핸들러는 **균일하게 async generator** 다 — ``StreamEvent`` 를 즉시 yield 하고
(서브 에이전트의 긴 진행 스트림도 그대로 흘려보냄), 제어 흐름은 호출부가 건넨
``CallOutcome`` 아웃파라미터로 보고한다(``result_holder`` 아웃파라미터 관례와 동일).
이렇게 하면 sync/async sentinel 을 가르지 않고 단일 디스패치 프로토콜로 통일된다.

제어 흐름 세 가지:
    - 기본(CONTINUE): outcome 미변경 → 다음 tool_call 처리.
    - INTERRUPT(``outcome.interrupted=True``): ask_user·슬롯 누락 → 루프 break 후
      미해결 tool_call 보정.
    - STOP(``outcome.stop=True``): complete_subagent → ``_run_agent_turn`` 즉시 종료.
"""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from agent.config import MAX_PARALLEL_SUBAGENTS
from agent.guard import SlotCheckResult, validate_tool_args
from agent.models import (
    MALFORMED_TOOL_ARGS_KEY,
    AgentReturnEvent,
    AgentState,
    AskUserEvent,
    Message,
    SkillActiveEvent,
    StreamEvent,
    TodoUpdateEvent,
    ToolCall,
    ToolResultEvent,
)
from agent.registries.agents import AgentRegistry
from agent.registries.prompts import PromptRegistry
from agent.registries.skills import Skill, SkillRegistry
from agent.registries.tools import (
    ACTIVATE_SKILL,
    ASK_USER,
    COMPLETE_SUB_AGENT,
    PLANNER_ADD_TODO,
    PLANNER_COMPLETE_TODO,
    SUB_AGENT_DISPATCH,
    SUB_AGENTS_PARALLEL_DISPATCH,
    ToolRegistry,
)
from agent.providers.factory import LLMProvider

from agent.harness.budget import TurnBudget
from agent.harness.dispatch.parallel import _dispatch_parallel_sub_agents
from agent.harness.dispatch.result_format import _format_sub_agent_result
from agent.harness.dispatch.sequential import _dispatch_sub_agent
from agent.harness.state.loop_guard import (
    _LOOP_GUARD_MESSAGE,
    _call_signature,
    _record_invalid_call,
)
from agent.harness.state.pending import clear_pending_tool
from agent.harness.state.todo import (
    _all_todos_terminal,
    _build_skill_complete_event,
    _handle_add_todo,
    _handle_complete_todo,
    _mark_running_todo_done,
)
from agent.harness.tool_exec import _append_tool_result, _execute_tool


# ---------------------------------------------------------------------------
# Turn 실행 컨텍스트 + 단건 처리 결과
# ---------------------------------------------------------------------------


@dataclass
class TurnContext:
    """``_run_agent_turn`` 한 번의 turn 전체에서 참조가 고정된 실행 환경.

    핸들러 시그니처를 ``(ctx, call, outcome)`` 로 통일하기 위한 파라미터 객체.
    필드는 turn 시작 시 한 번 묶이며, 가변 컬렉션(``messages``·``history_calls``·
    ``active_skills``)은 동일 객체를 in-place 갱신한다. sentinel·dispatch 핸들러가
    SentinelCtx/DispatchCtx 로 나뉘지 않고 하나를 공유한다 — 빌드 1회·핸들러 시그니처
    통일이 분리보다 단순하다(각 핸들러는 필요한 필드만 참조).
    """

    agent_id: str
    # astream(messages, tools) 어댑터 — providers.factory 의 Protocol.
    provider: LLMProvider
    registry: ToolRegistry
    agent_registry: AgentRegistry | None
    prompt_registry: PromptRegistry
    skill_registry: SkillRegistry
    budget: TurnBudget
    depth: int
    max_iterations: int
    state: AgentState | None
    active_skills: list[Skill] | None
    recompose_system: Callable[[list[Skill]], str] | None
    messages: list[Message]
    turn_messages: list[Message] | None
    history_calls: set[tuple[str, str, str]]

    @property
    def is_sub_agent(self) -> bool:
        """서브 에이전트 컨텍스트 여부 — turn_messages=None 이 관례적 신호."""
        return self.turn_messages is None


@dataclass
class CallOutcome:
    """tool_call 한 건 처리 후 호출부가 읽는 제어 신호.

    둘 다 False 면 CONTINUE(다음 호출). 핸들러가 하나만 set 한다.
    """

    interrupted: bool = False  # ask_user·슬롯 누락 → break 후 미해결 호출 보정
    stop: bool = False  # complete_subagent → _run_agent_turn 즉시 종료


# ---------------------------------------------------------------------------
# 공통 헬퍼 — 여러 핸들러가 공유하는 검증된 로직
# ---------------------------------------------------------------------------


def _emit_missing_slot(
    state: AgentState | None, call: ToolCall, guard: SlotCheckResult
) -> tuple[str, AskUserEvent]:
    """필수 슬롯 누락을 state 에 기록하고 사용자에게 재질문할 AskUserEvent 를 만든다.

    call_sub_agent / call_sub_agents_parallel / 일반 도구 세 핸들러에 동일하게
    중복되던 블록을 일원화한다. 제어흐름(outcome.interrupted=True)은 호출부 유지.

    Returns:
        (tool_result placeholder 텍스트, 사용자에게 보낼 AskUserEvent).
    """
    first = guard.missing[0]
    if state is not None:
        state.missing_slots = {m.key: m.question for m in guard.missing}
        state.pending_tool = call.name
        state.pending_args = dict(call.arguments)
    placeholder = f"[guard] missing required slots: {[m.key for m in guard.missing]}"
    event = AskUserEvent(
        question=first.question,
        slot_key=first.key,
        options=first.options,
        tool_name=call.name,
        input_type="both" if first.options else "text",
    )
    return placeholder, event


def _invalid_call_message(
    call: ToolCall, history_calls: set[tuple[str, str, str]], fallback: str
) -> str:
    """반복된 형식오류 호출이면 루프가드 메시지, 아니면 fallback 을 반환한다.

    malformed args(F3)와 형식오류 분기(invalid_message)의 '루프가드-or-에러' 결정을
    일원화한다. ``_record_invalid_call`` 이 history_calls 에 시그니처를 기록하는
    부수효과를 그대로 수행한다 (정상↔형식오류 루프 동시 감지).
    """
    if _record_invalid_call(call, history_calls):
        return _LOOP_GUARD_MESSAGE
    return fallback


def _guard_tool_args(
    ctx: TurnContext, call: ToolCall, outcome: CallOutcome
) -> list[StreamEvent] | None:
    """등록 도구 인자를 검증한다. 통과면 None, 실패면 호출부가 yield 할 이벤트 목록.

    call_sub_agent / call_sub_agents_parallel / 일반 도구 세 핸들러에 동일하게
    중복되던 '검증 → 형식오류 회신 → 슬롯 누락 질문' 프롤로그를 일원화한다. 호출부는::

        denial = _guard_tool_args(ctx, call, outcome)
        if denial is not None:
            for ev in denial:
                yield ev
            return

    - 형식 오류(invalid_message): LLM self-correct 용 ToolResultEvent(is_error) 1건.
      반복되면 루프가드 메시지로 전환. outcome 미변경 → 호출부 CONTINUE.
    - 슬롯 누락(not ok): AskUserEvent 1건 + ``outcome.interrupted=True`` → 호출부 INTERRUPT.
    - 통과: None (이벤트 없음 — 호출부가 실행 단계로 진입).
    """
    guard = validate_tool_args(call.arguments, ctx.registry.get(call.name))
    if guard.invalid_message:
        # 형식 오류 — 사용자에게 묻지 않고 LLM 에 도구 에러로 회신해 self-correct.
        result_content = _invalid_call_message(
            call, ctx.history_calls, guard.invalid_message
        )
        _append_tool_result(ctx.messages, ctx.turn_messages, call, result_content)
        return [
            ToolResultEvent(
                tool_call_id=call.id,
                name=call.name,
                result=result_content,
                is_error=True,
            )
        ]
    if not guard.ok:
        placeholder, ask_ev = _emit_missing_slot(ctx.state, call, guard)
        _append_tool_result(ctx.messages, ctx.turn_messages, call, placeholder)
        outcome.interrupted = True
        return [ask_ev]
    return None


# ---------------------------------------------------------------------------
# 1단계 — 특수 호출 핸들러 (malformed args + sentinel 도구)
# ---------------------------------------------------------------------------


async def _handle_malformed_args(
    ctx: TurnContext, call: ToolCall, outcome: CallOutcome
) -> AsyncIterator[StreamEvent]:
    """F3: tool_call 인자 JSON 파싱 실패 — 사용자에게 묻지 않고 LLM 에 재전송 요구.

    빈 인자로 오인해 슬롯 누락을 질문하는 것을 방지한다. 반복되면 루프가드로 전환.
    """
    result_content = _invalid_call_message(
        call,
        ctx.history_calls,
        f"[arg-error] '{call.name}' 도구의 인자가 유효한 JSON 이 아닙니다 (스트리밍 "
        "중 잘렸거나 형식이 깨졌습니다). 인자를 더 짧고 정확한 JSON 으로 같은 도구를 "
        "다시 호출하세요.",
    )
    _append_tool_result(ctx.messages, ctx.turn_messages, call, result_content)
    yield ToolResultEvent(
        tool_call_id=call.id, name=call.name, result=result_content, is_error=True
    )


def _activate_skills_in_context(ctx: TurnContext, skill_name: str) -> list[Skill]:
    """skill_name 을 turn-local active_skills 에 추가하고 새로 활성화된 것만 반환한다.

    이미 활성화됐거나 카탈로그에 없으면 빈 리스트 (호출부가 멱등 응답 분기에 사용).
    """
    assert ctx.active_skills is not None  # 라우팅 조건 보장
    existing_names = {s.meta.name for s in ctx.active_skills}
    newly_activated = (
        ctx.skill_registry.get_by_names([skill_name])
        if skill_name and skill_name not in existing_names
        else []
    )
    ctx.active_skills.extend(newly_activated)
    return newly_activated


async def _handle_activate_skill(
    ctx: TurnContext, call: ToolCall, outcome: CallOutcome
) -> AsyncIterator[StreamEvent]:
    """activate_skill — SKILL 카탈로그 의미 기반 활성화. turn-local active_skills 갱신."""
    skill_name = (call.arguments or {}).get("name", "").strip()
    newly_activated = _activate_skills_in_context(ctx, skill_name)
    if newly_activated and ctx.recompose_system is not None:
        ctx.messages[0] = Message(
            role="system", content=ctx.recompose_system(list(ctx.active_skills))
        )
        yield SkillActiveEvent(skills=[s.meta.name for s in ctx.active_skills])
        if ctx.state is not None:
            ctx.state.active_skills = [s.meta.name for s in ctx.active_skills]
    result_text = (
        f"SKILL '{skill_name}' 활성화됨. 이제 해당 SKILL 의 지침이 컨텍스트에 포함됩니다."
        if newly_activated
        else f"SKILL '{skill_name}' 은(는) 이미 활성화되어 있거나 카탈로그에 없습니다."
    )
    _append_tool_result(ctx.messages, ctx.turn_messages, call, result_text)
    yield ToolResultEvent(
        tool_call_id=call.id,
        name=call.name,
        result=result_text,
        is_error=not newly_activated,
    )


async def _handle_complete_subagent(
    ctx: TurnContext, call: ToolCall, outcome: CallOutcome
) -> AsyncIterator[StreamEvent]:
    """complete_subagent — 서브 에이전트 종료 sentinel.

    ToolResultEvent 를 emit 하면 _dispatch_sub_agent 가 이를 캡처해 요약으로 쓴다.
    outcome.stop 으로 _run_agent_turn 을 즉시 종료시킨다(이후 tool_call 무시).
    """
    result_text = (call.arguments or {}).get("summary", "")
    _append_tool_result(ctx.messages, ctx.turn_messages, call, result_text)
    yield ToolResultEvent(tool_call_id=call.id, name=call.name, result=result_text)
    outcome.stop = True


async def _handle_add_todo_call(
    ctx: TurnContext, call: ToolCall, outcome: CallOutcome
) -> AsyncIterator[StreamEvent]:
    """add_todo sentinel — plan(todo) 누적 + 스냅샷 이벤트."""
    assert ctx.state is not None  # 라우팅 조건 보장
    result_text = _handle_add_todo(ctx.state, call.arguments)
    _append_tool_result(ctx.messages, ctx.turn_messages, call, result_text)
    yield ToolResultEvent(tool_call_id=call.id, name=call.name, result=result_text)
    yield TodoUpdateEvent(todos=list(ctx.state.todo_list))


async def _handle_complete_todo_call(
    ctx: TurnContext, call: ToolCall, outcome: CallOutcome
) -> AsyncIterator[StreamEvent]:
    """complete_todo sentinel — todo 상태 전이 + 전원 terminal 시 완료 통계."""
    assert ctx.state is not None  # 라우팅 조건 보장
    result_text = _handle_complete_todo(ctx.state, call.arguments)
    _append_tool_result(ctx.messages, ctx.turn_messages, call, result_text)
    yield ToolResultEvent(tool_call_id=call.id, name=call.name, result=result_text)
    yield TodoUpdateEvent(todos=list(ctx.state.todo_list))
    if _all_todos_terminal(ctx.state):
        yield _build_skill_complete_event(ctx.state)


async def _handle_ask_user(
    ctx: TurnContext, call: ToolCall, outcome: CallOutcome
) -> AsyncIterator[StreamEvent]:
    """ask_user sentinel — LLM 능동 보완 질문. placeholder 한 줄 + AskUserEvent 후 중단."""
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

    if ctx.state is not None:
        ctx.state.pending_question = question

    placeholder = f"[ask_user] 사용자에게 질문을 던졌습니다: {question}"
    _append_tool_result(ctx.messages, ctx.turn_messages, call, placeholder)
    yield ToolResultEvent(tool_call_id=call.id, name=call.name, result=placeholder)
    yield AskUserEvent(
        question=question,
        slot_key=ASK_USER,
        options=options,
        tool_name=ASK_USER,
        input_type=input_type,
    )
    outcome.interrupted = True


def _clear_pending_sub_agent_on_success(ctx: TurnContext, call: ToolCall) -> None:
    """위임이 성공 완료되면 그 에이전트에 걸린 pending 재위임 잔재를 비운다.

    직전 턴 서브 에이전트가 슬롯 부족으로 중단됐을 때 걸어둔 pending_sub_agent 가
    이번 위임으로 해소됐으면 다음 턴 system prompt 오염을 막는다.
    """
    if ctx.state is None:
        return
    dispatched_name = (call.arguments or {}).get("agent_name")
    if ctx.state.pending_sub_agent == dispatched_name:
        ctx.state.pending_sub_agent = None
        ctx.state.pending_sub_task = None
        ctx.state.missing_slots = {}


async def _handle_sub_agent_dispatch(
    ctx: TurnContext, call: ToolCall, outcome: CallOutcome
) -> AsyncIterator[StreamEvent]:
    """call_sub_agent — 순차 서브 에이전트 위임. async generator nesting 으로 통과."""
    assert ctx.agent_registry is not None  # 라우팅 조건 보장
    denial = _guard_tool_args(ctx, call, outcome)
    if denial is not None:
        for ev in denial:
            yield ev
        return

    captured_summary = (
        f"[error] {call.arguments.get('agent_name', '?')}: "
        "sub-agent 가 요약을 반환하지 않음"
    )
    sub_interrupted = False
    async for sub_ev in _dispatch_sub_agent(
        call=call,
        parent_agent_id=ctx.agent_id,
        agent_registry=ctx.agent_registry,
        skill_registry=ctx.skill_registry,
        prompt_registry=ctx.prompt_registry,
        registry=ctx.registry,
        provider=ctx.provider,
        budget=ctx.budget,
        depth=ctx.depth + 1,
        max_iterations=ctx.max_iterations,
        orchestrator_state=ctx.state,
    ):
        yield sub_ev
        if isinstance(sub_ev, AgentReturnEvent):
            # todo_log 와 통계를 포함한 구조화 텍스트로 LLM 컨텍스트에 주입.
            captured_summary = _format_sub_agent_result(sub_ev)
        elif isinstance(sub_ev, AskUserEvent):
            # 서브 에이전트 슬롯 부족 — 사용자 질문을 그대로 전달 후 중단.
            sub_interrupted = True

    if sub_interrupted:
        outcome.interrupted = True
        return

    _clear_pending_sub_agent_on_success(ctx, call)
    _append_tool_result(ctx.messages, ctx.turn_messages, call, captured_summary)
    yield ToolResultEvent(tool_call_id=call.id, name=call.name, result=captured_summary)


async def _handle_parallel_dispatch(
    ctx: TurnContext, call: ToolCall, outcome: CallOutcome
) -> AsyncIterator[StreamEvent]:
    """call_sub_agents_parallel — 독립 작업들을 동시에 실행하고 단일 결과로 합침."""
    assert ctx.agent_registry is not None  # 라우팅 조건 보장
    denial = _guard_tool_args(ctx, call, outcome)
    if denial is not None:
        for ev in denial:
            yield ev
        return

    # 병렬 디스패처가 모든 서브 에이전트 이벤트를 인터리브해 yield 하고,
    # 완료 후 통합 요약을 result_holder["combined"] 에 채운다.
    parallel_result: dict[str, str] = {}
    async for sub_ev in _dispatch_parallel_sub_agents(
        call=call,
        parent_agent_id=ctx.agent_id,
        agent_registry=ctx.agent_registry,
        skill_registry=ctx.skill_registry,
        prompt_registry=ctx.prompt_registry,
        registry=ctx.registry,
        provider=ctx.provider,
        budget=ctx.budget,
        depth=ctx.depth + 1,
        max_iterations=ctx.max_iterations,
        orchestrator_state=ctx.state,
        max_parallel=MAX_PARALLEL_SUBAGENTS,
        result_holder=parallel_result,
    ):
        yield sub_ev

    captured_summary = parallel_result.get(
        "combined", "[error] 병렬 위임 결과가 비어 있습니다"
    )
    _append_tool_result(ctx.messages, ctx.turn_messages, call, captured_summary)
    yield ToolResultEvent(tool_call_id=call.id, name=call.name, result=captured_summary)


# ---------------------------------------------------------------------------
# 2+3단계 — 일반 도구: 슬롯 가드 → 중복 감지 → 실행
# ---------------------------------------------------------------------------


def _loop_guard_denial(ctx: TurnContext, call: ToolCall) -> list[StreamEvent] | None:
    """동일 시그니처 재호출이면 루프가드 이벤트, 처음 보는 호출이면 기록 후 None.

    ``_guard_tool_args`` 와 같은 "통과면 None, 차단이면 yield 이벤트" 계약을 따른다.
    R4: 시그니처는 ``result/`` 인자 파일 fingerprint 까지 포함해, 파일을 고쳐 쓴
    뒤 같은 경로로 재호출하는 정당한 재시도는 차단하지 않는다.
    """
    call_sig = _call_signature(call)
    if call_sig not in ctx.history_calls:
        ctx.history_calls.add(call_sig)
        return None
    _append_tool_result(ctx.messages, ctx.turn_messages, call, _LOOP_GUARD_MESSAGE)
    if ctx.state is not None and ctx.state.pending_tool == call.name:
        clear_pending_tool(ctx.state)
    return [
        ToolResultEvent(
            tool_call_id=call.id,
            name=call.name,
            result=_LOOP_GUARD_MESSAGE,
            is_error=True,
        )
    ]


async def _emit_post_tool_todo_events(
    ctx: TurnContext, call: ToolCall, result_content: str, *, is_error: bool
) -> AsyncIterator[StreamEvent]:
    """도구 실행 직후 todo 상태 전이를 반영하고 pending 슬롯을 정리한다.

    실행 중이던 todo 를 결과에 맞춰 종료시키고, 전원 terminal 이면 완료 통계까지 emit.
    state 가 없는(서브 에이전트 등) 컨텍스트면 no-op.
    """
    if ctx.state is None:
        return
    todo_updated = _mark_running_todo_done(
        ctx.state, call.name, result_content, is_error=is_error
    )
    if todo_updated:
        yield TodoUpdateEvent(todos=list(ctx.state.todo_list))
        if _all_todos_terminal(ctx.state):
            yield _build_skill_complete_event(ctx.state)
    if ctx.state.pending_tool == call.name:
        clear_pending_tool(ctx.state)


async def _handle_normal_tool(
    ctx: TurnContext, call: ToolCall, outcome: CallOutcome
) -> AsyncIterator[StreamEvent]:
    """sentinel 이 아닌 일반 등록 도구 — 검증·루프가드 통과 후 실행한다."""
    denial = _guard_tool_args(ctx, call, outcome)
    if denial is None:
        denial = _loop_guard_denial(ctx, call)
    if denial is not None:
        for ev in denial:
            yield ev
        return

    result = await _execute_tool(call, ctx.registry)
    _append_tool_result(ctx.messages, ctx.turn_messages, call, result.content)
    yield ToolResultEvent(
        tool_call_id=call.id,
        name=call.name,
        result=result.content,
        data=result.data,
        is_error=result.is_error,
    )

    async for ev in _emit_post_tool_todo_events(
        ctx, call, result.content, is_error=result.is_error
    ):
        yield ev


# ---------------------------------------------------------------------------
# 디스패치 테이블 + 단건 처리 진입점
# ---------------------------------------------------------------------------

# 핸들러 시그니처: async generator (ctx, call, outcome) -> StreamEvent 스트림.
_Handler = Callable[[TurnContext, ToolCall, CallOutcome], AsyncIterator[StreamEvent]]

# (sentinel 이름, 적용 조건, 핸들러). 조건은 원래 if/elif 의 컨텍스트 가드를 그대로
# 보존한다 — 조건 미충족 시 라우팅에서 빠져 일반 도구 경로로 폴백한다(예: 서브
# 에이전트 컨텍스트에서 흘러든 orchestrator 전용 sentinel → sentinel-bypass 에러).
# 이름은 유일하므로 순서는 무관하나 원래 if/elif 순서를 따른다.
_SENTINEL_ROUTES: tuple[tuple[str, Callable[[TurnContext], bool], _Handler], ...] = (
    (ACTIVATE_SKILL, lambda c: c.active_skills is not None, _handle_activate_skill),
    (COMPLETE_SUB_AGENT, lambda c: c.is_sub_agent, _handle_complete_subagent),
    (PLANNER_ADD_TODO, lambda c: c.state is not None, _handle_add_todo_call),
    (PLANNER_COMPLETE_TODO, lambda c: c.state is not None, _handle_complete_todo_call),
    (ASK_USER, lambda c: True, _handle_ask_user),
    (
        SUB_AGENT_DISPATCH,
        lambda c: c.agent_registry is not None,
        _handle_sub_agent_dispatch,
    ),
    (
        SUB_AGENTS_PARALLEL_DISPATCH,
        lambda c: c.agent_registry is not None,
        _handle_parallel_dispatch,
    ),
)


def _select_sentinel_handler(ctx: TurnContext, call: ToolCall) -> _Handler | None:
    """call 에 맞는 sentinel 핸들러를 고른다. 없으면 None(=일반 도구 경로)."""
    for name, applies, handler in _SENTINEL_ROUTES:
        if call.name == name and applies(ctx):
            return handler
    return None


async def _handle_tool_call(
    ctx: TurnContext, call: ToolCall, outcome: CallOutcome
) -> AsyncIterator[StreamEvent]:
    """tool_call 한 건을 3단계 파이프라인으로 처리해 StreamEvent 를 yield 한다.

    제어 흐름은 ``outcome`` 으로 보고한다 (기본 CONTINUE / interrupted / stop).
    """
    # 1단계 (특수) — F3 깨진 인자: 이름이 아니라 인자 내용으로 분기.
    if MALFORMED_TOOL_ARGS_KEY in (call.arguments or {}):
        async for ev in _handle_malformed_args(ctx, call, outcome):
            yield ev
        return

    # 1단계 (특수) — sentinel 디스패치 테이블.
    handler = _select_sentinel_handler(ctx, call)
    if handler is not None:
        async for ev in handler(ctx, call, outcome):
            yield ev
        return

    # 2+3단계 — 일반 도구: 검증 → 중복 감지 → 실행.
    async for ev in _handle_normal_tool(ctx, call, outcome):
        yield ev
