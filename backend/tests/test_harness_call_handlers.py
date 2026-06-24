"""call_handlers 개별 핸들러 격리 단위 테스트.

``_run_agent_turn`` 통합 테스트(test_harness_*)가 전체 루프를 커버하는 것과 달리,
이 파일은 tool_call 단건 핸들러를 ``TurnContext`` 만 직접 만들어 격리 검증한다.
구조 리팩토링(call_handlers 추출)으로 핸들러가 독립 함수가 되어 가능해진 테스트.
디스패치 핸들러(call_sub_agent[s_parallel])는 provider·서브에이전트 실행이 필요해
통합 테스트(test_harness_subagent / _parallel)에 위임하고, 여기서는 라우팅만 본다.
"""

import sys
from pathlib import Path
from typing import Annotated

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.harness.call_handlers import (  # noqa: E402
    CallOutcome,
    TurnContext,
    _activate_skills_in_context,
    _emit_post_tool_todo_events,
    _guard_tool_args,
    _handle_activate_skill,
    _handle_add_todo_call,
    _handle_ask_user,
    _handle_complete_subagent,
    _handle_complete_todo_call,
    _handle_malformed_args,
    _handle_normal_tool,
    _handle_sub_agent_dispatch,
    _loop_guard_denial,
    _select_sentinel_handler,
)
from agent.harness.state.loop_guard import _LOOP_GUARD_MESSAGE  # noqa: E402
from agent.harness.state.pending import (  # noqa: E402
    clear_all_pending,
    clear_pending_tool,
)
from agent.harness.state.todo import _mark_running_todo_done  # noqa: E402
from agent.models import (  # noqa: E402
    MALFORMED_TOOL_ARGS_KEY,
    AgentState,
    AskUserEvent,
    Message,
    SkillActiveEvent,
    SkillCompleteEvent,
    TodoItem,
    TodoStatus,
    ToolCall,
    ToolResultEvent,
    TodoUpdateEvent,
)
from agent.registries.skills import Skill, SkillMeta  # noqa: E402
from agent.tools.artifact_io import LIST_ARTIFACTS  # noqa: E402
from agent.tools.runtime import DESCRIBE_VARIABLE, LIST_NAMESPACE  # noqa: E402
from agent.registries.tools import (  # noqa: E402
    ACTIVATE_SKILL,
    ASK_USER,
    COMPLETE_SUB_AGENT,
    PLANNER_ADD_TODO,
    PLANNER_COMPLETE_TODO,
    SUB_AGENT_DISPATCH,
    ToolRegistry,
    _reset_registry_for_tests,
    register_tool,
)
from tests._runner import run_tests  # noqa: E402


# ---------------------------------------------------------------------------
# 테스트 픽스처
# ---------------------------------------------------------------------------


class _FakeSkillRegistry:
    """get_by_names 만 구현한 경량 SkillRegistry 대역 (디스크 SKILLS 불필요)."""

    def __init__(self, skills: list[Skill]) -> None:
        self._by_name = {s.meta.name: s for s in skills}

    def get_by_names(self, names: list[str]) -> list[Skill]:
        return [self._by_name[n] for n in names if n in self._by_name]


def _skill(name: str) -> Skill:
    return Skill(meta=SkillMeta(name=name), source_path=f"/fake/{name}.md")


# "인자 미전달" 과 "명시적 None" 을 구분하기 위한 sentinel — turn_messages=None 은
# 서브 에이전트 컨텍스트를 뜻하므로 기본값(오케스트레이터)과 분리해야 한다.
_UNSET = object()


