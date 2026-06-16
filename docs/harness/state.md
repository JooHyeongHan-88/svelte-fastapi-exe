# 상태 변형 — `state/`

`AgentState` 를 직접 조작하는 네 모듈. `loop`·`call_handlers` 양쪽에서 공유되므로
단방향 의존으로 분리됐다(`state/` 는 상위 모듈을 import 하지 않음 — 순환 없음).

| 모듈 | 역할 |
|---|---|
| `todo.py` | Planner 핸들러 — `add_todo`/`complete_todo` 처리, terminal 판정, 통계 이벤트 |
| `balancing.py` | 미해결 tool_call 에 placeholder 를 채워 OpenAI 와이어 규약 준수 (F1b·R1) |
| `loop_guard.py` | 호출 시그니처 fingerprint 기반 동일 호출 반복 감지 (R4) |
| `pending.py` | 턴 경계 pending 잔재 클리어 (F11) |

---

## Planner — `todo.py`

`add_todo`/`complete_todo` sentinel 을 받아 `AgentState.todo_list` 를 직접 갱신하고,
`call_handlers` 가 `TodoUpdateEvent`·`SkillCompleteEvent` 를 emit 할 때 사용하는
판정·통계 헬퍼를 제공한다.

### `_TERMINAL_STATUSES`

```python
_TERMINAL_STATUSES: frozenset[TodoStatus] = frozenset(
    {TodoStatus.COMPLETED, TodoStatus.FAILED, TodoStatus.SKIPPED}
)
```

todo 가 더 이상 진행되지 않는 최종 상태 집합. R5(턴 시작 리셋)·F6(fallback is_recovered
판정)·`_all_todos_terminal` 이 공통으로 참조한다. 이 집합 이외의 상수를 각 거처에서
별도로 정의하지 말 것.

### `_handle_add_todo(state, args) → str`

`args["items"]` 를 순회해 `TodoItem(task_id, description, tool_name, status=PENDING)` 를
`state.todo_list` 에 append 한다. `task_id` 는 `uuid4().hex[:8]` 자동 생성. `description`
없는 항목은 silent skip + 스킵 수를 반환 문자열에 포함.

### `_handle_complete_todo(state, args) → str`

`args["task_id"]` 로 첫 일치 항목을 찾아 `status` 를 전이하고 `result_summary` 를
저장. `status` 파라미터는 `completed`/`failed`/`skipped` 허용 — 범위 밖 값은
`COMPLETED` 로 폴백해 LLM 오타에 관대하게 처리.

### `_mark_running_todo_done(state, tool_name, result_text, *, is_error) → bool`

일반 도구 실행 직후 `_emit_post_tool_todo_events` 가 호출한다. PENDING 또는 RUNNING 중
`tool_name` 이 일치하는 **첫 항목**을 `COMPLETED`(is_error=False) 또는 `FAILED`(True)
로 자동 전이하고, `result_text[:120]` 을 `result_summary` 에 저장한다. 일치 항목이
있으면 `True`(호출자가 `TodoUpdateEvent` 를 yield 해야 함), 없으면 `False`.

### `_all_todos_terminal(state) → bool`

`todo_list` 가 비어있지 않고 모든 항목이 `_TERMINAL_STATUSES` 안에 있으면 `True`.
F6 fallback `is_recovered` 판정과 `_emit_post_tool_todo_events` 의
`SkillCompleteEvent` 발화 조건으로 쓰인다.

### `_build_skill_complete_event(state) → SkillCompleteEvent`

`todo_list` 를 순회해 completed/failed/skipped 수를 집계한 `SkillCompleteEvent` 를
만든다. `_all_todos_terminal` 이 True 인 직후에만 호출된다.

---

## 히스토리 정합성 — `balancing.py` (F1b · R1)

OpenAI 와이어 규약상 `assistant` 의 모든 `tool_call` 에는 매칭되는 `role="tool"`
메시지가 인접해 있어야 한다. 배치 도중 AskUser·예외로 턴이 끊기면 뒤따르는 호출이
응답 없이 남아, 이 상태로 영속되면 다음 턴 요청이 **400** 으로 거부된다.

### `_balance_unresolved_tool_calls(messages, turn_messages, assistant_msg)` (F1b)

**중단(AskUser) 경로 전용.** `_run_agent_turn` 의 `if interrupted:` 블록에서 호출된다.

- `messages` 내 기존 `role="tool"` 의 `tool_call_id` 를 resolved set 으로 수집.
- `assistant_msg.tool_calls` 중 resolved 에 없는 것마다 placeholder `role="tool"`
  메시지를 `messages` 와 `turn_messages` 에 append.
- placeholder 내용: `"[중단됨] 사용자 입력 대기로 이 도구 호출은 실행되지 않았습니다."`
- 서브 에이전트(`turn_messages=None`)는 영속 버퍼에는 넣지 않는다.

