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
- `Origin` 헤더 있으면 `ALLOWED_ORIGIN`(`http://127.0.0.1:8765`)과 일치 확인
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
