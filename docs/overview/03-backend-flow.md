# ③ Backend 동작 흐름

> **대상 독자**: 백엔드 내부 구조를 처음 파악하는 개발자
> **이 문서의 목표**: 기동부터 채팅 한 턴이 처리되는 전 과정을 따라가며, 각 모듈의 역할과 등록된 도구를 파악한다.

---

## 1. 백엔드의 5가지 책임

`backend/`는 단순 API 서버가 아니라 데스크탑 앱의 **모든 서버 측 역할**을 겸한다.

| # | 책임 | 담당 모듈 |
|---|---|---|
| 1 | **정적 서빙** — Svelte SPA·산출물 파일 제공 | `main.py` (StaticFiles mount) |
| 2 | **HTTP API** — 채팅·설정·산출물·차트 REST/SSE | `api/` |
| 3 | **에이전트 하니스** — LLM ↔ 도구 실행 루프 | `agent/` |
| 4 | **생명주기** — 브라우저 연동 자동 기동·종료 | `core/browser.py` |
| 5 | **자동 업데이트** — 버전 확인·다운로드·자가 교체 | `core/updater.py` |

---

## 2. 기동 시퀀스 — EXE 더블클릭부터 첫 화면까지

`backend/main.py`가 엔트리포인트. 기동 순서:

```
① 소켓 바인딩      create_server_socket() — frozen은 APP_PORT 또는 APP_NAME 해시 기반 고정 포트 바인딩
                   (고정 포트로 재기동 후에도 localStorage origin 일치 → 대화 기록 보존)
                   같은 앱이 이미 실행 중이면 기존 탭을 열고 즉시 종료 (단일 인스턴스)
                   (TOCTOU 없음: 우리가 바인딩한 소켓을 uvicorn에 그대로 전달)
② 도구 자기등록     import agent.tools → @register_tool 데코레이터가 ToolRegistry 채움
③ 레지스트리 로드   PromptRegistry · SkillRegistry · AgentRegistry 메타 1회 로드
                   + AGENTS의 skills ↔ 실제 SKILLS 교차 검증 (불일치 시 부팅 경고)
④ 라우터 등록      /api/* — SPA catch-all보다 먼저 등록 (순서 중요)
⑤ 정적 mount      /workspace · /result · /assets · SPA fallback (build/web 존재 시)
⑥ 데몬 스레드      watchdog (생존 감시) + open_browser (기본 브라우저 자동 오픈)
⑦ server.run()    uvicorn 이벤트 루프 시작
```

dev 모드에서 `build/web/`이 없으면 ⑤의 SPA 서빙과 ⑥이 생략된다 — Vite dev server와
병행하는 경로로, 이때는 Ctrl+C로 종료한다.

---

## 3. 생명주기 — Presence & Watchdog

"브라우저 탭이 열려 있는 동안만 서버가 산다"를 구현하는 메커니즘.

```
브라우저                                 백엔드
   │  GET /api/presence  (SSE 연결 유지)   │
   ├────────────────────────────────────→ │ connect_client(id)  ← 연결 자체가 생존 신호
   │  ←  : ping  (30초마다)                │ (idle timeout 방지)
   │                                      │
   │  탭 닫힘 → EventSource 종료            │ disconnect_client(id)
   │                                      │   └ 2초 유예 (F5·새로고침 흡수)
   │                                      │ watchdog: 클라이언트 0명 감지
   │                                      │   └ SHUTDOWN_GRACE 후 server.should_exit = True
```

- 세션이 있으면 세션 ID로, 모든 세션을 지웠으면 `BROWSER_KEEPALIVE_ID`로 연결 →
  **세션 삭제와 서버 생존이 분리**된다 (탭이 열려 있는 한 서버 유지)
- 탭 복제(같은 세션 공유)는 연결 카운트로 관리 — 마지막 연결이 끊겨야 유예 진입
- 첫 연결 전에는 `STARTUP_GRACE`(60초)까지 기다림 (브라우저가 늦게 떠도 종료 안 함)

---

## 4. HTTP API 전체 지도

`backend/api/`의 라우터 7개. 모든 엔드포인트에 **Origin 가드**(`require_local_origin`)가
적용된다 — frozen EXE에서 외부 출처 요청을 차단하는 보안 경계 (dev는 Vite 프록시라 자동 통과).