### `_ERROR_TOOL_PLACEHOLDER`

```python
"[중단됨] 턴이 오류로 종료되어 이 도구 호출은 완료되지 않았습니다."
```

`_balance_all_unresolved` 전용 상수. AskUser 중단과 구분하려고 문구가 다르다.

### `_balance_all_unresolved(turn_messages)` (R1)

**예외 경로(`_persist_failed_turn`) 전용.** 예외 시점에는 in-flight `assistant_msg`
를 특정할 수 없으므로 버퍼 전체를 순회한다.

```
i = 0
while i < len(turn_messages):
    msg = turn_messages[i]
    if not (msg.role == "assistant" and msg.tool_calls):
        i += 1; continue
    # 이 assistant 에 인접한 tool 블록 끝(j)과 resolved ids 수집
    j = i + 1
    while j < len(turn_messages) and turn_messages[j].role == "tool":
        resolved.add(turn_messages[j].tool_call_id)
        j += 1
    # 미해결마다 j 위치에 insert (끝 append 아님 — 인접성 규약 준수)
    for tc in msg.tool_calls 미해결:
        turn_messages.insert(j, placeholder); j += 1
    i = j
```

> **insert vs append** — 미해결 placeholder 를 버퍼 끝에 append 하면 다른 assistant
> 메시지와 tool 메시지 사이에 끼어들어 인접성 규약을 위반한다. 반드시 해당 assistant
> 의 tool 응답 블록 **바로 뒤(j)** 에 insert 해야 한다.

---

## 루프가드 — `loop_guard.py` (R4) {#루프가드-loop_guardpy}

동일 호출의 반복을 감지해 루프를 차단한다. **파일 fingerprint** 를 시그니처에 포함해
"spec 파일을 고쳐 쓴 뒤 같은 경로로 재호출"(정당한 재시도)을 오탐으로 차단하지 않는다.

### `_LOOP_GUARD_MESSAGE`

루프 감지 시 LLM 에 회신하는 `[System]` 메시지. 정상 실행 경로와 형식오류
self-correct 경로 양쪽에서 **동일한 상수**를 재사용한다 — 한쪽만 바꾸지 말 것.

### `_collect_result_path_fingerprints(value, parts)`

인자 트리(`str`/`dict`/`list`) 를 재귀 순회하면서 `"result/"` 로 시작하는 문자열을
`resolve_result_path` 로 해석해 `"경로:mtime_ns:size"` 를 `parts` 에 append 한다.
미존재 경로·일반 문자열은 조용히 skip.

### `_call_signature(call) → tuple[str, str, str]`

```python
(call.name, json.dumps(call.arguments, sort_keys=True), "|".join(sorted(parts)))
```

3-튜플 `(도구명, 인자 JSON, 파일 fingerprint 합산)`. `history_calls: set[tuple]` 의
원소 타입이다. 동일 도구 동일 인자로도 참조 파일이 수정됐으면 fingerprint 가 달라
별개 시그니처로 취급된다.

### `_record_invalid_call(call, history_calls) → bool`

형식오류 self-correct 경로(`_guard_tool_args` 의 `invalid_message` 분기)에서 호출.
시그니처를 계산해 `history_calls` 에 이미 있으면 `True`(반복 — 루프가드 메시지로
전환), 없으면 `False`(최초 기록). **정상 실행 경로의 `history_calls` 와 동일한 집합**
을 공유하므로 "형식오류로 기록된 호출 → 같은 인자로 정상 실행 재시도" 패턴도 함께
감지된다.

---

## Pending 클리어 — `pending.py` (F11)

`run_turn` 성공 경로·예외 경로, `call_handlers` 일반 도구 경로가 각각 같은
pending 필드 묶음을 비우던 중복을 한 곳으로 모은다.

### `clear_pending_tool(state)`

`pending_tool` / `pending_args` / `missing_slots` 를 None·빈 dict 로 초기화한다.
슬롯 누락으로 보류됐던 도구가 같은 턴에 실행·중복차단되면 즉시 호출해 다음 턴
system prompt 가 stale pending 으로 오염되지 않게 한다.

### `clear_all_pending(state)`

`clear_pending_tool` + `pending_sub_agent` / `pending_sub_task` 까지 포함해 전부
비운다. AskUser 없이 턴이 완료됐다 = 사용자 입력 없이 해결됐다 = 어떤 pending 도
다음 턴으로 넘길 필요 없다. 호출 위치:

| 위치 | 트리거 |
|---|---|
| `run_turn` 마무리 (F11) | AskUser 없이 턴 정상 완료 |
| `_persist_failed_turn` (R1) | 최상위 예외 경로 — best-effort 영속 직전 |
