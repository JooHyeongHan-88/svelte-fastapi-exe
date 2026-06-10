# 백엔드 아키텍처

## PyInstaller frozen 경로 분기

`backend/core/config.py`의 `_project_root()`가 모든 경로의 단일 진실 공급원.

| 모드 | 루트 | 정적 자산 | Updater |
|---|---|---|---|
| frozen EXE | `sys._MEIPASS` | `MEIPASS/web` | `MEIPASS/updater/Updater.exe` |
| dev | 프로젝트 루트 | `build/web/` | — |

> **새 정적 자산을 추가할 때** → `packaging/App.spec`의 `datas`에도 등록 필수.  
> `PROMPTS/`, `SKILLS/`, `AGENTS/` 는 디렉터리 단위로 이미 등록됐으므로 파일 추가만으로 다음 빌드에 반영된다.
>
> **`backend/scripts/` 패키지**: `backend/` 가 PyInstaller `pathex` 에 포함되므로 `scripts/` 는 일반 Python 패키지(`__init__.py` 필수)로 자동 인식된다. `App.spec` 이 `collect_submodules('scripts')` 를 실행하므로 파일을 추가하면 다음 빌드에서 자동 번들링된다.
>
> **`APP_ALLOWED_LIBRARIES` 자동 번들링**: `App.spec` 이 빌드 시 `.env` 의 `APP_ALLOWED_LIBRARIES` 를 읽어 각 패키지에 `collect_all()` 을 실행한다. `.env` 한 줄 추가만으로 dev 런타임과 EXE 번들 양쪽에서 동시 사용 가능.

---

## App 생명주기 (EXE 기동 시)

1. `backend/main.py` → `uvicorn.Config + Server` 생성, `browser.server`에 보관  
   (Windows `os.kill(SIGTERM)`은 lifespan shutdown을 실행하지 않으므로 `server.should_exit = True` 경로만 사용)
2. watchdog + open_browser 데몬 스레드 시작 → `server.run()`
3. 브라우저 로드 → `initApp()`이 localStorage에서 세션 복원  
   - 세션이 있으면 활성 세션 ID로, 없으면 `BROWSER_KEEPALIVE_ID`로 `/api/presence` EventSource 오픈
4. `browser.connect_client(id)` 호출 — 연결 유지 = 생존 신호. `KEEPALIVE_INTERVAL`(30s)마다 `: ping`으로 idle timeout 방지
5. 탭 닫기 → EventSource 종료 → `finally`에서 `browser.disconnect_client` → `PRESENCE_RECONNECT_GRACE`(2s) 후 실제 제거
6. `browser.watchdog`이 클라이언트 부재 감지 → `SHUTDOWN_GRACE` 경과 시 `server.should_exit = True`

### Presence 설계 원칙

`presenceSource`는 탭당 1개. 세션이 있으면 해당 세션 ID, 없으면 `BROWSER_KEEPALIVE_ID`로 연결한다.  
세션 삭제와 서버 생존을 분리함으로써 **모든 세션을 삭제해도 브라우저가 열려 있는 한 서버는 유지**된다.

```
세션 있음  → openPresence(sessionId)
세션 전부 삭제  → openPresence(BROWSER_KEEPALIVE_ID)   ← 서버 종료 방지
탭 닫기  → EventSource 자동 종료 → disconnect → watchdog → shutdown
```

---

## 동시성 모델

`backend/core/browser.py`의 `_connections: dict[str, int]`과 `_pending_disconnects: dict[str, threading.Timer]`는  
**uvicorn event-loop · watchdog 스레드 · `threading.Timer` 콜백** 3곳에서 동시 접근한다.

- 모든 read/write는 `_lock` 안에서 수행
- 순회는 `_snapshot()`이 `dict`를 락 안에서 스냅샷한 뒤 락 밖에서 처리
- `Timer.cancel()` / `Timer.start()`는 자체 락을 가지므로 우리 `_lock` **밖**에서 호출 (lock ordering 준수)
- 탭 복제(같은 client_id 공유) 대응: `_connections` 값을 카운트로 관리 — 마지막 연결이 끊겨야 grace 진입
- `_ever_registered` 플래그로 "최초 연결 이전 STARTUP_GRACE 대기"와 "연결 후 비어있음(SHUTDOWN_GRACE)"을 구분

