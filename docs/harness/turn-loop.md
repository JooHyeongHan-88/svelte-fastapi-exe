# 턴 루프 — `loop.py` · `budget.py` · `tool_exec.py` · `constants.py`

하니스의 코어 머신. **진입점(`run_turn`)** 과 **공통 provider→tool 루프(`_run_agent_turn`)**,
그리고 그 둘을 떠받치는 호출 예산·도구 실행·루프 상수가 여기 모여 있다.

---

## `run_turn` — 오케스트레이터 진입점 (`loop.py`)

`run_turn(client_id, user_message, *, store, state_store, skill_registry, prompt_registry,
registry, provider, max_iterations, agent_registry=None, max_agent_calls=10,
force_skills=None, session_title="", user_prompt="")` → `AsyncIterator[StreamEvent]`.

준비 단계는 가독성을 위해 헬퍼로 분리돼 있다:

| 단계 | 동작 |
|---|---|
| `set_session_context` | client_id·session_title 을 contextvars 에 저장 (도구·provider 가 산출물 경로 해소 시 참조). late import 로 순환 회피 |
| state 로드 + terminal todo 리셋 | `state_store.get()`. todo_list 가 비어있지 않고 **전원 terminal**(completed/failed/skipped)이면 비운다 (R5 — 완료 todo 가 새 턴 UI·프롬프트를 오염시키는 것 방지) |
| SKILL 선택 | `force_skills` 있으면 `get_by_names()`, 없으면 `skill_registry.select(user_message, available_tools=...)` |
| `_make_system_prompt_composer` | system prompt 를 동적 재조립하는 **클로저** `_recompose(skills)` 를 만든다. `activate_skill` 이 SKILL 을 켤 때 이 클로저로 prompt[0] 을 다시 쓴다 |
| `_build_orchestrator_specs` | provider 에 노출할 도구 스펙 선별 (아래) |
| `_run_agent_turn(depth=0)` | 공통 루프 실행. 모든 이벤트를 그대로 yield, `AskUserEvent` 발생 여부를 추적 |
| 마무리 | AskUser 없이 끝났으면 `clear_all_pending(state)` (F11) → `store.append(turn_messages)` → `state_store.set` → `DoneEvent` |

`turn_messages` 는 영속화 대상 버퍼(`[user_msg]` 로 시작). `turn_persisted` 플래그는
성공 경로 append 직후 state flush 가 실패하는 좁은 창에서 except 가 재-append 해
턴이 중복 영속되는 것을 막는다.

### `_make_system_prompt_composer`

`has_agents` 여부로 분기해 base prompt(±`orchestrator.md`)를 한 번 만들고, 활성 SKILL
목록을 받아 완성된 system prompt 를 돌려주는 클로저를 반환한다. base 와 state 는 이번
턴 시점 확정값이라 캡처해도 안전하다. `has_agents` 면
`_compose_orchestrator_system_prompt`, 아니면 단층 `_compose_system_prompt` 를 부른다
(→ [prompt.md](prompt.md)). 사용자가 SettingsModal 에 적은 추가 지침은 base 뒤에 한 번 덧붙는다.

### `_build_orchestrator_specs`

`COMPLETE_SUB_AGENT`(서브 전용)는 항상 숨기고, AGENTS 가 없으면 위임 도구
(`call_sub_agent`·`call_sub_agents_parallel`)도 제거한다. 활성 SKILL 중 하나라도
`api_refs` 를 가지면 `_inject_runtime_tools` 로 인프라 메타 도구를 자동 주입한다
(SKILL 본문에 명시하지 않아도 LLM 이 자체 plan 에 쓰게 함).

### `_persist_failed_turn` (R1)

최상위 `except Exception` 의 best-effort 영속. 실패한 턴도 사용자 메시지까지 보존해야
다음 턴 컨텍스트가 끊기지 않는다. `clear_all_pending` → (미persist 면)
`_balance_all_unresolved`(미해결 tool_call 쌍 보정, OpenAI 400 방지) + `store.append` →
`state_store.set`. 영속 자체가 또 실패해도 로그만 남기고 ErrorEvent/DoneEvent 송출은
막지 않는다. 에러 메시지는 `f"[{type(exc).__name__}] 처리 중 오류..."` 로 안전화(F12 — 키·URL 노출 방지).

---

## `_run_agent_turn` — 공통 provider→tool 루프 (`loop.py`)

오케스트레이터와 서브 에이전트가 **동일하게** 쓰는 루프 골격. 시작 시
`turn_messages is not None or agent_registry is None` 을 단언한다 — 서브 에이전트
컨텍스트(`turn_messages=None`)에서 `agent_registry` 가 살아 있으면 중첩 위임이
열리므로 L0 방어선을 assert 로 못박는다.

턴 시작에 `TurnContext` 를 1회 만들어 핸들러 시그니처를 `(ctx, call, outcome)` 로
통일한다(→ [call-handlers.md](call-handlers.md)). 매 iteration:

```
for iteration in range(max_iterations):
  ① _maybe_inject_wind_down(ctx, iteration, notified)   남은 호출 ≤ 2면 [System] 마무리 지시 1회 (R7)
  ② budget.try_consume()                                False → ErrorEvent 후 return
  ③ provider.astream(messages, sub_specs)
        delta      → assistant_buffer 누적 + yield
        tool_call  → pending_tool_calls 누적 + yield
        reasoning  → yield
        skill_active → yield (provider 가 직접 emit 하는 mock 경로)
        done       → break
        그 외       → yield 후 return (조기 종료)
  ④ tool_call 없음 → assistant_text 를 turn_messages 에 append 후 return
  ⑤ assistant_msg(tool_calls 포함) 를 messages·turn_messages 에 append
  ⑥ for call in pending_tool_calls:
        _handle_tool_call(ctx, call, outcome) 의 이벤트를 yield
        outcome.stop        → return (complete_subagent — 남은 호출 무시)
        outcome.interrupted → break
  ⑦ interrupted 면 _balance_unresolved_tool_calls (F1b) 후 return
else:  # 반복 상한 소진
  _emit_max_iterations_fallback (F6)
```

### 생애주기 헬퍼

- **`_maybe_inject_wind_down` (R7)** — `remaining_calls = min(반복 잔여, budget 잔여)` 가
  `WIND_DOWN_REMAINING_CALLS`(2) 이하로 떨어지는 시점에 `_build_wind_down_message` 의
  마무리 지시문을 `messages` 에만 1회 주입한다(히스토리 비영속). 진행은 정상인데 예산만
  소진돼 `display_*` 같은 사용자 노출 단계가 잘리는 것을 방지. 1회 주입 후 재주입 안 함.
- **`_emit_max_iterations_fallback` (F6)** — 반복 상한 소진 시 도구 없는 최종 요약 라운드를
  돌린다. 모든 todo 가 terminal 이면 `is_recovered=True`(완료·예산 소진 → 프론트 초록 점선),
  아니면 False(미완료 → 빨강 점선). 자연어 응답이 나오면 `ErrorEvent(is_fallback=True,
  is_recovered=...)` 만 보내고, fallback 호출 자체가 실패하면 일반 ErrorEvent.

---

## `TurnBudget` (`budget.py`) {#turnbudget}

한 사용자 턴에서 오케스트레이터 + 모든 (재귀) 서브 에이전트의 provider 호출 **총량**을
제한한다(`max_calls`, `APP_MAX_AGENT_CALLS_PER_TURN`). `loop` 와 양 디스패처가 공유한다.

| 메서드 | 동작 |
|---|---|
| `try_consume()` | 호출 1회 소비. `used >= max_calls` 면 False (상한 도달) |
| `check_dispatch(agent_name)` | 같은 에이전트 연속 호출 가드. `MAX_CONSECUTIVE_SAME_AGENT`(3) 초과 시 차단 사유 문자열, 통과 시 None |

병렬 디스패치는 의도된 동시성이라 `check_dispatch` 를 `skip_consecutive_guard=True` 로
건너뛴다(→ [dispatch.md](dispatch.md)).

---

## 도구 실행 (`tool_exec.py`) {#도구-실행}

- **`_execute_tool(call, registry)`** — 등록 도구를 `asyncio.wait_for(timeout=tool.timeout_seconds)`
  안에서 실행해 `ToolResult` 로 표준화한다.
  - unknown tool → `is_error` ToolResult. **sentinel 도구가 여기까지 흘러오면** 명시적
    에러(L3 방어선 — harness 분기 누락 버그를 조용히 통과시키지 않음).
  - 실행 직전 `input_model.model_validate` 로 raw 인자를 Pydantic 강제 변환하고,
    `{name: getattr(parsed, name) for name in model_fields}` 로 kwargs 추출 —
    `model_dump()` 는 중첩 모델(`list[ImageItem]` 등)을 dict 로 직렬화해 타입 불일치를
    내므로 **쓰지 않는다**.
  - timeout → `[timeout] ...`, 예외 → `[error] {type}: {exc}` (스택트레이스 로깅).
  - `is_error=True` 결과에는 RCA + 1회 재시도 유도 `[System]` 메시지를 자동 첨부.
- **`_append_tool_result(messages, turn_messages, call, text)`** — `role="tool"` 메시지를
  LLM 컨텍스트와 영속 버퍼 양쪽에 누적한다. 서브 에이전트는 `turn_messages=None` 이라
  컨텍스트에만 들어간다(격리).

---

## 루프 상수 (`constants.py`)

| 상수 | 값 | 용도 |
|---|---|---|
| `ORCHESTRATOR_ID` | `"orchestrator"` | depth 0 에이전트 식별자 — AgentSwitch/Progress 라벨·로깅 |
| `WIND_DOWN_REMAINING_CALLS` | `2` | 마무리 지시 임계 (R7) — '마지막 도구 1회 + 최종 요약 1회' 여유 |
| `MAX_ITERATIONS_FALLBACK_INSTRUCTION` | (문자열) | 반복 상한 소진 시 회신하는 마무리 지시문 (F6) |

모듈 고유 로직에 밀착된 상수(`state.todo._TERMINAL_STATUSES`,
`state.loop_guard._LOOP_GUARD_MESSAGE` 등)는 응집도를 위해 각 거처에 둔다.
