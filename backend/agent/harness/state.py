"""Harness 의 AgentState 변형·히스토리 정합성·루프 가드 헬퍼.

``harness.run_turn`` / ``_run_agent_turn`` 이 사용하는, turn 실행 루프와 분리 가능한
상태 조작 유틸리티를 한곳에 모은다. 세 가지 책임:

1. **Planner 도구 핸들러** — add_todo / complete_todo 등 sentinel 도구를 받아
   ``AgentState.todo_list`` 를 직접 갱신한다.
2. **대화 히스토리 정합성** — OpenAI 와이어 규약(모든 tool_call 은 매칭 tool 응답
   필요)을 깨지 않도록 미해결 tool_call 에 placeholder 응답을 채운다 (F1b·R1).
3. **루프 가드 시그니처** — 동일 호출 반복을 감지하기 위한 호출 시그니처를 계산한다
   (R4). 인자뿐 아니라 참조하는 ``result/...`` 파일의 fingerprint 까지 포함한다.

> 하위호환: harness.py 가 이 모듈의 심볼을 re-export 하므로 기존
> ``from agent.harness import _balance_unresolved_tool_calls`` 류 import 은 그대로 동작한다.
"""

import json
import uuid
from typing import Any

from agent.models import (
    AgentState,
    Message,
    SkillCompleteEvent,
    TodoItem,
    TodoStatus,
    ToolCall,
)
from core.result_store import resolve_result_path

# todo 가 더 이상 진행되지 않는 최종 상태.
_TERMINAL_STATUSES: frozenset[TodoStatus] = frozenset(
    {TodoStatus.COMPLETED, TodoStatus.FAILED, TodoStatus.SKIPPED}
)


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


# ---------------------------------------------------------------------------
# 대화 히스토리 정합성 — 미해결 tool_call placeholder 채우기
# ---------------------------------------------------------------------------


def _balance_unresolved_tool_calls(
    messages: list[Message],
    turn_messages: list[Message] | None,
    assistant_msg: Message,
) -> None:
    """중단으로 처리되지 못한 tool_call 에 placeholder tool 응답을 채운다.

    OpenAI 와이어 규약상 assistant 의 모든 tool_call 은 매칭되는 tool 메시지가
    있어야 한다. 배치 도구 호출 도중 AskUser 등으로 턴이 끊기면 뒤따르는 호출이
    응답 없이 남아, 이 메시지가 히스토리에 영속되면 다음 턴 요청이 400 으로
    거부된다. 미해결 tool_call 마다 placeholder 응답을 추가해 쌍을 맞춘다.

    Args:
        messages: LLM 컨텍스트 (in-place 보정).
        turn_messages: 영속화 버퍼. 서브 에이전트는 None.
        assistant_msg: 이번 iteration 의 assistant 메시지 (tool_calls 보유).
    """
    if not assistant_msg.tool_calls:
        return
    resolved = {m.tool_call_id for m in messages if m.role == "tool" and m.tool_call_id}
    for tc in assistant_msg.tool_calls:
        if tc.id in resolved:
            continue
        placeholder = "[중단됨] 사용자 입력 대기로 이 도구 호출은 실행되지 않았습니다."
        tool_msg = Message(role="tool", content=placeholder, tool_call_id=tc.id)
        messages.append(tool_msg)
        if turn_messages is not None:
            turn_messages.append(tool_msg)


_ERROR_TOOL_PLACEHOLDER = (
    "[중단됨] 턴이 오류로 종료되어 이 도구 호출은 완료되지 않았습니다."
)


