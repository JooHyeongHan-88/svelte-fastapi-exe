# 서브 에이전트 디스패치 — `dispatch/`

오케스트레이터가 복잡한 작업을 전문 서브 에이전트에게 위임하는 경로. 순차(`call_sub_agent`)와
병렬(`call_sub_agents_parallel`) 두 방식이 있고, 노출 도구 선별과 결과 포맷이 보조한다.

| 모듈 | 역할 |
|---|---|
| `sequential.py` | `_dispatch_sub_agent` — 위임 1건을 격리 컨텍스트에서 순차 실행 |
| `parallel.py` | `_dispatch_parallel_sub_agents` — 독립 작업들을 동시 실행·fan-in |
| `spec_filter.py` | `_filter_specs_for_sub_agent` — 서브에 노출할 도구 스펙 선별 + 런타임 도구 주입 |
| `result_format.py` | `_format_sub_agent_result`·`_extract_task_summary` — 결과를 오케스트레이터 컨텍스트용 텍스트로 |

> **상호재귀 경계**: `loop._run_agent_turn` ↔ `dispatch.sequential._dispatch_sub_agent` 는
> 서로를 부른다. 순환 import 를 피하려 `sequential.py` 가 `_run_agent_turn` 을 **함수 본문에서
> late import** 한다(`run_turn` 의 `set_session_context` late import 와 동일한 코드베이스 관례).

---

## 순차 위임 — `_dispatch_sub_agent` (`sequential.py`)

`call_sub_agent` sentinel 1건을 격리된 컨텍스트에서 실행하고, 내부 이벤트를
**AgentSwitch → AgentProgress×N → AgentReturn** 으로 래핑해 yield 한다. 부모
`_run_agent_turn` 이 `AgentReturnEvent.summary` 를 캡처해 tool_result 로 변환한다.

```
_dispatch_sub_agent(call, parent_agent_id, ..., dispatch_id?, ask_user_mode="surface", skip_consecutive_guard=False)
  ① depth guard          depth > MAX_AGENT_DEPTH → 에러 요약 AgentReturnEvent 후 종료 (L2)
  ② consecutive guard    skip 아니면 budget.check_dispatch(name) → 3회 연속이면 차단 요약
  ③ agent 조회           agent_registry.get_by_name — 없으면 unknown agent 요약
  ④ AgentSwitchEvent(from_agent, to_agent, reason=task[:80], dispatch_id)
  ⑤ 격리 prompt          _resolve_agent_skills → _compose_sub_agent_system_prompt
                         (base + safety + 에이전트 본문 + 학습 SKILL 본문 + 종료 규약)
  ⑥ sub_messages = [system, user(task)]  ·  sub_specs = _filter_specs_for_sub_agent(...)  ·  sub_state = AgentState()
  ⑦ late import _run_agent_turn(agent_registry=None, turn_messages=None, state=sub_state, depth=depth)
        DeltaEvent                         → last_assistant_text 누적 + _progress 래핑
        ToolResultEvent(COMPLETE_SUB_AGENT)→ complete_subagent_summary 캡처
        ToolResultEvent(그 외)             → tool/error 카운트 + _progress
        ToolCall/Reasoning/Todo/Skill*     → _progress 래핑
        AskUserEvent                       → ask_user_mode 분기 (아래)
        ErrorEvent                         → 에러 요약 AgentReturnEvent 후 종료
  ⑧ AgentReturnEvent(summary, todo_log, tool_calls_count, error_count, dispatch_id)
```

- **`_progress(ev)`** — 서브의 raw 이벤트를 `AgentProgressEvent(agent_id, inner_type,
  inner_payload, dispatch_id)` 로 래핑한다. 프론트는 `dispatch_id` 로 정확한 트레일에 라우팅.
- **`agent_registry=None` (L0)** · **`turn_messages=None`** — 중첩 위임 차단 + 컨텍스트 격리.
- **summary** — `complete_subagent` 호출 결과를 우선 쓰고, 없으면
  `_extract_task_summary` 가 마지막 assistant 텍스트의 `Task Summary:` 헤더를 파싱(폴백 마지막 200자).

### `ask_user_mode` — 서브가 사용자 입력을 필요로 할 때

| 모드 | 사용처 | 동작 |
|---|---|---|
| `"surface"` (기본·순차) | `call_sub_agent` | `orchestrator_state` 에 `pending_sub_agent`/`pending_sub_task`/`missing_slots` 저장 후 **AskUserEvent 를 직접 사용자에게 yield** → AgentReturnEvent 없이 종료. 부모가 AskUser 를 감지해 턴 interrupted. 다음 턴 프롬프트의 "Pending Sub-Agent Slot" 이 재위임 유도 |
| `"abort"` (병렬) | `call_sub_agents_parallel` | 사용자에게 묻지 않고 그 작업만 "입력 필요" 에러 요약 AgentReturnEvent 로 변환. orchestrator_state 미변경 — 오케스트레이터가 결과를 보고 순차 재위임 |

---

## 병렬 위임 — `_dispatch_parallel_sub_agents` (`parallel.py`)