| 메서드·경로 | 라우터 | 역할 |
|---|---|---|
| `POST /api/chat` | chat.py | **채팅 턴 실행** — SSE 이벤트 스트림 응답. `force_skills`(슬래시 커맨드) 지원 |
| `GET /api/conversation` | chat.py | 백엔드 보관 히스토리 조회 (검증용) |
| `DELETE /api/conversation` | chat.py | 세션 삭제 시 히스토리·상태 제거 |
| `POST /api/conversation/restore` | chat.py | 프론트 localStorage → 백엔드 컨텍스트 복원 (hydrate) |
| `GET /api/presence` | presence.py | SSE 생존 채널 (위 3절) |
| `GET /api/app-info` | settings.py | 앱 이름·버전 |
| `GET·POST /api/settings` | settings.py | LLM 설정 조회(키 마스킹)·부분 업데이트 |
| `GET /api/settings/providers` | settings.py | 가용 프로바이더 메타데이터 |
| `GET /api/settings/models` | settings.py | 프로바이더 모델 목록 (`{base_url}/models` 프록시) |
| `POST /api/settings/test` | settings.py | 연결 테스트 (저장 없이 ping) |
| `GET /api/skills` | skills.py | SKILL 목록 (슬래시 커맨드 자동완성용) |
| `GET /api/version` | update.py | 현재 버전 |
| `GET /api/update/check` | update.py | 저장소 latest.json 확인 (5분 캐시) |
| `POST /api/update/apply` | update.py | 업데이트 다운로드·검증·Updater 기동 |
| `GET /api/update/status` | update.py | 진행 상태 폴링 (downloading/verifying/…) |
| `POST /api/chart/filter` | chart.py | 차트 인터랙션 — exclude/legend/undo/redo/reset |
| `GET /api/chart/filter-state` | chart.py | 세션 재진입 시 필터 상태 복원 |
| `GET /api/artifact/preview` | artifact.py | parquet head(N) 미리보기 (데이터 칩 패널) |
| `GET /api/artifact/csv` | artifact.py | parquet → CSV 변환 다운로드 |
| `POST /api/artifact/reveal` | artifact.py | 산출물이 든 폴더를 OS 파일 탐색기에서 열기 (패널 '폴더 열기' 버튼) |

이외 정적 mount: `/` (SPA) · `/assets` · `/result` (산출물) · `/workspace` (도구 생성 파일).

---

## 5. 모듈 지도 — 파일별 역할

### `backend/core/` — 앱 기반 시설

| 파일 | 역할 |
|---|---|
| `config.py` | **모든 경로·포트의 단일 진실 공급원.** frozen/dev 분기(`_project_root`), presence 상수, `.env` 로드. 포트 바인딩은 `core.server_socket`이 담당 |
| `browser.py` | presence 연결 카운트(스레드 안전), watchdog, 브라우저 자동 오픈, 서버 종료 제어 |
| `result_store.py` | 산출물 폴더 슬롯 발급(`result/<세션>/<시각>/`), 경로 해석·containment 검증(`resolve_result_path`), 세션 manifest |
| `updater.py` | latest.json 확인(캐시·검증) → 다운로드 → sha256 → 스테이징 → Updater.exe 기동 |

### `backend/api/` — HTTP 경계

| 파일 | 역할 |
|---|---|
| `deps.py` | 공유 의존성 — Origin 가드, store 싱글톤 (conversation·state·settings) |
| `chat.py` | 채팅 SSE 스트리밍, 대화 복원/삭제, **동시 턴 가드**(같은 세션 중복 요청 즉시 거부) |
| `presence.py` | SSE 생존 채널 |
| `settings.py` | 설정 CRUD·모델 목록·연결 테스트 |
| `skills.py` | SKILL 카탈로그 노출 |
| `update.py` | 업데이트 4단계의 HTTP 노출 |
| `chart.py` | 차트 필터/레전드 액션 → 재렌더된 ECharts option 반환 |
| `artifact.py` | parquet 미리보기·CSV 변환 + 산출물 폴더 탐색기 열기 (데이터 칩 전용) |

### `backend/agent/` — 에이전트 하니스 (핵심)

