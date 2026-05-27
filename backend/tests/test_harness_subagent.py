"""Sub-agent 고도화 검증.

#10 complete_subagent sentinel 등록
#11 max_iterations -> ErrorEvent
#8  sub-agent PLANNER tools (TodoUpdateEvent)
#9  sub-agent AskUserEvent -> orchestrator pending_sub_agent
"""

import asyncio
import sys
from pathlib import Path
from typing import Annotated, Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.models import (  # noqa: E402
    AgentState,
    ErrorEvent,
    StreamEvent,
)
from agent.registries.tools import (  # noqa: E402
    COMPLETE_SUB_AGENT,
    _reset_registry_for_tests,
    get_registered_tool,
    register_tool,
)
from tests._runner import run_tests  # noqa: E402


def _reload_all_tool_modules() -> None:
    """Tool 모듈 전부를 reload 해 @register_tool 데코레이터를 재실행한다.

    test_guard_pydantic·test_tools_decorator 등이 호출한 _reset_registry_for_tests 로
    빈 상태가 된 registry 를 복구한다. 단순 ``import agent.tools`` 는 sys.modules
    캐시 때문에 데코레이터가 다시 돌지 않으므로 명시적 reload 가 필요하다.
    """
    import importlib

    import agent.tools.artifact
    import agent.tools.builtin
    import agent.tools.clarify
    import agent.tools.demo
    import agent.tools.dispatch
    import agent.tools.planner
    import agent.tools.visualize

    for mod in (
        agent.tools.builtin,
        agent.tools.clarify,
        agent.tools.dispatch,
        agent.tools.planner,
        agent.tools.visualize,
        agent.tools.demo,
        agent.tools.artifact,
    ):
        importlib.reload(mod)


# ---------------------------------------------------------------------------
# #10 — complete_subagent sentinel 등록 확인
# ---------------------------------------------------------------------------


def test_complete_subagent_is_registered() -> None:
    """상수와 도구 이름이 일치해야 한다 — registry 가 비어 있어도 강건하게 복구."""
    _reload_all_tool_modules()

    tool = get_registered_tool(COMPLETE_SUB_AGENT)
    assert tool is not None, "complete_subagent 가 등록되지 않음"
    assert tool.sentinel is True
    assert tool.name == "complete_subagent"


def test_complete_subagent_has_summary_param() -> None:
    _reload_all_tool_modules()

    tool = get_registered_tool(COMPLETE_SUB_AGENT)
    assert tool is not None
    assert "summary" in tool.required, "summary 가 required 파라미터여야 함"


# ---------------------------------------------------------------------------
# #11 — max_iterations 소진 시 ErrorEvent yield
# ---------------------------------------------------------------------------


def _collect_events(coro: Any) -> list[StreamEvent]:
    async def _run() -> list[StreamEvent]:
        return [ev async for ev in coro]

    return asyncio.run(_run())


def test_max_iterations_yields_error_event() -> None:
    """매 iteration 마다 tool_call 을 반환하는 mock provider 로 상한 도달 검증."""
    _reset_registry_for_tests()

    @register_tool(description="무한 반복 도구", timeout_seconds=5)
    async def noop_tool(x: Annotated[str, "입력"]) -> str:
        return "done"

    from agent.harness import _run_agent_turn
    from agent.models import (
        Message,
        ToolCall,
        ToolCallEvent,
        ToolSpec,
    )
    from agent.registries.tools import ToolRegistry

    class _InfiniteProvider:
        """매 astream 호출마다 tool_call → done 을 반환."""

        async def astream(self, messages, tools):  # noqa: ANN001
            yield ToolCallEvent(
                call=ToolCall(id="tc1", name="noop_tool", arguments={"x": "hi"})
            )
            from agent.models import DoneEvent as DE

            yield DE()

    registry = ToolRegistry()
    specs = [
        ToolSpec(
            name="noop_tool",
            description="test",
            parameters={"type": "object", "properties": {}, "required": []},
        )
    ]

    async def _run():
        events = []
        async for ev in _run_agent_turn(
            agent_id="test_agent",
            messages=[Message(role="user", content="go")],
            turn_messages=[],
            provider=_InfiniteProvider(),
            registry=registry,
            sub_specs=specs,
            agent_registry=None,
            prompt_registry=None,
            skill_registry=None,
            budget=__import__("agent.harness", fromlist=["TurnBudget"]).TurnBudget(
                max_calls=20
            ),
            depth=0,
            state=AgentState(),
            max_iterations=2,
        ):
            events.append(ev)
        return events

    events = asyncio.run(_run())
    error_events = [e for e in events if isinstance(e, ErrorEvent)]
    assert error_events, "max_iterations 소진 시 ErrorEvent 가 없음"
    assert (
        "max_iterations" in error_events[0].message.lower()
        or "반복 상한" in error_events[0].message
    )