`call_sub_agents_parallel(tasks=[{agent_name, task}, ...])` 의 독립 작업들을 **동시에**
실행한다. 순차 경로를 그대로 두고 신규 분기로만 추가됐다.

```
_dispatch_parallel_sub_agents(call, ..., max_parallel, result_holder)
  ├─ tasks 파싱           dispatch_id = f"{call.id}::p{i}"  (상관키)
  ├─ Semaphore(max_parallel)  ·  asyncio.Queue (fan-in)
  ├─ task 마다 _produce 코루틴을 asyncio.create_task:
  │     async with sem:
  │       _dispatch_sub_agent(ask_user_mode="abort", skip_consecutive_guard=True, dispatch_id=...)
  │       이벤트 → queue.put(("ev", ev));  AgentReturnEvent → summaries[did] 저장
  │     finally: queue.put(("done", did))
  ├─ 소비 루프: remaining 만큼 큐에서 꺼내 ("ev"→yield, "done"→remaining-=1)
  ├─ finally: 미완 task 전부 cancel + gather(return_exceptions=True)  ← 고아 task 방지(ESC·탭 종료)
  └─ 입력(task) 순서대로 요약을 "### 병렬 작업 i/total — name" 블록으로 합쳐 result_holder["combined"]
```

- **dispatch_id 상관키** — 같은 이름 에이전트를 둘 이상 동시에 띄워도 프론트가 각자
  트레일로 정확히 라우팅한다(`{call.id}::p{i}`).
- **단일 통합 tool_result** — 전원 완료 후 입력 순서대로 요약을 합쳐 **하나의**
  tool_result 본문으로 채운다. call ↔ tool_result 1:1 쌍이 유지돼 히스토리 정합성 로직
  (F1a·F1b·F7)을 건드리지 않는다.
- **가드** — `skip_consecutive_guard=True`(의도된 동시성이라 연속 호출 가드 오탐 방지).
  `TurnBudget` 합산 상한은 그대로 적용. 동시 실행 수는 `Semaphore(APP_MAX_PARALLEL_SUBAGENTS)`.
- depth: 병렬도 오케스트레이터(depth 0)에서만 발생하고 각 서브는 `agent_registry=None` 으로 실행돼 중첩이 차단된다.

---

## 노출 도구 선별 — `_filter_specs_for_sub_agent` (`spec_filter.py`)

서브 에이전트가 provider 에게 보는 `ToolSpec` 집합을 결정한다.

| 구분 | 도구 |
|---|---|
| **금지** | `call_sub_agent`·`call_sub_agents_parallel` (무한 재귀 방지 — L1) |
| **항상 허용** | `complete_subagent`(종료 규약) · `add_todo`/`complete_todo`(서브 자체 plan, sub_state 로 관리) |
| **화이트리스트** | `agent.meta.tools` 비어 있으면 금지 외 전체, 비어있지 않으면 그 목록만 |
| **자동 주입** | 에이전트 또는 학습 SKILL 에 `api_refs` 가 있으면 화이트리스트와 무관하게 `INFRASTRUCTURE_TOOL_NAMES`(8 메타 도구) + `ARTIFACT_IO_TOOL_NAMES`(list/load_artifact) 포함 |

보조: `_skills_require_runtime_tools`(활성 SKILL 중 api_refs 보유 여부) ·
`_inject_runtime_tools`(specs 에 없는 인프라 도구 추가) · `_resolve_agent_skills`(agent.meta.skills lazy load).

---

## 결과 포맷 — `result_format.py`

- **`_format_sub_agent_result(AgentReturnEvent)`** — 오케스트레이터 LLM 컨텍스트에 주입할
  구조화 텍스트. 헤더(`[agent 완료] summary`) + todo_log 있으면 단계별
  `[✓/✗/–] 설명: 요약`, 없으면 도구 호출 통계(`N건, 실패 X건`).
- **`_extract_task_summary(full_text, agent_name)`** — assistant 텍스트의 `Task Summary:`
  헤더를 파싱, 없으면 마지막 200자 폴백. (`complete_subagent` 미호출 시 안전망.)

---

## 중첩 위임 4중 방어선 {#중첩-위임-4중-방어선}

서브 에이전트가 다시 위임하는 무한 재귀를 4겹으로 막는다:

| 계층 | 위치 | 방식 |
|---|---|---|
| **L0** | `_dispatch_sub_agent` | 서브 turn 을 `agent_registry=None` 으로 실행 → `call_sub_agent` 분기 자체가 비활성. `_run_agent_turn` 시작 assert 가 이 계약을 못박음 |
| **L1** | `spec_filter._filter_specs_for_sub_agent` | 위임 도구 스펙을 LLM 시야에서 제거 (forbidden) |
| **L2** | `_dispatch_sub_agent` depth guard | `depth > MAX_AGENT_DEPTH` 이면 위임 거부 |
| **L3** | `tool_exec._execute_tool` | sentinel 도구가 실행 단계까지 흘러오면 명시적 에러 |
