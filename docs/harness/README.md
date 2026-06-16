# 에이전트 하니스 (`backend/agent/harness/`)

하니스는 **사용자 입력 1건 → 완결된 응답 1턴**을 처리하는 서브시스템이다.
`run_turn()` 한 번이 곧 한 턴이며, 그 안에서 LLM provider 와 등록 도구 사이를
반복하며 plan 을 실행하고 필요 시 서브 에이전트에게 위임한다.

> **이 문서군의 위치** — 여기(`docs/harness/`)는 하니스의 **구조와 동작 흐름**을 패키지
> 단위로 설명하는 개발자용 워크스루다. 실 LLM 환경의 경계·실패 경로를 흡수하는
> **복원력 불변식**(F1~F12·R1~R8 — "왜 이 방어 코드가 있나, 회귀 금지")은
> [`.claude/rules/harness_resilience.md`](../../.claude/rules/harness_resilience.md) 에 별도로
> 정리돼 있다. 본 문서는 흐름 설명 중 해당 패턴을 `(R7)`·`(F6)` 식으로 **참조만** 한다.

---

## 패키지가 분해된 이유

하니스는 멀티 에이전트 오케스트레이션이라는 복잡도 때문에 **`agent/` 의 유일한 중첩
서브패키지**다(다른 `agent/` 서브시스템은 플랫 모듈). 최상위 코어 머신(플랫 모듈) +
책임별 3개 서브패키지로 나뉜다.

| 파일/폴더 | 책임 | 문서 |
|---|---|---|
| `loop.py` | 진입점 `run_turn` + 공통 provider→tool 루프 `_run_agent_turn` + 생애주기 헬퍼(wind-down·fallback·실패 영속) | [turn-loop.md](turn-loop.md) |
| `call_handlers.py` | tool_call **단건 3단계 파이프라인** + sentinel 디스패치 테이블 + 공유 가드 | [call-handlers.md](call-handlers.md) |
| `budget.py` | `TurnBudget` — 턴 호출 상한 + 같은-에이전트-연속-호출 가드 | [turn-loop.md](turn-loop.md#turnbudget) |
| `tool_exec.py` | `_execute_tool`(timeout·표준화) + `_append_tool_result` | [turn-loop.md](turn-loop.md#도구-실행) |
| `constants.py` | 루프 차원 상수(`ORCHESTRATOR_ID`·`WIND_DOWN_REMAINING_CALLS`·fallback 지시문) | [turn-loop.md](turn-loop.md) |
| `dispatch/` | 서브 에이전트 위임 — 순차·병렬·스펙 선별·결과 포맷 | [dispatch.md](dispatch.md) |
| `prompt/` | system prompt 조립 — 오케스트레이터/서브/단층·섹션·산출물·api_refs·wind-down | [prompt.md](prompt.md) |
| `state/` | 상태 변형 — todo·히스토리 정합성·루프가드·pending 클리어 | [state.md](state.md) |
| `__init__.py` | 공개 API(`run_turn`/`TurnBudget`/`ORCHESTRATOR_ID`) + 하위호환 re-export | — |

> `from agent.harness import run_turn` 경로는 분해 이후에도 불변이다(`__init__.py` re-export).

---

## 한 턴의 생애주기

```
POST /api/chat
  │
  ▼
run_turn(client_id, user_message, *, store, state_store, registries, provider, agent_registry?, force_skills?)
  ├─ set_session_context()           세션 메타를 contextvars 에 (도구·provider 가 산출물 경로 해소 시 참조)
  ├─ state_store.get()               AgentState (todo / pending 슬롯) 로드
  ├─ terminal todo 리셋 (R5)         직전 턴 plan 이 전부 종결됐으면 빈 plan 으로 시작
  ├─ SKILL 선택                      force_skills(슬래시) → get_by_names / 아니면 trigger 매칭 select()
  ├─ system prompt 합성              _make_system_prompt_composer → _recompose(skills)
  │                                  (오케스트레이터 / 단층 — prompt/compose.py)
  ├─ SkillActiveEvent · TodoUpdateEvent (있으면)
  │
  └─ _run_agent_turn(depth=0)  ◀── 공통 provider→tool 루프 (turn-loop.md)
        for iteration in range(max_iterations):
          ├─ wind-down 주입 (R7)     남은 호출 ≤ 2면 [System] 마무리 지시 1회
          ├─ budget.try_consume()    초과 시 ErrorEvent 안전 종료
          ├─ provider.astream()      delta / tool_call / reasoning 수집·즉시 yield
          ├─ tool_call 없음 → 최종 assistant 메시지 append 후 종료
          └─ 각 tool_call → call_handlers._handle_tool_call(ctx, call, outcome)
                ├─ CONTINUE   다음 호출
                ├─ interrupted(ask_user·슬롯 누락) → 미해결 쌍 보정(F1b) 후 break
                └─ stop(complete_subagent) → 즉시 종료
        else (반복 상한 소진) → _emit_max_iterations_fallback (F6)
  │
  ├─ AskUser 없이 완료 → pending 전부 클리어 (F11)
  ├─ store.append(turn_messages) + state_store.set + DoneEvent
  └─ 예외 시 → _persist_failed_turn(R1) → ErrorEvent(F12) → DoneEvent
```

오케스트레이터(depth 0)와 서브 에이전트는 **같은 `_run_agent_turn` 루프**를 공유한다.
서브 에이전트는 `agent_registry=None`·`turn_messages=None` 으로 호출돼 위임 도구가
시야에서 빠지고(중첩 차단) 히스토리에 영속되지 않는다(컨텍스트 격리).

---

## SKILL 활성화의 세 경로

system prompt 에 어떤 SKILL 본문이 실릴지는 세 가지로 결정된다:

1. **트리거 매칭** — `skill_registry.select(user_message)` 가 Front Matter `trigger` 키워드로 자동 선택(턴 시작).
2. **슬래시 커맨드** — 사용자가 `/skill_name` 으로 보내면 `force_skills` 로 그 SKILL 을 강제 활성화.
3. **`activate_skill` (능동 활성화)** — LLM 이 **비활성 SKILL 카탈로그**(prompt/sections)를 보고
   의미가 맞는 SKILL 을 턴 도중 스스로 켠다. → `_handle_activate_skill` 가 turn-local
   `active_skills` 를 갱신하고 `_recompose` 클로저로 **system prompt 를 동적으로 재조립**한다.
   상세: [call-handlers.md](call-handlers.md#activate_skill--동적-프롬프트-재조립) · [prompt.md](prompt.md).

---

## 중첩 위임 4중 방어선

서브 에이전트가 다시 서브 에이전트를 부르는 무한 재귀를 4겹으로 차단한다(상세 [dispatch.md](dispatch.md#중첩-위임-4중-방어선)):

| 계층 | 위치 | 차단 방식 |
|---|---|---|
| L0 | `_dispatch_sub_agent` | 서브 turn 을 `agent_registry=None` 으로 실행 → call_sub_agent 분기 자체가 비활성 |
| L1 | `spec_filter._filter_specs_for_sub_agent` | 위임 도구 스펙을 LLM 시야에서 제거 |
| L2 | `_dispatch_sub_agent` depth guard | `depth > MAX_AGENT_DEPTH` 이면 위임 거부 |
| L3 | `tool_exec._execute_tool` sentinel guard | sentinel 도구가 실행 단계까지 흘러오면 명시적 에러 |