---

## Origin 가드 (보안 경계)

`backend/api/deps.py`의 `require_local_origin` 의존성이 router 레벨에 적용된다.

- **frozen(EXE)** 에서만 활성. dev는 Vite proxy 때문에 origin이 달라 자동 패스.
- `Origin` 헤더 있으면 `ALLOWED_ORIGIN`(`http://{HOST}:{실제 바인딩 포트}`)과 일치 확인.
  포트는 기동 시 OS 가 동적 할당하므로(`create_server_socket` → `set_runtime_port`),
  `deps.py` 는 import 스냅샷이 아니라 `config.ALLOWED_ORIGIN` 을 매 요청 참조한다.
- 없으면 `sec-fetch-site`가 `same-origin` / `none` 이어야 통과

---

## 에이전트 설계 원칙

이 프로젝트의 에이전트는 **미리 등록된 Python API 도구를 plan에 따라 실행**하는 역할이다.
코드를 작성하거나 파일을 편집하는 AI 코딩 어시스턴트가 아님을 항상 염두에 둘 것.

- 에이전트는 일반 질문에 텍스트로 답하거나, `add_todo` 로 plan 수립 후 tool 순차 실행.
- 오케스트레이터는 복잡한 작업을 `call_sub_agent` 로 서브 에이전트에게 위임.
- **서브 에이전트는 병렬·백그라운드 실행 없음** — 항상 순차적으로 결과가 반환될 때까지 대기.

---

## 에이전트 하니스 구조

`backend/agent/harness.py`의 `run_turn()` 한 번 = 사용자 입력 1건에 대한 완전한 응답 턴.

```
run_turn(client_id, user_message, *, agent_registry, force_skills=None, ...)
   │
   ├─ state_store.get(client_id)          → AgentState (todo / missing_slots)
   ├─ force_skills ? get_by_names()       → SKILLS body lazy load
   │            : skill_registry.select() → trigger / name 매칭
   ├─ PromptRegistry.compose()            → PROMPTS/base.md + safety.md (+ orchestrator.md)
   │
   ├─ agent_registry 있으면
   │    └─ _compose_orchestrator_system_prompt() → base + skills + 에이전트 카탈로그 + state
   │  없으면 (하위호환 단층 모드)
   │    └─ _compose_system_prompt()              → base + skills + state
   │
   ├─ yield SkillActiveEvent              → 프론트 뱃지 즉시 표시
   │
   └─ _run_agent_turn(depth=0) — 공통 provider→tool 루프
        ├─ delta           → yield 그대로 전달
        ├─ tool_call 분기
        │    ├─ MALFORMED_TOOL_ARGS_KEY   → ToolResultEvent(is_error) → LLM self-correct
        │    ├─ add_todo / complete_todo  → AgentState 직접 갱신 + TodoUpdateEvent
        │    ├─ call_sub_agent            → _dispatch_sub_agent (순차 실행)
        │    │    └─ AgentSwitch → AgentProgress×N → AgentReturn
        │    ├─ call_sub_agents_parallel  → _dispatch_parallel_sub_agents (동시 실행)
        │    │    └─ N개 _dispatch_sub_agent 인터리브 → 단일 통합 tool_result
        │    ├─ 슬롯 가드(validate_tool_args)
        │    │    ├─ invalid_message      → ToolResultEvent(is_error) → LLM self-correct
        │    │    └─ missing 슬롯         → AskUserEvent + 안전 종료
        │    └─ 정상 도구               → _execute_tool + ToolResultEvent
        └─ done → break
   │
   ├─ AskUser 없이 완료 → pending_tool/missing_slots/pending_sub_agent 자동 클리어
   └─ store.append(turn_messages) + state_store.set + DoneEvent
        └─ turn_messages 의 tool 메시지는 800자 truncation 후 히스토리 저장
```