def _make_ctx(
    *,
    registry: ToolRegistry | None = None,
    state: AgentState | None = None,
    active_skills: list[Skill] | None = None,
    skill_registry: object | None = None,
    recompose: object | None = None,
    turn_messages: object = _UNSET,
    agent_registry: object | None = None,
    messages: list[Message] | None = None,
) -> TurnContext:
    """단건 핸들러 테스트용 최소 TurnContext.

    turn_messages 미전달 시 빈 리스트(=오케스트레이터 컨텍스트). ``None`` 을 명시하면
    서브 에이전트 컨텍스트(is_sub_agent=True)가 된다.
    """
    return TurnContext(
        agent_id="orchestrator",
        provider=object(),  # 이 파일의 핸들러는 provider 를 호출하지 않음
        registry=registry,  # type: ignore[arg-type]
        agent_registry=agent_registry,  # type: ignore[arg-type]
        prompt_registry=None,  # type: ignore[arg-type]
        skill_registry=skill_registry,  # type: ignore[arg-type]
        budget=None,  # type: ignore[arg-type]
        depth=0,
        max_iterations=12,
        state=state,
        active_skills=active_skills,
        recompose_system=recompose,  # type: ignore[arg-type]
        messages=messages
        if messages is not None
        else [Message(role="system", content="sys")],
        turn_messages=[] if turn_messages is _UNSET else turn_messages,  # type: ignore[arg-type]
        history_calls=set(),
    )


async def _collect(agen) -> list:
    return [ev async for ev in agen]


def _setup_registry() -> ToolRegistry:
    _reset_registry_for_tests()
    return ToolRegistry()


def _only_tool_result(events: list) -> ToolResultEvent:
    matches = [e for e in events if isinstance(e, ToolResultEvent)]
    assert len(matches) == 1, f"expected exactly one ToolResultEvent, got {events}"
    return matches[0]


# ---------------------------------------------------------------------------
# 1단계 — malformed args (F3)
# ---------------------------------------------------------------------------


async def test_malformed_args_yields_error_and_appends() -> None:
    ctx = _make_ctx()
    call = ToolCall(id="c1", name="foo", arguments={MALFORMED_TOOL_ARGS_KEY: '{"x'})
    events = await _collect(_handle_malformed_args(ctx, call, CallOutcome()))
    tr = _only_tool_result(events)
    assert tr.is_error is True
    assert any(m.role == "tool" for m in ctx.messages)


# ---------------------------------------------------------------------------
# _guard_tool_args — 통과 / 형식오류 / 슬롯누락
# ---------------------------------------------------------------------------


async def test_guard_passes_returns_none() -> None:
    reg = _setup_registry()

    @register_tool(description="echo")
    async def echo(msg: Annotated[str, "본문"], count: Annotated[int, "수"]) -> str:
        return f"{msg}:{count}"

    ctx = _make_ctx(registry=reg)
    call = ToolCall(id="c", name="echo", arguments={"msg": "hi", "count": 2})
    outcome = CallOutcome()
    assert _guard_tool_args(ctx, call, outcome) is None
    assert outcome.interrupted is False


async def test_guard_invalid_type_returns_error_no_interrupt() -> None:
    reg = _setup_registry()

    @register_tool(description="echo")
    async def echo(msg: Annotated[str, "본문"], count: Annotated[int, "수"]) -> str:
        return f"{msg}:{count}"

    ctx = _make_ctx(registry=reg)
    call = ToolCall(id="c", name="echo", arguments={"msg": "hi", "count": "abc"})
    outcome = CallOutcome()
    denial = _guard_tool_args(ctx, call, outcome)
    assert denial is not None
    assert denial[0].is_error is True
    # 형식 오류는 LLM self-correct 경로 — 사용자에게 묻지 않음(중단 없음).
    assert outcome.interrupted is False


async def test_guard_missing_slot_interrupts_with_ask() -> None:
    reg = _setup_registry()

    @register_tool(description="echo")
    async def echo(msg: Annotated[str, "본문"], count: Annotated[int, "수"]) -> str:
        return f"{msg}:{count}"

    ctx = _make_ctx(registry=reg, state=AgentState())
    call = ToolCall(id="c", name="echo", arguments={})
    outcome = CallOutcome()
    denial = _guard_tool_args(ctx, call, outcome)
    assert denial is not None
    assert isinstance(denial[0], AskUserEvent)
    assert outcome.interrupted is True
    assert ctx.state.pending_tool == "echo"