def _balance_all_unresolved(turn_messages: list[Message]) -> None:
    """버퍼 전체를 스캔해 모든 미해결 tool_call 에 placeholder 응답을 채운다.

    run_turn 최상위 예외 경로 전용. `_balance_unresolved_tool_calls` 와 달리 예외
    시점의 in-flight assistant_msg 를 특정할 수 없으므로 전수 검사한다. placeholder
    는 끝에 append 하지 않고 해당 assistant 의 tool 응답 블록 바로 뒤에 삽입한다 —
    OpenAI 와이어 규약상 tool 메시지는 자신의 assistant 메시지에 인접해야 한다.

    Args:
        turn_messages: 영속화 직전의 턴 버퍼 (in-place 보정).
    """
    i = 0
    while i < len(turn_messages):
        msg = turn_messages[i]
        if msg.role != "assistant" or not msg.tool_calls:
            i += 1
            continue
        # 이 assistant 에 인접한 tool 응답 블록의 끝(j)과 해결된 id 집합을 수집.
        j = i + 1
        resolved: set[str] = set()
        while j < len(turn_messages) and turn_messages[j].role == "tool":
            if turn_messages[j].tool_call_id:
                resolved.add(turn_messages[j].tool_call_id)
            j += 1
        for tc in msg.tool_calls:
            if tc.id in resolved:
                continue
            turn_messages.insert(
                j,
                Message(
                    role="tool",
                    content=_ERROR_TOOL_PLACEHOLDER,
                    tool_call_id=tc.id,
                ),
            )
            j += 1
        i = j


# ---------------------------------------------------------------------------
# 루프 가드 — 호출 시그니처 (name + args + 참조 파일 fingerprint)
# ---------------------------------------------------------------------------


def _collect_result_path_fingerprints(value: Any, parts: list[str]) -> None:
    """인자 트리에서 'result/...' 경로 문자열을 찾아 파일 fingerprint 를 수집한다.

    Args:
        value: tool_call 인자 트리의 한 노드 (str/dict/list/스칼라).
        parts: 수집된 ``경로:mtime_ns:size`` 문자열이 append 되는 출력 버퍼.
    """
    if isinstance(value, str):
        if value.strip().replace("\\", "/").startswith("result/"):
            target, error = resolve_result_path(value)
            if error is None and target is not None:
                try:
                    stat = target.stat()
                except OSError:
                    return
                parts.append(f"{value}:{stat.st_mtime_ns}:{stat.st_size}")
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_result_path_fingerprints(item, parts)
        return
    if isinstance(value, list):
        for item in value:
            _collect_result_path_fingerprints(item, parts)


def _call_signature(call: ToolCall) -> tuple[str, str, str]:
    """루프 가드용 호출 시그니처 — (도구명, 인자 JSON, 참조 파일 fingerprint).

    인자만 비교하면 'spec 파일을 고쳐 쓴 뒤 같은 경로로 재호출'(정당한 재시도)을
    루프로 오인한다. 인자 속 'result/...' 경로가 가리키는 파일의 mtime/size 를
    시그니처에 포함해, 관측 가능한 상태가 그대로인 진짜 반복만 차단한다.
    미존재 경로·일반 문자열은 fingerprint 에 기여하지 않는다.
    """
    args_str = json.dumps(call.arguments, sort_keys=True) if call.arguments else ""
    parts: list[str] = []
    _collect_result_path_fingerprints(call.arguments or {}, parts)
    return (call.name, args_str, "|".join(sorted(parts)))


def _record_invalid_call(
    call: ToolCall, history_calls: set[tuple[str, str, str]]
) -> bool:
    """형식오류 호출 시그니처를 history_calls 에 기록한다.

    같은 시그니처의 형식오류 호출이 반복되면(=self-correct 실패) True 를 반환해
    호출자가 루프 차단 메시지로 전환하도록 한다. 정상 실행 경로의 dedup 과 동일한
    history_calls 집합을 공유하므로 형식오류↔정상 호출 간 루프도 함께 감지된다.

    Returns:
        True: 이미 본 동일 호출(반복). False: 최초 기록.
    """
    sig = _call_signature(call)
    if sig in history_calls:
        return True
    history_calls.add(sig)
    return False