### AgentRegistry — 서브 에이전트 카탈로그 (`AGENTS/`)

`backend/agent/registries/agents.py`의 `AgentRegistry` 가 `AGENTS/*.md` 를 관리.

- 부팅 시 Front Matter(`name` / `description` / `skills` / `tools` / `priority`)만 파싱.
- 본문(페르소나)은 `call_sub_agent` 위임 시점에 `_ensure_body()` 로 lazy load.
- `skills` 에 SKILLS 이름 등록 → 해당 트리거 매칭 시 오케스트레이터가 자동 위임 (Case 3 결정론 매핑).
- `tools` 비어 있으면 에이전트에게 전체 도구 노출. 채워져 있으면 화이트리스트만.
- `agent_registry` 가 `None` 이거나 빈 경우 → 단층 동작 (하위호환, SKILLS 직접 라우팅).
- `TurnBudget`: 오케스트레이터 + 모든 서브 에이전트 provider 호출 합산 상한 (`max_agent_calls`, `APP_MAX_AGENT_CALLS_PER_TURN`, 기본 10). 같은 서브 에이전트 3회 연속 위임은 `loop-guard` 로 차단.

### 병렬 서브 에이전트 디스패치 (`_dispatch_parallel_sub_agents`)

`call_sub_agents_parallel(tasks=[{agent_name, task}, ...])` sentinel 을 오케스트레이터가
호출하면 독립 작업들을 **동시에** 실행한다. 순차 경로(`call_sub_agent`)는 그대로 두고
신규 분기/함수로만 추가됐다.

- **이벤트 fan-in**: task 마다 `asyncio.create_task` 로 producer 코루틴을 띄워 각자
  `_dispatch_sub_agent` 를 실행하고, 이벤트를 공유 `asyncio.Queue` 로 흘려보낸다. 소비
  루프가 큐에서 꺼내 그대로 yield 하므로 여러 트레일의 AgentSwitch/Progress/Return 이
  인터리브되어 스트리밍된다.
- **dispatch_id 상관키**: 각 task 는 `{call.id}::p{i}` 를 dispatch_id 로 받고, 그 디스패치가
  emit 하는 모든 `agent:*` 이벤트에 실린다. 같은 이름 에이전트를 둘 이상 동시에 띄워도
  프론트가 정확한 트레일로 라우팅한다 (`AgentSwitch/Progress/Return.dispatch_id`).
- **단일 통합 tool_result**: 전원 완료 후 입력(task) 순서대로 요약을 합쳐 **하나의**
  tool_result 로 append 한다. call ↔ tool_result 1:1 쌍이 유지되므로 히스토리 정합성
  로직(F1a 쌍 보존 · F1b balancing · F7 truncation)을 건드리지 않는다.
- **ask_user abort**: 병렬 작업 중 서브가 사용자 입력이 필요해지면(`ask_user_mode="abort"`)
  AskUserEvent 를 사용자에게 노출하지 않고 그 작업만 '입력 필요' 에러 요약의 AgentReturn 으로
  변환한다. orchestrator pending 은 건드리지 않으며, 오케스트레이터가 결과를 보고 `call_sub_agent`
  로 순차 재위임한다 (병렬은 사용자 미개입 · 독립 작업 전용).
- **동시성 상한 · 가드**: `asyncio.Semaphore(APP_MAX_PARALLEL_SUBAGENTS, 기본 3)` 로 동시
  실행 수를 제한한다. `TurnBudget` 합산 상한은 그대로 적용되지만, 의도된 동시성이므로 같은-
  에이전트-연속-호출 가드(`check_dispatch`)는 `skip_consecutive_guard=True` 로 건너뛴다.
- **취소 정리**: 소비 루프가 취소되면(ESC·탭 종료) `finally` 가 모든 producer task 를
  `cancel()` 후 `gather(return_exceptions=True)` 로 회수해 고아 task 를 남기지 않는다.