| 파일/폴더 | 역할 |
|---|---|
| `harness.py` | **`run_turn()` — 한 턴의 전 과정 오케스트레이션.** provider↔도구 루프, sentinel 분기, 서브 에이전트 디스패치(순차/병렬), 루프 가드, 예산 관리, 영속화 |
| `guard.py` | 슬롯 가드 — 도구 인자 Pydantic 검증 후 **missing(사용자에게 질문) / invalid(LLM 자가수정)** 분기 |
| `models.py` | 전 데이터 모델 — Message·ToolCall·ToolResult·SSE 이벤트 13종·AgentState·TodoItem |
| `config.py` | 에이전트 한도 환경 변수 (반복 상한·예산·타임아웃·상태 파일 경로) |
| `providers/` | LLM 어댑터 — `openai.py`(OpenAI 호환+DTGPT, 재시도·스트림 잘림 대응), `mock.py`(시나리오 A~G), `factory.py`(설정→인스턴스) |
| `registries/` | 4종 레지스트리 (10절) |
| `stores/` | `conversation.py`(히스토리+와이어 규약 정합성), `agent_state.py`(todo·pending 디스크 영속) |
| `tools/` | 내장 도구 구현 (12절) |
| `runtime/` | 라이브러리 실행 인프라 — `evaluator.py`(안전 exec/eval), `namespace.py`(세션 변수 저장소+LRU spill), `resolver.py`(허용 라이브러리 import), `introspect.py`(시그니처 추출), `serialization.py` |
| `charts/` | `chart_spec.py`(선언적 spec 스키마), `chart_renderer.py`(parquet+spec→ECharts option), `chart_filter_store.py`(필터·레전드 undo/redo 스택) |

### `backend/settings/` — LLM 설정 저장소

| 파일 | 역할 |
|---|---|
| `models.py` | `LLMSettings` — 프로바이더별 설정 슬롯(`providers: dict`), 전환해도 이전 설정 보존 |
| `store.py` | settings.json 읽기/쓰기 (`threading.Lock`, 구 포맷 자동 마이그레이션) |
| `masking.py` | API 키 마스킹 단일 지점 (`sk-p••••••4f2a`) |
| `config.py` | settings.json 경로 (dev: `backend/settings/` / frozen: `%APPDATA%`) |

### `backend/scripts/` — 도메인 유틸 패키지

에이전트에 노출할 경량 Python 함수를 두는 곳 (`__init__.py` 필수). 현재는 Mock용
통계 함수(`stats.py`·`stats_df.py`)가 들어 있다. `APP_ALLOWED_LIBRARIES=scripts` +
SKILL의 `api_refs` 등록으로 노출하며, EXE 빌드 시 자동 번들링된다.

---

## 6. 채팅 한 턴의 처리 흐름 — `run_turn()`

사용자 입력 1건 = `run_turn()` 1회 = 완결된 응답 턴. 백엔드의 심장부다.

```
POST /api/chat {client_id, message, force_skills?}
  │
  ├─ [동시 턴 가드] 같은 세션이 이미 생성 중이면 즉시 거부 (ErrorEvent+DoneEvent)
  ▼
run_turn()
  ① 상태 로드        AgentState (todo·pending 슬롯) — 전부 종결된 todo는 리셋
  ② SKILL 선택       trigger 키워드 매칭 (또는 슬래시 커맨드 강제 지정)
  ③ 프롬프트 합성     PROMPTS + SKILL 본문 + 서브 에이전트 카탈로그
                     + 현재 To-do + Pending 슬롯 + Session Artifacts(과거 산출물 목록)
  ④ SkillActiveEvent → 프론트에 스킬 뱃지 즉시 표시
  ⑤ 에이전트 루프     _run_agent_turn() — 최대 APP_MAX_AGENT_ITERATIONS(8)회 반복
  │
  │    provider.astream(messages, tools)  ← LLM 호출 (스트리밍)
  │      ├─ delta            → 그대로 프론트에 중계 (실시간 타이핑)
  │      ├─ reasoning        → ReasoningEvent
  │      ├─ tool_call        → 분기 처리:
  │      │    ├─ 깨진 인자 JSON      → 에러 회신 → LLM 자가수정 (사용자 미개입)
  │      │    ├─ sentinel 도구      → 하니스가 직접 처리
  │      │    │    ├─ add_todo/complete_todo → 상태 갱신 + TodoUpdateEvent
  │      │    │    ├─ ask_user               → AskUserEvent + 턴 안전 종료
  │      │    │    ├─ call_sub_agent         → 서브 에이전트 순차 디스패치 (9절)
  │      │    │    └─ call_sub_agents_parallel → 병렬 디스패치 (9절)
  │      │    ├─ 슬롯 가드 검증
  │      │    │    ├─ 필수값 누락 → AskUserEvent (사용자에게 질문) + 안전 종료
  │      │    │    └─ 형식 오류   → 에러 회신 → LLM 자가수정
  │      │    └─ 일반 도구          → _execute_tool() (timeout 강제) → ToolResultEvent
  │      └─ done             → 도구 결과가 있으면 루프 계속, 없으면 종료
  │
  ⑥ 영속화           히스토리 append (tool 메시지는 800자 절단 저장) + 상태 저장
  │                  AskUser 없이 끝났으면 pending 상태 자동 클리어
  ⑦ DoneEvent        정확히 1회 보장 — 프론트 스트리밍 종료 신호
```