# ---------------------------------------------------------------------------
# _select_sentinel_handler — 라우팅 + 컨텍스트 가드
# ---------------------------------------------------------------------------


def test_select_sentinel_routing() -> None:
    # ask_user 는 항상 라우팅 (조건 lambda:True).
    ctx = _make_ctx()
    assert (
        _select_sentinel_handler(ctx, ToolCall(id="1", name=ASK_USER, arguments={}))
        is _handle_ask_user
    )
    # add_todo 는 state 가 있어야 라우팅.
    no_state = _make_ctx(state=None)
    assert (
        _select_sentinel_handler(
            no_state, ToolCall(id="1", name=PLANNER_ADD_TODO, arguments={})
        )
        is None
    )
    with_state = _make_ctx(state=AgentState())
    assert (
        _select_sentinel_handler(
            with_state, ToolCall(id="1", name=PLANNER_ADD_TODO, arguments={})
        )
        is _handle_add_todo_call
    )
    # complete_subagent 는 서브 에이전트 컨텍스트(turn_messages=None)에서만.
    sub = _make_ctx(turn_messages=None)
    assert (
        _select_sentinel_handler(
            sub, ToolCall(id="1", name=COMPLETE_SUB_AGENT, arguments={})
        )
        is _handle_complete_subagent
    )
    orch = _make_ctx()
    assert (
        _select_sentinel_handler(
            orch, ToolCall(id="1", name=COMPLETE_SUB_AGENT, arguments={})
        )
        is None
    )
    # call_sub_agent 는 agent_registry 가 있어야.
    assert (
        _select_sentinel_handler(
            _make_ctx(agent_registry=None),
            ToolCall(id="1", name=SUB_AGENT_DISPATCH, arguments={}),
        )
        is None
    )
    assert (
        _select_sentinel_handler(
            _make_ctx(agent_registry=object()),
            ToolCall(id="1", name=SUB_AGENT_DISPATCH, arguments={}),
        )
        is _handle_sub_agent_dispatch
    )
    # 일반 도구는 sentinel 이 아님 → None (일반 경로 폴백).
    assert (
        _select_sentinel_handler(ctx, ToolCall(id="1", name="echo", arguments={}))
        is None
    )


# ---------------------------------------------------------------------------
# activate_skill
# ---------------------------------------------------------------------------


def test_activate_skills_in_context_idempotent() -> None:
    sk = _skill("report")
    ctx = _make_ctx(active_skills=[], skill_registry=_FakeSkillRegistry([sk]))
    assert [s.meta.name for s in _activate_skills_in_context(ctx, "report")] == [
        "report"
    ]
    # 이미 활성화됨 → 빈 리스트, 중복 추가 없음.
    assert _activate_skills_in_context(ctx, "report") == []
    assert [s.meta.name for s in ctx.active_skills] == ["report"]
    # 카탈로그에 없는 이름 → 빈 리스트.
    assert _activate_skills_in_context(ctx, "nope") == []


async def test_activate_skill_newly_recomposes_prompt() -> None:
    sk = _skill("report")
    recompose_args: list[list[str]] = []

    def recompose(skills: list[Skill]) -> str:
        recompose_args.append([s.meta.name for s in skills])
        return "recomposed-system"

    ctx = _make_ctx(
        active_skills=[],
        skill_registry=_FakeSkillRegistry([sk]),
        recompose=recompose,
        state=AgentState(),
    )
    call = ToolCall(id="c", name=ACTIVATE_SKILL, arguments={"name": "report"})
    events = await _collect(_handle_activate_skill(ctx, call, CallOutcome()))
    assert any(isinstance(e, SkillActiveEvent) for e in events)
    assert _only_tool_result(events).is_error is False
    assert ctx.messages[0].content == "recomposed-system"
    assert recompose_args == [["report"]]
    assert ctx.state.active_skills == ["report"]


