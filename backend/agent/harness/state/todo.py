"""Planner 도구 핸들러 — harness 가 직접 AgentState.todo_list 를 갱신한다.

add_todo / complete_todo sentinel 도구를 받아 plan(todo) 상태를 변형하고, todo 가
모두 terminal 상태인지 판정하거나 통계 이벤트를 만든다. 구 ``harness/state.py`` 의
Planner 섹션을 그대로 옮겨왔다.
"""

import uuid
from typing import Any

from agent.models import (
    AgentState,
    SkillCompleteEvent,
    TodoItem,
    TodoStatus,
)

# todo 가 더 이상 진행되지 않는 최종 상태.
_TERMINAL_STATUSES: frozenset[TodoStatus] = frozenset(
    {TodoStatus.COMPLETED, TodoStatus.FAILED, TodoStatus.SKIPPED}
)


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

    PENDING/RUNNING 중 tool_name 이 일치하는 항목이 **정확히 하나일 때만** 갱신한다.
    둘 이상이면 어느 단계가 이번 실행에 대응하는지 모호하므로(같은 도구를 쓰는 다단계
    plan) 자동완료를 건너뛰고 명시 ``complete_todo(task_id)`` 신호에 위임한다 —
    엉뚱한 단계를 완료로 라벨링하는 것보다 정확하다.
    is_error=True 면 FAILED, 아니면 COMPLETED 로 전이한다.

    Returns:
        True: todo 가 실제로 갱신된 경우 (호출자가 TodoUpdateEvent 를 yield 해야 함).
        False: 일치 항목이 없거나(0개) 모호한(2개 이상) 경우.
    """
    target_statuses = {TodoStatus.PENDING, TodoStatus.RUNNING}
    matches = [
        item
        for item in state.todo_list
        if item.status in target_statuses and item.tool_name == tool_name
    ]
    if len(matches) != 1:
        return False
    item = matches[0]
    item.status = TodoStatus.FAILED if is_error else TodoStatus.COMPLETED
    item.result_summary = result_text[:120]
    return True


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