루프가 반복되는 이유: LLM이 "도구 호출 → 결과 확인 → 다음 행동 결정"을 여러 번
거치며 작업을 완성하기 때문. 상한(8회) 도달 시 그때까지의 결과로 **응급 응답(salvage)**을
만들어 반환한다 — todo가 모두 끝난 상태면 "완료(예산 소진)", 아니면 "미완료 주의"로 구분 표시.

---

## 7. SSE 이벤트 — 백엔드→프론트 스트리밍 프로토콜

한 턴 동안 백엔드가 흘려보내는 이벤트 종류. 프론트는 이 이벤트만으로 모든 UI를 그린다.

| 이벤트 | 발생 시점 | 프론트 반영 |
|---|---|---|
| `skill_active` | 턴 시작, 스킬 매칭 직후 | 스킬 뱃지 |
| `reasoning` | LLM 중간 판단 설명 | ReasoningBlock (접이식) |
| `delta` | 텍스트 토큰 생성 | 말풍선 실시간 타이핑 |
| `tool_call` | 도구 호출 시작 | 도구 카드 (running) |
| `tool_result` | 도구 완료/실패 | 도구 카드 종결 + 산출물 칩 생성 (`data` 페이로드) |
| `todo_update` | add_todo / complete_todo | TodoProgress 체크리스트 (전체 스냅샷) |
| `ask_user` | 사용자 입력 필요 | AskUserCard + 턴 중단 |
| `agent:switch` | 서브 에이전트 위임 시작 | 트레일 카드 생성 (`dispatch_id` 상관키 포함) |
| `agent:progress` | 서브 에이전트 내부 진행 | 트레일 내부 세그먼트 채움 |
| `agent:return` | 서브 에이전트 완료 | 트레일 종결 + 요약 표시 |
| `skill_complete` | todo 전원 종결 | SkillCompleteBadge |
| `error` | 오류·예산 소진 | 점선 박스 (복구됨=초록 / 미완료=빨강) |
| `done` | 턴 종료 (**정확히 1회**) | 스트리밍 종료, 완료 마커·소요시간 |

---

## 8. 오케스트레이터 라우팅 — Case 0~5

`AGENTS/`에 파일이 1개라도 있으면 메인 에이전트는 **오케스트레이터**로 동작하며,
`PROMPTS/orchestrator.md`의 결정론적 라우팅 규칙을 따른다.

| Case | 조건 | 행동 |
|---|---|---|
| **0** | 요청이 모호함 (대상·기간·의도 불명) | 도구 호출 전에 `ask_user`로 먼저 질문 |
| **1** | 일상 대화·단순 질문 | 도구 없이 즉시 텍스트 응답 |
| **2** | 사용자가 에이전트를 지명 ("분석 에이전트한테…") | 지명된 에이전트에게 즉시 위임 |
| **3** | SKILL 트리거 매칭 + 그 스킬 전담 에이전트 존재 | 해당 에이전트에게 **자동 위임** (직접 실행 금지) |
| **4** | SKILL 매칭됐지만 전담 에이전트 없음 | 오케스트레이터가 직접 도구 실행 |
| **5** | 모든 도구 호출이 끝난 마지막 응답 | "무엇을 했고 / 결과는 / 다음 행동은" 형식으로 완료 보고 |

