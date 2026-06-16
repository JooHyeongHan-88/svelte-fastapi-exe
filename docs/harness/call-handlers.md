# tool_call 처리 — `call_handlers.py`

`_run_agent_turn` 이 assistant 가 emit 한 tool_call **하나하나**를
`_handle_tool_call(ctx, call, outcome)` 에 위임한다. 이 모듈이 그 단건 처리를 담당한다.

모든 핸들러는 **균일하게 async generator** 다 — `StreamEvent` 를 즉시 yield 하고
(서브 에이전트의 긴 진행 스트림도 그대로 흘려보냄), 제어 흐름은 호출부가 건넨
`CallOutcome` 아웃파라미터로 보고한다. sync/async sentinel 을 가르지 않고 단일
디스패치 프로토콜로 통일된다.

---

## 데이터클래스

### `TurnContext`

`_run_agent_turn` 한 턴 전체에서 고정된 실행 환경. 핸들러 시그니처를 `(ctx, call,
outcome)` 로 통일하기 위한 파라미터 객체다. `provider` 는 `providers.factory.LLMProvider`
Protocol 타입. 가변 컬렉션(`messages`·`history_calls`·`active_skills`)은 같은 객체를
in-place 갱신한다. `is_sub_agent` 프로퍼티는 `turn_messages is None` 을 관례적 신호로 본다.

### `CallOutcome`

tool_call 한 건 처리 후 호출부가 읽는 제어 신호. 둘 다 False 면 **CONTINUE**(다음 호출):

| 필드 | 의미 |
|---|---|
| `interrupted` | ask_user·슬롯 누락 → 루프 break 후 미해결 tool_call 보정 |
| `stop` | complete_subagent → `_run_agent_turn` 즉시 종료 |

---

## 3단계 파이프라인 — `_handle_tool_call`

```
① 특수 호출
   ├─ MALFORMED_TOOL_ARGS_KEY ∈ arguments ?  → _handle_malformed_args (F3)
   └─ _select_sentinel_handler(ctx, call)     → 매칭되면 sentinel 핸들러
② + ③ 일반 도구
   └─ _handle_normal_tool  →  _guard_tool_args  →  _loop_guard_denial  →  _execute_tool  →  todo 반영
```

### 1단계 — 깨진 인자 (F3)

스트리밍 잘림 등으로 tool_call 인자 JSON 이 불완전하면 provider 가 원본을
`MALFORMED_TOOL_ARGS_KEY` 에 보존해 넘긴다. `_handle_malformed_args` 는 빈 인자로
오인해 슬롯 누락을 묻지 않고, "더 짧고 정확한 JSON 으로 다시 호출하라"는
`ToolResultEvent(is_error)` 로 LLM 에 self-correct 를 요구한다. 반복되면 루프가드 메시지로 전환.

### 1단계 — sentinel 디스패치 테이블 `_SENTINEL_ROUTES`

`(이름, 적용 조건, 핸들러)` 튜플의 순서 있는 목록. `_select_sentinel_handler` 가
`call.name == 이름 and 조건(ctx)` 인 첫 핸들러를 고르고, 없으면 None(→ 일반 도구 경로).
조건은 원래 if/elif 의 컨텍스트 가드를 보존한다 — 조건 미충족 시 일반 도구로 폴백돼,
서브 에이전트 컨텍스트로 흘러든 오케스트레이터 전용 sentinel 은 `_execute_tool` 의
sentinel-bypass 에러(L3)로 잡힌다.

| sentinel | 적용 조건 | 핸들러 동작 |
|---|---|---|
| `activate_skill` | `active_skills is not None` | 카탈로그 SKILL 능동 활성화 + 프롬프트 재조립 (아래) |
| `complete_subagent` | `is_sub_agent` | summary 를 ToolResultEvent 로 emit + `outcome.stop=True` |
| `add_todo` | `state is not None` | TodoItem 누적 + `TodoUpdateEvent` |
| `complete_todo` | `state is not None` | 상태 전이 + `TodoUpdateEvent` + 전원 terminal 이면 `SkillCompleteEvent` |
| `ask_user` | 항상 | placeholder + `AskUserEvent` + `outcome.interrupted=True` |
| `call_sub_agent` | `agent_registry is not None` | 순차 위임 (→ [dispatch.md](dispatch.md)) |
| `call_sub_agents_parallel` | `agent_registry is not None` | 병렬 위임 (→ [dispatch.md](dispatch.md)) |