async def test_activate_skill_already_active_is_error() -> None:
    sk = _skill("report")
    ctx = _make_ctx(
        active_skills=[sk],
        skill_registry=_FakeSkillRegistry([sk]),
        recompose=lambda s: "should-not-be-used",
        state=AgentState(),
    )
    call = ToolCall(id="c", name=ACTIVATE_SKILL, arguments={"name": "report"})
    events = await _collect(_handle_activate_skill(ctx, call, CallOutcome()))
    assert not any(isinstance(e, SkillActiveEvent) for e in events)
    # 이미 활성/미존재 → newly_activated 비어 is_error=True, prompt 미변경.
    assert _only_tool_result(events).is_error is True
    assert ctx.messages[0].content == "sys"


# ---------------------------------------------------------------------------
# complete_subagent — STOP 신호
# ---------------------------------------------------------------------------


async def test_complete_subagent_sets_stop() -> None:
    ctx = _make_ctx(turn_messages=None)  # 서브 에이전트 컨텍스트
    outcome = CallOutcome()
    call = ToolCall(id="c", name=COMPLETE_SUB_AGENT, arguments={"summary": "끝"})
    events = await _collect(_handle_complete_subagent(ctx, call, outcome))
    assert outcome.stop is True
    assert _only_tool_result(events).result == "끝"


# ---------------------------------------------------------------------------
# add_todo / complete_todo
# ---------------------------------------------------------------------------


async def test_add_todo_appends_and_emits_update() -> None:
    ctx = _make_ctx(state=AgentState())
    call = ToolCall(
        id="c", name=PLANNER_ADD_TODO, arguments={"items": [{"description": "step1"}]}
    )
    events = await _collect(_handle_add_todo_call(ctx, call, CallOutcome()))
    assert any(isinstance(e, TodoUpdateEvent) for e in events)
    assert len(ctx.state.todo_list) == 1


async def test_complete_todo_all_terminal_emits_skill_complete() -> None:
    ctx = _make_ctx(state=AgentState())
    add_call = ToolCall(
        id="a", name=PLANNER_ADD_TODO, arguments={"items": [{"description": "s"}]}
    )
    await _collect(_handle_add_todo_call(ctx, add_call, CallOutcome()))
    task_id = ctx.state.todo_list[0].task_id
    done_call = ToolCall(
        id="b", name=PLANNER_COMPLETE_TODO, arguments={"task_id": task_id}
    )
    events = await _collect(_handle_complete_todo_call(ctx, done_call, CallOutcome()))
    assert any(isinstance(e, TodoUpdateEvent) for e in events)
    # 전원 terminal → 완료 통계 이벤트.
    assert any(isinstance(e, SkillCompleteEvent) for e in events)


# ---------------------------------------------------------------------------
# ask_user — 옵션 정규화 + INTERRUPT
# ---------------------------------------------------------------------------


async def test_ask_user_empty_options_normalizes_to_text() -> None:
    ctx = _make_ctx(state=AgentState())
    outcome = CallOutcome()
    call = ToolCall(
        id="c", name=ASK_USER, arguments={"question": "어느 것?", "options": []}
    )
    events = await _collect(_handle_ask_user(ctx, call, outcome))
    ask = [e for e in events if isinstance(e, AskUserEvent)][0]
    assert ask.options is None
    assert ask.input_type == "text"
    assert outcome.interrupted is True
    assert ctx.state.pending_question == "어느 것?"


async def test_ask_user_with_options_keeps_choice() -> None:
    ctx = _make_ctx(state=AgentState())
    call = ToolCall(
        id="c",
        name=ASK_USER,
        arguments={"question": "골라", "options": ["A", "B"], "input_type": "choice"},
    )
    events = await _collect(_handle_ask_user(ctx, call, CallOutcome()))
    ask = [e for e in events if isinstance(e, AskUserEvent)][0]
    assert ask.options == ["A", "B"]
    assert ask.input_type == "choice"
    # 기본 단일 선택 — multi_select 미지정 시 False.
    assert ask.multi_select is False