Case 3가 이 구조의 핵심이다: **SKILL(무엇을) × AGENT(누가)**의 결정론 매핑으로,
LLM의 임의 판단이 아니라 설정 파일이 라우팅을 결정한다.

---

## 9. 서브 에이전트 위임 — 순차·병렬·격리

### 순차 위임 (`call_sub_agent`)

```
오케스트레이터 (depth 0)
  └─ call_sub_agent(agent_name, task)
       ├─ AGENTS/*.md 본문 lazy load → 서브 전용 system prompt
       ├─ 격리 컨텍스트 생성: 별도 messages + 별도 AgentState (메인 오염 없음)
       ├─ 서브 에이전트 자체 루프 실행 (자기 todo·도구 사용 가능)
       └─ complete_subagent(summary) → 요약+실행 로그가 오케스트레이터에 tool_result로 주입
```

### 병렬 위임 (`call_sub_agents_parallel`)

서로 독립적인 작업 여러 개를 **동시에** 실행한다 (의존성 있는 작업은 금지 — 순차 사용).

- task마다 `asyncio.create_task`로 디스패치 → 이벤트를 공유 큐로 fan-in → 여러 트레일이 인터리브 스트리밍
- `dispatch_id` 상관키로 같은 이름 에이전트가 동시에 떠도 프론트가 정확히 라우팅
- 동시 실행 수는 semaphore로 제한 (`APP_MAX_PARALLEL_SUBAGENTS`, 기본 3)
- 전원 완료 후 입력 순서대로 요약을 합쳐 **하나의 tool_result**로 복귀 (히스토리 정합성 유지)
- 병렬 작업 중 사용자 입력이 필요해진 작업은 그것만 '입력 필요'로 종료 보고 → 오케스트레이터가 순차로 재위임

### 안전 제약

| 제약 | 구현 |
|---|---|
| 서브가 다시 위임 불가 (무한 재귀 차단) | 4중 방어선 — 도구 스펙 제거·depth 검사·sentinel 거부·프롬프트 지침 |
| LLM 호출 총량 제한 | `TurnBudget` — 오케스트레이터+서브 합산 상한 (기본 20회) |
| 같은 에이전트 반복 위임 차단 | 3회 연속 위임 시 loop-guard 발동 |

---

## 10. 4개의 Registry — "정의 파일 → 런타임 객체"

마크다운/데코레이터로 정의된 것들을 런타임에 공급하는 계층. 모두
`backend/agent/registries/`에 있다.

| Registry | 원천 | 관리 대상 | 로딩 정책 |
|---|---|---|---|
| **PromptRegistry** | `PROMPTS/*.md` | 기반 system prompt 합성 (`compose()`) | 매 턴 읽기, dev는 mtime 핫리로드 |
| **SkillRegistry** | `SKILLS/*.md` | 트리거 매칭(`select()`), 슬래시 강제 지정(`get_by_names()`) | 메타 부팅 1회, 본문 첫 매칭 시 lazy |
| **AgentRegistry** | `AGENTS/*.md` | 서브 에이전트 카탈로그, Case 3 스킬→에이전트 매핑 | 메타 부팅 1회, 본문 위임 시 lazy |
| **ToolRegistry** | `@register_tool` 데코레이터 | 도구 스키마(LLM 노출)·검증기·실행 함수 | import 시 자기등록 (부팅 1회) |

공통 패턴: **메타데이터(Front Matter)는 가볍게 미리, 본문은 필요할 때 lazy** —
파일이 늘어나도 부팅 비용이 늘지 않는다.

---

## 11. 도구(Tool) 시스템 — 등록·검증·실행

### 등록: 파일 하나 = 도구 하나

`backend/agent/tools/`에 `.py` 파일을 만들고 데코레이터를 붙이면 부팅 시 자동 등록된다.

```python
@register_tool(
    description="매출 데이터를 기간으로 조회한다.",        # LLM에 노출되는 설명
    slot_prompts={"date_from": "조회 시작일을 알려주세요"},  # 누락 시 사용자에게 물을 문구
    timeout_seconds=15,                                  # 미지정 시 기본 30초
)
async def fetch_sales(
    date_from: Annotated[date, "조회 시작일"],   # Annotated 설명 → JSON Schema로 LLM 노출
    date_to: Annotated[date, "조회 종료일"],
) -> ToolResult:
    rows = await my_db.fetch_sales(date_from, date_to)
    return ToolResult(
        content=f"{len(rows)}행 조회",   # LLM 컨텍스트에 들어가는 요약
        data={"rows": rows},            # 프론트엔드로 전달 (칩·패널 페이로드)
    )
```