- depth: 병렬도 오케스트레이터(depth 0)에서만 발생하고 각 서브는 `agent_registry=None`(L0)
  으로 실행돼 중첩 위임이 차단된다. `SUB_AGENTS_PARALLEL_DISPATCH` 는 `_filter_specs_for_sub_agent`
  의 forbidden 에 포함돼 서브 에이전트 시야에서 제거된다.

### 라이브러리 런타임 인프라 도구 (8개)

`backend/agent/tools/runtime.py` 에 등록된 메타 도구들. SKILL/AGENT 에 `api_refs` 가 있으면 harness 가 자동 주입.

| 도구 | 역할 |
|---|---|
| `inspect_callable` | 함수/클래스 시그니처 + docstring 조회 |
| `list_module_members` | 모듈의 public 멤버 목록 |
| `call_function` | 라이브러리 함수 실행 → namespace 저장 (`$varname` 치환 지원) |
| `eval_expression` | 단일 Python 식 평가 (namespace 변수 참조 가능) |
| `exec_code` | 다중 statement 코드 실행 (import·할당·제어흐름·stdout 캡쳐) |
| `list_namespace` | 세션 namespace 변수 목록 요약 |
| `describe_variable` | 변수 타입별 상세 요약 (DataFrame shape, ndarray min/max 등) |
| `delete_variable` | namespace 변수 영구 삭제 |

> `exec_code` scope 에는 `artifact_dir()` 헬퍼가 주입된다 — 이번 턴 산출물 폴더(`Path`)를 반환해 라이브러리가 파일을 직접 쓰게 한다. `run_in_executor` 가 contextvars 를 전파하지 않으므로 `_ArtifactDirProvider` 가 생성 시점에 client_id/title/슬롯을 캡처하고, 실행 후 `adopt_turn_slot` 으로 메인 턴 캐시에 역동기화한다 (같은 턴 `save_artifact` 와 폴더 공유). `artifact_dir` 은 예약어로 namespace 저장에서 silent skip.

### 산출물 재발견·재사용 도구 (always-exposed)

`backend/agent/tools/artifact_io.py` — `list_artifacts`/`load_artifact` (`ARTIFACT_IO_TOOL_NAMES`). 인프라 메타 도구와 달리 `api_refs` 조건과 무관하게 **항상 노출**된다 (markdown 재표시 등 라이브러리 런타임 없이도 필요). 서브 에이전트 화이트리스트 우회는 `_filter_specs_for_sub_agent` 에서 `INFRASTRUCTURE_TOOL_NAMES | ARTIFACT_IO_TOOL_NAMES` 로 처리. 모든 경로 해석은 `core.result_store.resolve_result_path` (RESULT_DIR 절대 기준 + containment) 로 일원화 — frozen EXE 의 CWD 함정 회피.

### 세션 manifest + Session Artifacts 프롬프트 섹션

`save_artifact` 성공 시 세션 루트의 `_artifacts.jsonl` 에 한 줄 append (`append_manifest_entry`, OSError 는 삼킴). `run_turn` 의 시스템 프롬프트 합성이 `_render_session_artifacts_section` 으로 최근 N개(기본 10) 산출물을 `# Session Artifacts` 섹션으로 주입한다 (manifest 우선, 없으면 디스크 스캔 fallback). **세션 복원이 tool 메시지를 버려도**(OpenAI 와이어 규약상 고아 tool 메시지 복원 불가) 디스크 manifest 가 진실원천이라 과거 산출물 재발견이 끊기지 않는다.

### namespace LRU spill (휘발성 완화)

`APP_NAMESPACE_MAX_VARS` 초과 시 가장 오래된 변수를 **삭제하지 않고** 디스크로 spill 후 `_entries` 에서 deregister 한다 (`namespace._evict_if_needed`). 요약 크기는 bounded 로 유지되면서 같은 이름 재참조 시 lazy 재색인으로 부활한다. `__init__` 의 eager 재색인은 crash 복구용. `cleanup` 은 `disk_dir` 전체 rmtree (spill-후-deregister 파일 누수 방지). 단, presence 단절 2초 후 `cleanup_namespace` 가 디렉터리째 삭제하는 의도적 휘발 설계는 그대로 — **세션 간 영속의 정식 경로는 save→load_artifact** 이다.

