"""Planner sentinel 도구 — harness 가 tool_call 분기에서 가로채 직접 처리한다.

`run()` body 는 실행되지 않는다. spec 만 LLM 에게 노출되며, harness 의
`PLANNER_ADD_TODO` / `PLANNER_COMPLETE_TODO` 분기가 AgentState 갱신을 담당한다.
"""

from typing import Annotated, Any

from agent.registries.tools import (
    PLANNER_ADD_TODO,
    PLANNER_COMPLETE_TODO,
    register_tool,
)


@register_tool(
    name=PLANNER_ADD_TODO,
    description=(
        "작업을 단계별로 분해해 todo 체크리스트에 추가한다. "
        "When to use: 도구를 2회 이상 호출해야 하거나 도메인이 다른 작업이 섞여 있을 때, "
        "또는 멀티 스킬이 동시 활성화됐을 때 반드시 먼저 호출한다. "
        "When NOT to use: 단일 도구 1회로 끝나는 단순 질의(예: '지금 몇 시야?'). "
        "Expected chaining: add_todo → 각 step 도구 실행 → 각 단계 완료 즉시 complete_todo. "
        "각 item 은 description(필수)과 tool_name(선택, 사용할 도구 힌트)을 가진다. "
        "호출 즉시 todo_list 에 PENDING 상태로 추가되며 사용자 UI 에도 표시된다."
    ),
    slot_prompts={"items": "어떤 단계들로 작업을 분해하면 좋을까요?"},
    sentinel=True,
)
async def add_todo(
    items: Annotated[
        list[dict[str, Any]],
        "추가할 sub-task 목록. 각 항목: description(필수), tool_name(선택)",
    ],
) -> str:
    raise RuntimeError("sentinel tool — handled by harness, never executed")


@register_tool(
    name=PLANNER_COMPLETE_TODO,
    description=(
        "todo_list 의 한 단계를 처리 완료 표시한다. "
        "When to use: add_todo 로 등록한 step 의 실제 작업(도구 호출·분석)이 끝나는 즉시. "
        "여러 단계를 한 번에 묶어 표시하지 말고 step 마다 곧바로 호출한다. "
        "When NOT to use: add_todo 가 등록되지 않은 task_id 호출(매칭 실패), "
        "또는 아직 작업이 끝나지 않은 step 을 미리 표시하는 행위. "
        "도구 실행이 실패했거나 단계를 건너뛸 때는 status 를 'failed' 또는 'skipped' 로 지정한다. "
        "task_id 는 add_todo 또는 직전 todo_update 이벤트에서 얻은 식별자를 사용한다."
    ),
    slot_prompts={"task_id": "어느 단계를 완료 처리하시겠습니까?"},
    sentinel=True,
)
async def complete_todo(
    task_id: Annotated[str, "완료 처리할 단계의 id"],
    summary: Annotated[str, "완료 결과 요약 (한국어 한 줄)"] = "",
    status: Annotated[
        str, "completed | failed | skipped (기본값: completed)"
    ] = "completed",
) -> str:
    raise RuntimeError("sentinel tool — handled by harness, never executed")
