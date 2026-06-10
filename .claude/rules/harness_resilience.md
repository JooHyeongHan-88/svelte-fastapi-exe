# Harness 복원력 패턴

실제 LLM 환경에서 발생하는 경계/실패 경로를 처리하는 설계 결정들.
Mock 시나리오는 happy path만 검증하므로, 이 문서의 패턴들은 실 LLM 투입 시 임계적이다.

---

## 슬롯 가드 — 오류 책임자 분기 (`backend/agent/guard.py`)

`validate_tool_args()` 는 ValidationError 를 **책임자별로** 두 경로로 나눈다:

| ValidationError 종류 | 책임자 | 처리 |
|---|---|---|
| `type=="missing"` (값 자체 부재) | 사용자 | `MissingSlot` → `AskUserEvent` (사용자에게 재질문) |
| 형식/타입/enum 위반 (값은 줬는데 모양이 틀림) | **LLM** | `invalid_message` → `ToolResultEvent(is_error=True)` → LLM self-correct |

- 양쪽이 동시에 있으면 `invalid_message` 경로가 누락 항목까지 한 번에 안내한다.
- 동일한 잘못된 호출 반복은 `history_calls` loop-guard가 차단한다(`_LOOP_GUARD_MESSAGE`).
- `slot_prompts` 딕셔너리는 **missing 슬롯에만** 적용된다 (형식 오류는 LLM 에게 회신되므로 미사용).

**주의**: `save_artifact(kind='json', content=<dict>)` 처럼 값은 줬는데 타입이 `str` 대신 `dict`면 형식 오류 → LLM self-correct 경로(사용자 미개입). `artifact.py`의 `content: str | dict | list | None` 참고.

---

## Provider 스트리밍 경계 (`backend/agent/providers/openai.py`)

### 스트림 생성 재시도 (F4)

`_create_stream_with_retry()` 가 일시 오류(`APIConnectionError`, `APITimeoutError`, `RateLimitError`, `InternalServerError`)를 지수 백오프로 재시도한다. 영구 오류(401, 400)는 즉시 전파.

- 재시도는 **스트림 생성 전** 단계에서만 — 일부 이벤트를 yield한 뒤 재시도는 불가.
- `_MAX_RETRIES = 2`, `_RETRY_BASE_DELAY = 0.5s` + jitter.

### 스트림 잘림 대응 (F2)

스트림이 `finish_reason="length"`(잘림)이나 연결 종료로 끊겨도:
1. 버퍼된 `tool_calls_buffer` 를 항상 flush → `ToolCallEvent` yield.
2. `DoneEvent` 를 **정확히 1회** 보장 — harness 루프가 멈추지 않음.

### 깨진 인자 JSON 마커 (F3)

스트리밍 잘림으로 tool_call 인자 JSON이 불완전하면 `{}` 로 뭉개지 않고 `MALFORMED_TOOL_ARGS_KEY`(→ `models.py`) 에 원본을 보존한다.

```python
{"__malformed_arguments__": '{"code": "x='}   # 예시
```

harness 루프 최상단이 이 마커를 감지 → `ToolResultEvent(is_error=True)` 로 LLM 에 재전송 요구. 사용자에게 묻지 않는다.

---

## 대화 히스토리 정합성 (`backend/agent/stores/conversation.py`)

### Tool 쌍 보존 트리밍 (F1a)

`ConversationStore.append()` 의 트리밍은 고아 `role="tool"` 메시지가 첫 메시지로 남지 않도록 cut 경계를 앞으로 밀어 보정한다.

```
OpenAI 와이어 규약: tool 메시지는 선행 assistant.tool_calls 에 반드시 대응해야 함.
규약 위반 시 다음 턴 요청이 400 으로 거부된다.
```

### 배치 중단 시 미해결 tool_call placeholder (F1b)

`_balance_unresolved_tool_calls()` — 배치 도중 AskUser 등으로 턴이 끊기면 처리되지 못한 tool_call 에 placeholder `role="tool"` 응답을 채워 쌍을 완성한다. `harness._run_agent_turn()` 의 `if interrupted:` 블록에서 호출된다.

### Tool 결과 히스토리 Truncation (F7)

히스토리 저장 시 `role="tool"` 메시지를 **800자**로 절단한다 (`_TOOL_HISTORY_MAX_CHARS`).

- **현재 턴** `messages` 리스트(LLM이 직접 읽는 컨텍스트)에는 **full 내용** 유지.
- 히스토리(다음 턴부터 읽힘)에는 절단본 저장 → exec_code stdout 4000자가 매 턴 누적되는 문제 해소.
- `_truncate_for_history()` 는 새 객체를 반환 — 원본 Message 객체를 절대 변형하지 않는다.

---

## Pending 상태 자동 클리어 (`backend/agent/harness.py`, F11)

`run_turn()` 끝에서 `AskUserEvent` 가 한 번도 yield되지 않았으면 pending 상태를 모두 클리어한다:

```python
state.pending_tool = None
state.pending_args = {}
state.missing_slots = {}
state.pending_sub_agent = None
state.pending_sub_task = None
```

**이유**: LLM 이 pending 재시도를 무시하고 다른 작업을 하면 stale pending 이 다음 턴 system prompt를 오염시킨다. AskUser 없이 턴이 완료됐다 = 사용자 입력 없이도 해결됐다 = pending 불필요.

---

## Fallback Salvage 표현 (`backend/agent/harness.py` + frontend, F6)

max_iterations 도달 시 salvage 응답의 스타일이 **작업 완료 여부**에 따라 다르다:

| 조건 | `ErrorEvent.is_recovered` | 프론트 표현 |
|---|---|---|
| 모든 todo 가 terminal 상태 | `True` | 초록 점선 (`--color-success`) — "완료됐지만 예산 소진" |
| todo 미완 또는 todo 없음 | `False` | 빨강 점선 (`--danger`) — "미완료 주의" |

`Segment.svelte` 의 `.text-seg.recovered` / `.text-seg.fallback` CSS 클래스 분기.

---

## 실패 턴 영속 + DoneEvent 보장 (`backend/agent/harness.py`, R1)

`run_turn()` 최상위 `except Exception` 이 ErrorEvent 만 내보내고 끝나면 실패한 턴
전체(사용자 메시지 포함)가 백엔드 히스토리에서 증발하고 mid-mutation pending 이
다음 턴을 오염시킨다. except 블록이 best-effort 로 다음을 수행한다:

1. `_balance_all_unresolved(turn_messages)` — 버퍼 **전수 스캔**으로 미해결 tool_call
   에 placeholder 를 해당 assistant 블록 **바로 뒤에 삽입** (끝 append 는 와이어 규약
   위반). F1b 의 `_balance_unresolved_tool_calls` 는 in-flight assistant 한 건 전용이라
   예외 시점에는 쓸 수 없다.
2. F11 과 동일한 pending 클리어 → `store.append` + `state_store.set`.
3. ErrorEvent(F12 안전화 유지) 뒤 **DoneEvent 정확히 1회**.

- `turn_persisted` 플래그: 성공 경로의 append 성공 ↔ state flush 실패 사이 좁은 창에서
  except 가 재-append 해 턴이 중복 영속되는 것을 방지.
- 영속 자체가 또 실패하면 로그만 남기고 ErrorEvent/DoneEvent 송출은 막지 않는다.
- ESC/disconnect 의 `CancelledError` 는 `BaseException` 이라 이 경로를 타지 않는다
  (중단 턴 미영속은 의도된 기존 동작).

테스트: `backend/tests/test_harness_error_path.py`

---

## 동시 턴 가드 (`backend/api/chat.py`, R2)

같은 client_id 로 턴이 진행 중일 때 두 번째 `/api/chat` POST 는 **즉시 거부**된다 —
run_turn 미진입, `ErrorEvent("이미 응답을 생성 중...") + DoneEvent` 2건으로 스트림 종결.

- 탭 복제(같은 세션 = 같은 client_id 공유)는 presence 가 명시 지원하는 시나리오라,
  양쪽 동시 전송 시 두 run_turn 이 병주해 히스토리 교차 저장·state Last-Write-Wins
  오염이 발생할 수 있었다. 프론트 `ui.streaming` 가드는 탭 단위라 막지 못한다.
- `_active_turn_clients: set[str]` — uvicorn 단일 event loop 에서 check-and-add 사이에
  await 가 없으므로 set 만으로 원자적. 해제는 `finally` (CancelledError 포함 전 경로).

테스트: `backend/tests/test_chat_concurrent_guard.py`

---

## 에러 메시지 안전화 (F12)

- `run_turn()` 최상위 `except Exception`: `str(exc)` → `f"[{type(exc).__name__}] 처리 중 오류가 발생했습니다."` — API 키·URL 노출 방지.
- `chat.py` `event_source()`: `asyncio.CancelledError` (ESC/disconnect) 는 debug 로그 후 재전파 — Exception 스택트레이스 노이즈 방지.
- **`_execute_tool()` 내부 에러 메시지는 LLM self-correct 용**이므로 `{exc}` 상세 내용 유지.

---

## exec_code / eval_expression 스코프 (`backend/agent/runtime/evaluator.py`)

`safe_exec` / `safe_eval` 은 globals/locals 를 **단일 dict(module scope)** 로 실행한다.

분리하면(구 방식) generator expression·nested def가 free 변수를 locals에서 못 찾아 `NameError`:
```python
mean = sum(values) / len(values)
ss = sum((x - mean)**2 for x in values)  # NameError: 'mean' — genexpr 별도 스코프
```

단일 dict로 통합하면 module scope처럼 실행돼 해결. `safe_exec`는 실행 후 `__builtins__`를 제거해 namespace 오염을 방지한다.