**evaluator 보안 모델** (`backend/agent/runtime/evaluator.py`): 단일 사용자 로컬 데스크탑 앱 위협 모델에 맞게 완화됨.
- **차단**: `exec`, `eval`, `compile` (재귀 인젝션 방지), `__import__` 직접 무제한 사용
- **허용**: 그 외 모든 public builtin (`open`, `print`, `getattr`, `vars`, `dir`, `iter`, `next`, ...)
- **import 허용 목록**: stdlib 안전 목록(`math`, `statistics`, `json`, `datetime`, `pathlib`, `re`, `collections` 등) + `APP_ALLOWED_LIBRARIES`
- **차단 목록**: `os`, `sys`, `subprocess`, `socket`, `shutil` (시스템·외부통신 — runaway 방지)
- 진정한 sandbox 가 아님. dunder 우회를 완전히 막지는 않음. LLM 실수·runaway 방지 가드.

### Tool 등록 패턴 (`agent/tools/`)

새 사내 API 를 도구로 노출하려면 `backend/agent/tools/` 에 새 `.py` 파일을 만들고 `@register_tool` 데코레이터를 붙인 async 함수를 작성하면 끝. 부팅 시 `agent/tools/__init__.py` 가 모든 서브모듈을 import 해 데코레이터의 부수효과로 `_REGISTRY` 가 채워진다.

- **시그니처에서 자동 스키마 생성**: 각 파라미터의 `Annotated[T, "설명"]` 을 Pydantic `create_model` 로 묶어 JSON Schema (LLM 노출) + `TypeAdapter` (입력 검증) 를 1회 생성. 매 turn 재생성 없음.
- **오류 책임자별 분기 가드**: `validate_tool_args` 가 두 경로로 나눈다 — (1) `type=="missing"`(값 부재) → `MissingSlot`→`AskUserEvent` 로 사용자에게 재질문, (2) 그 외 형식/타입/enum 위반(`date_from="오늘"`, 문자열 자리 dict 등 값은 줬는데 모양이 틀림) → `SlotCheckResult.invalid_message` 로 LLM 에 도구 에러를 회신해 같은 루프 안에서 self-correct 유도(사용자 미개입). 둘이 동시면 invalid 경로가 누락 항목까지 함께 안내. 동일 잘못된 호출 반복은 `history_calls` loop-guard 가 차단.
- **중첩 Pydantic 모델 인자**: `_execute_tool` 이 `model_validate` 후 `{name: getattr(parsed, name) for name in type(parsed).model_fields}` 로 kwargs 를 추출한다. `model_dump()` 를 쓰면 `list[ImageItem]` 같은 중첩 모델이 `list[dict]` 로 직렬화돼 도구 함수의 타입 기대와 불일치한다 — **절대 `model_dump()` 로 바꾸지 말 것**.
- **`ToolResult` 구조화 응답**: 함수는 `str` 또는 `ToolResult(content, data, is_error)` 반환. LLM 컨텍스트엔 `content` 만, 프론트엔드엔 `data` 까지 노출.
- **Timeout 일등시민**: 데코레이터의 `timeout_seconds` 가 매 호출 `asyncio.wait_for` 로 강제. 기본값은 `APP_TOOL_DEFAULT_TIMEOUT` (30s). 초과 시 `ToolResult(is_error=True, content="[timeout] ...")` 자동 반환.
- **Sentinel 도구 마커**: `add_todo` / `complete_todo` / `call_sub_agent` / `complete_subagent` 같이 harness 가 tool_call 분기에서 가로채는 도구는 `sentinel=True` 로 등록. `_execute_tool` 에 도달하면 명시적 에러.
- **`complete_subagent` 종료 규약**: 서브 에이전트는 작업 완료 시 반드시 이 도구를 호출해 `summary` 를 전달한다. harness 가 `ToolResultEvent` 에서 캡처해 `AgentReturnEvent.summary` 로 사용.
- **서브 에이전트 PLANNER 지원**: `_dispatch_sub_agent` 가 격리된 `AgentState()` (sub_state) 를 생성. 서브 에이전트도 `add_todo` / `complete_todo` 로 자체 작업을 분해할 수 있다.
- **서브 에이전트 슬롯 영속**: 서브 에이전트가 `AskUserEvent` 를 발생시키면 오케스트레이터 state 에 `pending_sub_agent` / `pending_sub_task` 를 저장. 다음 턴 system prompt 의 "# Pending Sub-Agent Slot" 섹션이 재위임을 유도.