시그니처에서 Pydantic 모델이 자동 생성되어 **JSON Schema(LLM 노출)와 입력 검증**이
한 번에 만들어진다.

### 검증: 오류 책임자별 분기 (슬롯 가드)

도구 인자가 잘못됐을 때, **누구 잘못인지에 따라 처리가 다르다**:

| 오류 | 책임자 | 처리 |
|---|---|---|
| 필수 값 자체가 없음 (missing) | 사용자 | AskUserCard로 질문 → 답변 받으면 자동 재시도 |
| 값은 있는데 형식이 틀림 (`"오늘"` → date) | LLM | 도구 에러로 회신 → 같은 턴에서 LLM이 자가수정 |

### 실행 안전장치

- 모든 도구 호출에 `asyncio.wait_for` 타임아웃 강제 (초과 시 `[timeout]` 에러 반환)
- 동일한 잘못된 호출 반복 → loop-guard 차단 (단, 참조 파일이 수정된 재시도는 허용 — 파일 fingerprint 비교)
- `is_error=True` 결과에는 하니스가 원인 분석(RCA) 유도 메시지를 자동 첨부

### Sentinel 도구

`add_todo`처럼 **하니스가 직접 가로채 처리**하는 도구는 `sentinel=True`로 등록된다.
함수 본문은 절대 실행되지 않고, LLM의 "호출 신호" 역할만 한다.

---

## 12. Built-in 도구 카탈로그

새 도구를 추가하기 전부터 내장되어 있는 도구 전체. (인자 상세 → [docs/builtin-tools.md](../builtin-tools.md))

### 계획·상호작용 (Sentinel — 하니스가 직접 처리)

| 도구 | 사용 주체 | 역할 |
|---|---|---|
| `add_todo` | 공통 | 다단계 작업 계획 등록 → TodoProgress 표시. `tool_name` 지정 시 해당 도구 완료에 자동 연동 |
| `complete_todo` | 공통 | 단계 완료/실패/건너뜀 처리 + 한 줄 요약 |
| `ask_user` | 공통 | 사용자에게 보완 질문 (선택지/자유입력) + 턴 중단 |
| `activate_skill` | 공통 | 카탈로그의 SKILL을 런타임에 스스로 활성화 (트리거 미스 보완) |
| `call_sub_agent` | **오케스트레이터 전용** | 서브 에이전트 순차 위임 |
| `call_sub_agents_parallel` | **오케스트레이터 전용** | 독립 작업 동시 위임 (기본 3개 상한) |
| `complete_subagent` | **서브 에이전트 전용** | 결과 요약 반환 + 서브 턴 종료 |

### 산출물 저장·재발견 (항상 노출)