### 2+3단계 — 일반 도구 `_handle_normal_tool`

`_guard_tool_args`(통과면 None) → 통과하면 `_loop_guard_denial` → 둘 다 통과하면
`_execute_tool` 실행 → `ToolResultEvent` → `_emit_post_tool_todo_events`.

---

## `activate_skill` — 동적 프롬프트 재조립 {#activate_skill--동적-프롬프트-재조립}

트리거 매칭·슬래시 외의 **제3의 SKILL 활성화 경로**. LLM 이 system prompt 의
**비활성 SKILL 카탈로그**(→ [prompt.md](prompt.md))를 보고 의미가 맞는 SKILL 을 턴 도중
스스로 켤 수 있다.

```
_handle_activate_skill(ctx, call, outcome)
  ├─ _activate_skills_in_context(ctx, name)   turn-local active_skills 에 추가, 새로 켜진 것만 반환
  └─ 새로 활성화됐고 recompose_system 이 있으면:
        ctx.messages[0] = Message("system", recompose_system(active_skills))   ← system prompt 동적 교체
        yield SkillActiveEvent(skills=[...])
        state.active_skills 갱신
```

`recompose_system` 은 `run_turn` 의 `_make_system_prompt_composer` 가 만든 클로저다
(→ [turn-loop.md](turn-loop.md)). 이미 활성화됐거나 카탈로그에 없는 이름이면 멱등 응답
(`is_error=True` ToolResult)만 회신한다.

---

## 공유 가드 — "통과면 None, 차단이면 이벤트 목록"

세 dispatch/일반 핸들러에 중복되던 프롤로그를 일원화한 헬퍼들. 호출부는
`denial = _guard...(); if denial: yield from denial; return` 패턴으로 쓴다.

### `_guard_tool_args` — 슬롯 가드 (책임자 분기)

`validate_tool_args` 로 인자를 검증해 **오류 책임자별로** 갈린다(상세: harness_resilience.md):

| 결과 | 처리 | outcome |
|---|---|---|
| 형식/타입 오류 (`invalid_message`) | LLM self-correct 용 `ToolResultEvent(is_error)` 1건. 반복되면 루프가드 메시지 | 미변경(CONTINUE) |
| 필수 슬롯 누락 (`not ok`) | `_emit_missing_slot` → state 에 pending 기록 + `AskUserEvent` | `interrupted=True` |
| 통과 | None | — |

### `_loop_guard_denial` (R4)

`_call_signature(call)`(= 이름 + 정렬 인자 JSON + `result/` 참조 파일 fingerprint)이
`history_calls` 에 이미 있으면 루프가드 `ToolResultEvent(is_error)`, 처음이면 기록 후 None.
파일 fingerprint 덕에 "spec 을 고쳐 쓴 뒤 같은 경로로 재호출"하는 정당한 재시도는
차단하지 않는다(→ [state.md](state.md#루프가드-loop_guardpy)).

### `_emit_post_tool_todo_events`

도구 실행 직후 `_mark_running_todo_done` 으로 실행 중이던 todo 를 결과에 맞춰 종료하고,
전원 terminal 이면 `SkillCompleteEvent` 까지 emit. `pending_tool` 이 이 도구면 클리어.
`state` 가 없는(서브 에이전트) 컨텍스트면 no-op.

### `_clear_pending_sub_agent_on_success`

순차 위임이 성공 완료되면, 직전 턴 서브 에이전트가 슬롯 부족으로 걸어둔
`pending_sub_agent` 잔재를 비워 다음 턴 프롬프트 오염을 막는다.