### PROMPTS / SKILLS / AGENTS 로딩 정책

| 디렉터리 | 로딩 시점 | 캐시 정책 |
|---|---|---|
| `PROMPTS/` | 매 턴 `_read()` 호출 | dev: mtime 변경 시 재로드 (핫리로드) / frozen: 1회 |
| `SKILLS/` Front Matter | 부팅 시 `load()` 1회 | 메모리 캐시 고정 |
| `SKILLS/` body | 매칭된 스킬 첫 호출 시 lazy | dev: mtime 재검사 / frozen: 1회 |
| `AGENTS/` Front Matter | 부팅 시 `load()` 1회 | 메모리 캐시 고정 |
| `AGENTS/` body | `call_sub_agent` 위임 시점에 lazy | dev: mtime 재검사 / frozen: 1회 |

---

## 차트 인터랙션 파이프라인

`display_chart` 호출 이후의 인터랙티브 필터링·레전드 편집은 별도 파이프라인으로 처리된다.

### 산출물 파일 구조 (spec 폴더 기준)

```
result/<session>/<ts>/
  charts.spec.json    ChartSpecV1 선언 (mark·encoding·data.source)
  *.parquet           실제 데이터
  charts.json         render_spec_to_echarts() 결과 — 프론트가 fetch
  charts.filter.json  ViewState 사이드카 — exclude·legend 통합 undo/redo 스택 (v2)
```

### ViewState 스택 (`backend/agent/runtime/chart_filter_store.py`)

v2 스키마로 **필터(exclude)와 레전드 오버라이드(legend)를 단일 undo/redo 스택**에 통합. cursor가 가리키는 `ViewSnapshot`이 현재 상태.

| 전이 함수 | 효과 |
|---|---|
| `apply_exclude(state, chart_index, row_ids, scope, chart_sources)` | brush/레전드 Filter → 행 제외 push (legend carry) |
| `apply_legend(state, chart_index, *, order, colors, hidden, scope, ...)` | 순서·색상·Hide → legend 갱신 push (exclude carry) |
| `reset(state)` | 빈 스냅샷 push (undo 로 복구 가능) |
| `undo(state)` / `redo(state)` | cursor 이동만 — 양쪽 동작 무관하게 되감음 |

### `/api/chart/filter` 엔드포인트 (`backend/api/chart.py`)

| action | 동작 |
|---|---|
| `exclude` | brush 선택 행 제외 |
| `exclude_legend` | 레전드 이름 → `color.field` 값으로 행 역추적 → 기존 exclude funnel |
| `set_legend` | order·colors·hidden 오버라이드 저장 (재집계 없음) |
| `undo` / `redo` / `reset` | ViewState cursor 조작 |

응답: `{ items, can_undo, can_redo }` — `items`로 `charts.json`도 덮어씌워 재진입 일관성 보장.

### 렌더러 확장 (`backend/agent/runtime/chart_renderer.py`)

`render_spec_to_echarts(spec, base_dir, exclude_by_chart=None, legend_by_chart=None)`

- `legend_by_chart`: 차트 인덱스 → `{"order":[name], "colors":{name:hex}, "hidden":[name]}`
- `_apply_legend_config`: order(line+overlay 트윈 그룹 인접 유지)·colors(itemStyle+lineStyle)·hidden(`legend.selected`) 적용
- `resolve_legend_row_ids(chart, base_dir, legend_values)`: color.field 컬럼 기반 행 역추적 (레전드 Filter → exclude 환원)
