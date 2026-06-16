# system prompt 조립 — `prompt/`

`run_turn` 이 매 턴 system prompt 를 동적으로 합성하는 서브패키지. 오케스트레이터/서브
에이전트/단층 세 경로를 공통 섹션 렌더러로 조립한다.

| 모듈 | 역할 |
|---|---|
| `compose.py` | 세 경로의 최종 조립 (`_compose_orchestrator_system_prompt`·`_compose_sub_agent_system_prompt`·`_compose_system_prompt`) |
| `sections.py` | 공통 섹션 렌더러 (비활성 SKILL 카탈로그·멀티스킬·To-do·Pending Slot) — 모두 `str \| None` 순수 함수 |
| `artifacts.py` | `_render_session_artifacts_section` — 세션 manifest 기반 과거 산출물 목록 |
| `api_refs.py` | `_render_skills_api_refs`·`_collect_agent_api_refs_section` — api_refs → ApiDoc 섹션 |
| `wind_down.py` | `_build_wind_down_message` — 반복 예산 임박 마무리 지시문 (R7) |

`base` prompt 자체(`PROMPTS/base.md` + `safety.md` (+ `orchestrator.md`))는
`PromptRegistry.compose()` 가 만든다 — 그 합성·핫리로드 정책은
[docs/guides/prompts.md](../guides/prompts.md) 참고. 본 서브패키지는 그 base 뒤에
**런타임 상태**(SKILL 본문·todo·산출물·카탈로그)를 이어 붙인다.

---

## 세 경로 — `compose.py`

### `_compose_orchestrator_system_prompt` (AGENTS 보유 시)

```
base (+orchestrator.md +사용자 지침)
+ 활성 SKILL 본문 (# Skill: <name>)
+ 비활성 SKILL 카탈로그        _render_inactive_skill_catalog  → activate_skill 유도
+ 멀티 스킬 실행 지침          _render_multi_skill_instruction (2개+ 활성 시)
+ 현재 To-do                  _render_todo_section
+ Session Artifacts           _render_session_artifacts_section
+ Pending 슬롯                Pending Sub-Agent Slot > Pending Slot > Pending User Question (우선순위)
+ 가용 서브 에이전트 카탈로그   + ## Case 3 결정론 매핑 (skill→agent)
+ Library API 섹션            _render_skills_api_refs (활성 SKILL api_refs)
```

서브 에이전트 카탈로그는 각 에이전트의 `description`/`role`/`goal`/`when_to_delegate`/전담
스킬을 나열하고, `skills` 가 있으면 **Case 3 결정론 매핑**("'X' 트리거 → 반드시 `agent`
에게 위임")을 덧붙여 LLM 임의 판단이 아니라 설정이 라우팅을 결정하게 한다.

### `_compose_sub_agent_system_prompt`

`base`(orchestrator.md 제외) + `# 당신은 '<name>' 서브 에이전트입니다`(role/goal + 본문) +
학습 SKILL 본문 + 에이전트·SKILL api_refs 섹션 + **종료 규약**(`complete_subagent` 반드시
호출). `call_sub_agent` 도구는 spec 에서 제거돼 LLM 시야에 없다.

### `_compose_system_prompt` (단층 — AGENTS 부재 하위호환)

오케스트레이터 카탈로그·Case 3 없이: base + SKILL 본문 + 비활성 카탈로그 + 멀티스킬 +
todo + 산출물 + Pending Slot. `agent_registry` 가 None 일 때만 쓰인다.

---

## 공통 섹션 — `sections.py`

| 함수 | 출력 |
|---|---|
| `_render_inactive_skill_catalog` | **# 가용 SKILL 카탈로그 (비활성)** — 활성화되지 않은 SKILL 의 이름·설명·예시 트리거를 나열하고 "의미가 맞으면 `activate_skill(name=...)` 으로 활성화하라"고 안내. `activate_skill` 능동 활성화 경로의 원천(→ [call-handlers.md](call-handlers.md#activate_skill--동적-프롬프트-재조립)) |
| `_render_multi_skill_instruction` | 2개 이상 SKILL 동시 활성 시 — `add_todo` 로 단계 등록 후 단계마다 `complete_todo` 강제 |
| `_render_todo_section` | **# 현재 To-do** — `[status] (task_id) 설명` 목록 |
| `_render_pending_slot` | **# Pending Slot** — 직전 턴 AskUser 응답 재개 유도 (pending_tool + missing_slots 있을 때) |

---

## Session Artifacts — `artifacts.py`

`_render_session_artifacts_section(limit=10)` 가 세션 manifest(`_artifacts.jsonl`)에서 최근
N개 산출물을 읽어 **# Session Artifacts** 섹션으로 주입한다(경로·kind·shape·설명 80자).
대화 히스토리가 잘려도 LLM 이 과거 parquet 경로를 알 수 있게 하는 진실원천(→
[.claude/rules/agent_runtime.md](../../.claude/rules/agent_runtime.md) 의 manifest 절). 빈 세션이면 "".

## api_refs 섹션 — `api_refs.py`

`api_refs` 가 선언된 SKILL/AGENT 의 함수 시그니처+docstring 을 introspect 로 수집해
ApiDoc 섹션으로 렌더한다. `_render_skills_api_refs`(활성 SKILL 들) ·
`_collect_agent_api_refs_section`(에이전트 + 학습 SKILL). 라이브러리 런타임 상세는
[docs/guides/library-runtime.md](../guides/library-runtime.md).

## wind-down 지시문 — `wind_down.py`

`_build_wind_down_message(remaining_calls)` 가 남은 호출 수에 따라 마무리 지시문을
생성한다(R7). 잔여 2+ 면 "새 분석 금지·저장된 산출물 즉시 표시·다음 응답은 도구 없이
요약", 잔여 1 이면 "도구 호출 금지·최종 답변 작성". `loop._maybe_inject_wind_down` 이
`messages` 에만 1회 주입한다(→ [turn-loop.md](turn-loop.md)).