# ---------------------------------------------------------------------------
# #9 — pending_sub_agent 필드가 AgentState 에 존재
# ---------------------------------------------------------------------------


def test_agent_state_has_pending_sub_agent_fields() -> None:
    state = AgentState()
    assert hasattr(state, "pending_sub_agent")
    assert hasattr(state, "pending_sub_task")
    assert state.pending_sub_agent is None
    assert state.pending_sub_task is None


def test_agent_state_pending_sub_agent_serializes() -> None:
    state = AgentState(pending_sub_agent="data_agent", pending_sub_task="fetch sales")
    dumped = state.model_dump()
    restored = AgentState.model_validate(dumped)
    assert restored.pending_sub_agent == "data_agent"
    assert restored.pending_sub_task == "fetch sales"


def test_agent_state_backward_compat_old_json() -> None:
    """기존 JSON 에 pending_sub_agent 필드가 없어도 model_validate 통과."""
    old_json = {
        "todo_list": [],
        "missing_slots": {},
        "pending_tool": None,
        "pending_args": {},
    }
    state = AgentState.model_validate(old_json)
    assert state.pending_sub_agent is None
    assert state.pending_sub_task is None


# ---------------------------------------------------------------------------
# #8 — sub_state(AgentState) 주입 확인 — PLANNER 도구 분기 동작
# ---------------------------------------------------------------------------


def test_filter_specs_excludes_only_sub_agent_dispatch() -> None:
    """_filter_specs_for_sub_agent 가 SUB_AGENT_DISPATCH 만 제거하는지 확인."""
    _reload_all_tool_modules()

    from agent.harness import _filter_specs_for_sub_agent
    from agent.registries.agents import Agent, AgentMeta
    from agent.registries.tools import (
        PLANNER_ADD_TODO,
        PLANNER_COMPLETE_TODO,
        SUB_AGENT_DISPATCH,
        ToolRegistry,
    )

    registry = ToolRegistry()
    all_specs = registry.specs()

    agent = Agent(
        meta=AgentMeta(name="test", description="test", skills=[], tools=[]),
        source_path="test.md",
        body="",
    )
    filtered = _filter_specs_for_sub_agent(all_specs, agent)
    filtered_names = {s.name for s in filtered}

    assert SUB_AGENT_DISPATCH not in filtered_names, (
        "SUB_AGENT_DISPATCH 는 서브 에이전트에서 제외해야 함"
    )
    assert PLANNER_ADD_TODO in filtered_names, (
        "add_todo 는 서브 에이전트에서 사용 가능해야 함"
    )
    assert PLANNER_COMPLETE_TODO in filtered_names, (
        "complete_todo 는 서브 에이전트에서 사용 가능해야 함"
    )
    assert COMPLETE_SUB_AGENT in filtered_names, (
        "complete_subagent 는 서브 에이전트에서 사용 가능해야 함"
    )


if __name__ == "__main__":
    run_tests(globals())