async def test_ask_user_multi_select_with_options() -> None:
    ctx = _make_ctx(state=AgentState())
    call = ToolCall(
        id="c",
        name=ASK_USER,
        arguments={
            "question": "모두 골라",
            "options": ["A", "B", "C"],
            "input_type": "both",
            "multi_select": True,
        },
    )
    events = await _collect(_handle_ask_user(ctx, call, CallOutcome()))
    ask = [e for e in events if isinstance(e, AskUserEvent)][0]
    assert ask.options == ["A", "B", "C"]
    assert ask.multi_select is True


async def test_ask_user_multi_select_without_options_forced_false() -> None:
    # 옵션이 없으면 다중 선택 대상이 없으므로 multi_select 는 False 로 강제된다.
    ctx = _make_ctx(state=AgentState())
    call = ToolCall(
        id="c",
        name=ASK_USER,
        arguments={"question": "자유 입력?", "options": [], "multi_select": True},
    )
    events = await _collect(_handle_ask_user(ctx, call, CallOutcome()))
    ask = [e for e in events if isinstance(e, AskUserEvent)][0]
    assert ask.options is None
    assert ask.input_type == "text"
    assert ask.multi_select is False


# ---------------------------------------------------------------------------
# 일반 도구 실행 + 루프 가드
# ---------------------------------------------------------------------------


async def test_normal_tool_executes_and_returns_result() -> None:
    reg = _setup_registry()

    @register_tool(description="echo")
    async def echo(msg: Annotated[str, "본문"]) -> str:
        return f"e:{msg}"

    ctx = _make_ctx(registry=reg, state=AgentState())
    call = ToolCall(id="c", name="echo", arguments={"msg": "hi"})
    events = await _collect(_handle_normal_tool(ctx, call, CallOutcome()))
    tr = _only_tool_result(events)
    assert tr.result == "e:hi"
    assert tr.is_error is False


async def test_normal_tool_loop_guard_blocks_identical_repeat() -> None:
    reg = _setup_registry()

    @register_tool(description="echo")
    async def echo(msg: Annotated[str, "본문"]) -> str:
        return f"e:{msg}"

    ctx = _make_ctx(registry=reg, state=AgentState())
    first = ToolCall(id="c1", name="echo", arguments={"msg": "hi"})
    await _collect(_handle_normal_tool(ctx, first, CallOutcome()))
    # 동일 시그니처(name+args) 재호출 → 루프 가드 차단.
    second = ToolCall(id="c2", name="echo", arguments={"msg": "hi"})
    events = await _collect(_handle_normal_tool(ctx, second, CallOutcome()))
    tr = _only_tool_result(events)
    assert tr.is_error is True
    assert tr.result == _LOOP_GUARD_MESSAGE


def test_loop_guard_denial_records_then_blocks() -> None:
    ctx = _make_ctx(state=AgentState())
    call = ToolCall(id="c", name="echo", arguments={"msg": "hi"})
    assert _loop_guard_denial(ctx, call) is None  # 첫 호출 — 기록 후 통과
    denial = _loop_guard_denial(ctx, call)  # 동일 재호출 — 차단
    assert denial is not None
    assert denial[0].is_error is True


def test_loop_guard_exempts_ambient_read_tools() -> None:
    # list_artifacts/list_namespace/describe_variable 는 가변 세션 상태(산출물 집합·
    # namespace)를 읽으므로, 동일 호출 반복이라도 루프로 차단하지 않는다 — 상태 변경
    # 후 재조회가 정당한 행동이기 때문 (A-1).
    for name in (LIST_ARTIFACTS, LIST_NAMESPACE, DESCRIBE_VARIABLE):
        ctx = _make_ctx(state=AgentState())
        call = ToolCall(id="c", name=name, arguments={})
        assert _loop_guard_denial(ctx, call) is None
        assert _loop_guard_denial(ctx, call) is None  # 재호출도 면제(차단 안 함)