| 도구 | 방향 | 역할 |
|---|---|---|
| `save_artifact` | 쓰기 | 파일로 영속 — `kind`: markdown/json/text/**parquet**(+ png/svg/pdf/pptx/xlsx 바이너리). parquet·바이너리는 namespace 변수(`$df`)를 source로 받음 |
| `list_artifacts` | 읽기 | 현재 세션 산출물 목록 최신순 조회 (kind 필터, parquet은 행×열 요약) |
| `load_artifact` | 읽기 | `result/...` 파일을 namespace 변수로 복원 (save의 역방향) — 과거 산출물 이어서 분석 |

### 시각화 (아티팩트 패널로 전달)

| 도구 | 역할 |
|---|---|
| `display_image` | 이미지(들) 갤러리 표시 — 경로/URL/data URI |
| `display_chart` | parquet + 선언적 spec(`charts.spec.json`) → ECharts 인터랙티브 차트 (14절 파이프라인) |
| `display_markdown` | 저장된 `.md` 보고서를 패널에 렌더링 |

### 라이브러리 런타임 메타 도구 (8종 — `api_refs` 활성 시 자동 노출)

SKILL/AGENT에 `api_refs`가 있으면 자동 주입된다. 외부 Python 라이브러리를 wrapper 없이
동적으로 쓰게 하는 인프라.

| 도구 | 역할 |
|---|---|
| `inspect_callable` | 함수/클래스 시그니처 + docstring 조회 |
| `list_module_members` | 모듈 public 멤버 목록 |
| `call_function` | 라이브러리 함수 실행 → 결과를 namespace 변수로 저장 (`$var` 치환 지원) |
| `eval_expression` | 단일 식 평가 (namespace 변수 참조 가능) |
| `exec_code` | 다중 statement 코드 실행 — import·할당·제어흐름·stdout 캡처, `artifact_dir()` 헬퍼 주입 |
| `list_namespace` | 세션 변수 목록 요약 |
| `describe_variable` | 변수 상세 (DataFrame shape, ndarray 통계 등) |
| `delete_variable` | 변수 삭제 |

### 데모

| 도구 | 역할 |
|---|---|
| `now` | 현재 시각 ISO 8601 반환 (등록 패턴 예시 겸용) |

### 도구 노출 규칙 요약

```
오케스트레이터  = 전체 도구 − complete_subagent
서브 에이전트   = tools 화이트리스트 (비어 있으면 전체) − 위임 도구
항상 노출       = list_artifacts · load_artifact (화이트리스트 무관)
조건부 자동 주입 = 메타 도구 8종 (api_refs 있을 때, 화이트리스트 무관)
```

---

## 13. 산출물(Artifact) 파이프라인 — 세션을 넘는 데이터 영속

에이전트 작업 결과가 휘발되지 않고 **다음 턴·다음 세션에서 재사용**되는 구조.

### 저장 구조

```
result/
└─ <세션제목>-<id 앞8자>/          ← 세션 단위
    ├─ _artifacts.jsonl           ← 세션 manifest (산출물 장부)
    └─ <YYYYMMDD-HHmmss>/         ← 턴 단위 슬롯
        ├─ data.parquet           ← 데이터 (표준 포맷)
        ├─ charts.spec.json       ← 차트 선언
        ├─ charts.json            ← 렌더된 ECharts option
        └─ report.md              ← 보고서
```

### 두 종류의 작업 메모리

| 저장소 | 수명 | 용도 |
|---|---|---|
| **세션 namespace** (메모리+spill) | 브라우저 연결 동안 | `exec_code`·`call_function`의 변수 (DataFrame 등). 상한 초과분은 디스크로 spill 후 재참조 시 부활 |
| **result/ 디스크** | 영구 | `save_artifact`로 영속화한 파일. **세션 간 재사용의 정식 경로** |

### 재발견 루프 — "지난번 그 데이터로 이어서"

```
① 저장   save_artifact / exec_code의 artifact_dir() → manifest에 자동 기록
② 노출   매 턴 system prompt에 "# Session Artifacts" 섹션으로 최근 산출물 목록 주입
         → 대화 히스토리가 잘려도 LLM이 과거 산출물의 존재를 안다
③ 재사용  list_artifacts(목록) → load_artifact(path, store_as="df") → exec_code로 후속 분석
         (재표시만 필요하면 display_* 에 경로 직접 전달)
```

모든 경로 해석은 `resolve_result_path` 한 곳으로 일원화 — `result/` 밖 접근을
차단(containment)하고, frozen EXE의 작업 디렉터리 함정을 회피한다.

### 코드 실행 보안 모델 (`evaluator.py`)

단일 사용자 로컬 데스크탑 앱 위협 모델에 맞춘 가드 (완전한 sandbox가 아님 — LLM 실수·폭주 방지용):

- **차단**: `exec`/`eval`/`compile`(재귀 인젝션), `os`·`sys`·`subprocess`·`socket`·`shutil`(시스템·외부 통신)
- **허용**: 그 외 builtin 전부 + stdlib 안전 목록 + `APP_ALLOWED_LIBRARIES` 등록 패키지

---

## 14. 차트 파이프라인 — 선언적 spec과 인터랙션

`display_chart`는 "이미지 생성"이 아니라 **데이터(parquet)와 선언(spec)을 분리**해
렌더링하는 파이프라인이다. 덕분에 사후 필터링·레전드 편집이 가능하다.

```
생성 (에이전트)                          상호작용 (사용자)
① save_artifact(parquet)  데이터        ⑤ 라이트박스에서 brush 선택 / 레전드 편집
② save_artifact(spec)     차트 선언      ⑥ POST /api/chart/filter
③ display_chart(spec 경로)              ⑦ ViewState 스택에 변경 push (undo/redo 가능)
④ 렌더러가 parquet 로드                  ⑧ 렌더러가 제외 행·레전드 반영해 재렌더
   → charts.json (ECharts option)          → charts.json 갱신 → 그리드·라이트박스 동시 반영
```

- spec은 mark(bar/line/scatter/box/histogram/heatmap/ecdf) × encoding(x/y/color) 선언 —
  Vega-Lite 류의 축소판 (`ChartSpecV1`)
- 필터·레전드 변경은 `charts.filter.json` 사이드카에 **단일 undo/redo 스택**으로 영속 —
  세션 재진입 후에도 복원·되감기 가능
- 데이터 원본(parquet)은 불변 — 필터는 row id 제외 목록일 뿐이라 Reset/Undo로 언제든 원복

---

## 15. 안전장치 모음 (요약)

실 LLM의 비결정성·실패에 대비한 방어선들. (상세: `.claude/rules/harness_resilience.md`)

| 분류 | 장치 | 효과 |
|---|---|---|
| 입력 경계 | Origin 가드 + 루프백 고정 | 외부 네트워크에서 API 접근 불가 |
| 입력 경계 | 동시 턴 가드 | 같은 세션 중복 요청 → 히스토리 교차 오염 방지 |
| LLM 오류 | 슬롯 가드 책임자 분기 | 사용자 질문 최소화, LLM 실수는 자가수정 유도 |
| LLM 오류 | 깨진 tool_call JSON 마커 | 스트림 잘림 시에도 원본 보존 → 재요청 |
| 폭주 방지 | 반복 상한(8) · 턴 예산(20) · loop-guard | 무한 루프·비용 폭주 차단 |
| 폭주 방지 | 도구 타임아웃 (기본 30초) | 도구 1회가 턴을 영원히 잡지 못함 |
| 네트워크 | provider 재시도 (지수 백오프) | 일시 오류(429·연결 끊김) 자동 복구 |
| 정합성 | tool 쌍 보존 트리밍 + placeholder | OpenAI 와이어 규약 위반(400 거부) 방지 |
| 정합성 | 실패 턴 영속 + DoneEvent 보장 | 예외가 나도 턴이 증발하지 않고 스트림이 닫힘 |
| 비밀 보호 | 에러 메시지 안전화 · API 키 마스킹 | 키·URL이 사용자 화면에 노출되지 않음 |

---

## 16. 설정 시스템 — settings.json & Provider Hot-swap

```
settings.json (dev: backend/settings/ · frozen: %APPDATA%\{APP_NAME}\)
{
  "provider": "dtgpt",                          ← 현재 활성
  "providers": {                                ← 프로바이더별 슬롯 (전환해도 보존)
    "dtgpt":             {"model": "...", "api_key": "...", "base_url": ""},
    "openai_compatible": {"model": "...", "api_key": "...", "base_url": "https://..."}
  }
}
```

- **Hot-swap**: `/api/chat` 요청마다 최신 설정을 읽어 provider 인스턴스를 즉석 생성 —
  서버 재시작 없이 모델·프로바이더 전환이 다음 메시지부터 적용
- 생성 파라미터(temperature 등)는 settings.json이 아니라 환경 변수로만 제어 (UI 비노출)
- API 키는 응답에서 항상 마스킹, 브라우저 저장 금지

---

## 17. 정리 — 백엔드를 한 장으로

```
기동      main.py → 동적 포트 → 레지스트리 로드 → 브라우저 오픈
생존      presence SSE = 생존 신호, 탭 닫으면 watchdog이 자가 종료
한 턴     /api/chat → run_turn → [SKILL 선택 → 프롬프트 합성 → LLM↔도구 루프] → SSE 스트림
위임      오케스트레이터 → call_sub_agent(순차) / call_sub_agents_parallel(병렬, 격리 실행)
도구      @register_tool 자동 등록 + sentinel + 슬롯 가드 + 타임아웃
산출물    save → manifest → 프롬프트 노출 → list/load 로 세션 넘어 재사용
안전      Origin·동시 턴·예산·loop-guard·재시도·히스토리 정합성·키 마스킹
```

**이전 문서**: [① 프로젝트 전체 흐름](01-project-overview.md) · [② 구현된 UX/UI](02-ux-ui.md)