async def test_post_tool_events_clear_matching_pending() -> None:
    state = AgentState(
        pending_tool="echo", pending_args={"x": 1}, missing_slots={"y": "?"}
    )
    ctx = _make_ctx(state=state)
    call = ToolCall(id="c", name="echo", arguments={})
    await _collect(_emit_post_tool_todo_events(ctx, call, "ok", is_error=False))
    assert state.pending_tool is None
    assert state.pending_args == {}
    assert state.missing_slots == {}


async def test_post_tool_events_noop_without_state() -> None:
    ctx = _make_ctx(state=None)
    call = ToolCall(id="c", name="echo", arguments={})
    # state 없으면 todo 이벤트도 없음 (서브 에이전트 등).
    events = await _collect(
        _emit_post_tool_todo_events(ctx, call, "ok", is_error=False)
    )
    assert events == []


# ---------------------------------------------------------------------------
# todo 자동완료 — 단일 일치일 때만 (C-2)
# ---------------------------------------------------------------------------


def test_mark_running_todo_skips_when_ambiguous() -> None:
    # 같은 tool_name 을 쓰는 비-terminal todo 가 둘이면 어느 단계인지 모호하므로
    # 자동완료를 건너뛰고 명시 complete_todo 에 위임한다.
    state = AgentState()
    state.todo_list = [
        TodoItem(
            task_id="t1",
            description="저장 1",
            tool_name="save_artifact",
            status=TodoStatus.PENDING,
        ),
        TodoItem(
            task_id="t2",
            description="저장 2",
            tool_name="save_artifact",
            status=TodoStatus.PENDING,
        ),
    ]
    assert _mark_running_todo_done(state, "save_artifact", "ok") is False
    assert all(t.status == TodoStatus.PENDING for t in state.todo_list)


def test_mark_running_todo_closes_single_match() -> None:
    # 일치가 정확히 하나면 그 단계만 닫는다(흔한 경우 — 기존 동작 유지).
    state = AgentState()
    state.todo_list = [
        TodoItem(
            task_id="t1",
            description="저장",
            tool_name="save_artifact",
            status=TodoStatus.PENDING,
        ),
        TodoItem(
            task_id="t2",
            description="차트",
            tool_name="display_chart",
            status=TodoStatus.PENDING,
        ),
    ]
    assert _mark_running_todo_done(state, "save_artifact", "done") is True
    assert state.todo_list[0].status == TodoStatus.COMPLETED
    assert state.todo_list[1].status == TodoStatus.PENDING


# ---------------------------------------------------------------------------
# pending 클리어 헬퍼 (state/pending.py)
# ---------------------------------------------------------------------------


def test_clear_pending_tool_leaves_sub_agent_fields() -> None:
    s = AgentState(
        pending_tool="x",
        pending_args={"a": 1},
        missing_slots={"k": "?"},
        pending_sub_agent="sa",
        pending_sub_task="t",
    )
    clear_pending_tool(s)
    assert s.pending_tool is None
    assert s.pending_args == {}
    assert s.missing_slots == {}
    # sub-agent 재위임 잔재는 보존.
    assert s.pending_sub_agent == "sa"
    assert s.pending_sub_task == "t"


def test_clear_all_pending_clears_everything() -> None:
    s = AgentState(
        pending_tool="x",
        pending_args={"a": 1},
        missing_slots={"k": "?"},
        pending_sub_agent="sa",
        pending_sub_task="t",
    )
    clear_all_pending(s)
    assert s.pending_tool is None
    assert s.pending_args == {}
    assert s.missing_slots == {}
    assert s.pending_sub_agent is None
    assert s.pending_sub_task is None


if __name__ == "__main__":
    run_tests(globals())
