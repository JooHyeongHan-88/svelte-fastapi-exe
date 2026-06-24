# 에이전트 런타임

`backend_architecture.md` 에서 발췌. 에이전트 원칙 · AgentRegistry · 런타임 도구 ·
산출물 IO · manifest · namespace · evaluator 보안 · 도구 등록 · 로딩 정책을 다룬다.

하니스 구조·동작 흐름은 [docs/harness/](../../docs/harness/README.md) 참고.
인프라(경로 분기·기동·동시성·Origin 가드)는 [app_lifecycle.md](app_lifecycle.md).
차트 파이프라인은 [charts_pipeline.md](charts_pipeline.md).

---

## 에이전트 설계 원칙

이 프로젝트의 에이전트는 **미리 등록된 Python API 도구를 plan에 따라 실행**하는 역할이다.
코드를 작성하거나 파일을 편집하는 AI 코딩 어시스턴트가 아님을 항상 염두에 둘 것.

- 에이전트는 일반 질문에 텍스트로 답하거나, `add_todo` 로 plan 수립 후 tool 순차 실행.
- 오케스트레이터는 복잡한 작업을 `call_sub_agent` 로 서브 에이전트에게 위임.
- **서브 에이전트는 병렬·백그라운드 실행 없음** - 항상 순차적으로 결과가 반환될 때까지 대기.

---

## AgentRegistry - 서브 에이전트 카탈로그 (`AGENTS/`)

`backend/agent/registries/agents.py`의 `AgentRegistry` 가 `AGENTS/*.md` 를 관리.

- 부팅 시 Front Matter(`name` / `description` / `skills` / `tools` / `priority`)만 파싱.
- 본문(페르소나)은 `call_sub_agent` 위임 시점에 `_ensure_body()` 로 lazy load.
- `skills` 에 SKILLS 이름 등록 -> 해당 트리거 매칭 시 오케스트레이터가 자동 위임 (Case 3 결정론 매핑).
- `tools` 비어 있으면 에이전트에게 전체 도구 노출. 채워져 있으면 화이트리스트만.
- `agent_registry` 가 `None` 이거나 빈 경우 -> 단층 동작 (하위호환, SKILLS 직접 라우팅).
- `TurnBudget`: 오케스트레이터 + 모든 서브 에이전트 provider 호출 합산 상한 (`max_agent_calls`, `APP_MAX_AGENT_CALLS_PER_TURN`). 같은 서브 에이전트 3회 연속 위임은 loop-guard 로 차단.

---

## 라이브러리 런타임 인프라 도구 (8개)

`backend/agent/tools/runtime.py` 에 등록된 메타 도구들. SKILL/AGENT 에 `api_refs` 가 있으면 harness 가 자동 주입.

| 도구 | 역할 |
|---|---|
| `inspect_callable` | 함수/클래스 시그니처 + docstring 조회 |
| `list_module_members` | 모듈의 public 멤버 목록 |
| `call_function` | 라이브러리 함수 실행 -> namespace 저장 (`$varname` 치환 지원) |
| `eval_expression` | 단일 Python 식 평가 (namespace 변수 참조 가능) |
| `exec_code` | 다중 statement 코드 실행 (import·할당·제어흐름·stdout 캡쳐) |
| `list_namespace` | 세션 namespace 변수 목록 요약 |
| `describe_variable` | 변수 타입별 상세 요약 (DataFrame shape, ndarray min/max 등) |
| `delete_variable` | namespace 변수 영구 삭제 |

> `exec_code` scope 에는 `artifact_dir()` 헬퍼가 주입된다 - 이번 턴 산출물 폴더(`Path`)를 반환해 라이브러리가 파일을 직접 쓰게 한다. `run_in_executor` 가 contextvars 를 전파하지 않으므로 `_ArtifactDirProvider` 가 생성 시점에 client_id/title/슬롯을 캡처하고, 실행 후 `adopt_turn_slot` 으로 메인 턴 캐시에 역동기화한다 (같은 턴 `save_artifact` 와 폴더 공유). `artifact_dir` 은 예약어로 namespace 저장에서 silent skip.

> **도구 노출 vs docstring 노출 (중요)**: 위 8개 메타 도구는 `registry.specs()` 에 항상 들어
> 있어 **오케스트레이터에는 api_refs 와 무관하게 늘 노출**된다 (`_build_orchestrator_specs` 는
> 이를 제거하지 않는다). `_inject_runtime_tools` 의 api_refs 게이팅이 실효를 갖는 곳은 **서브
> 에이전트**다 - 화이트리스트(`agent.meta.tools`)로 걸러진 뒤 api_refs 가 있으면 다시 더해진다
> (`_filter_specs_for_sub_agent`). 즉 오케스트레이터에서 api_refs 가 추가로 제공하는 것은 *도구*가
> 아니라 system prompt 의 `# Available Library APIs`(시그니처·docstring) 섹션이다 - LLM 이 "무슨
> 함수가 있는지" 알게 하는 단서. 이 docstring 이 없으면 도구는 있어도 무엇을 호출할지 모른다.

### 오케스트레이터 baseline api_refs (`APP_ORCHESTRATOR_API_REFS`)

SKILL/서브에이전트 없이도 오케스트레이터가 라이브러리 함수를 docstring 기반으로 쓰게 하려면
`APP_ORCHESTRATOR_API_REFS`(CSV) 에 dotted-path 를 등록한다 (`agent.config.ORCHESTRATOR_API_REFS`).
`run_turn(orchestrator_api_refs=...)` → `_make_system_prompt_composer(baseline_api_refs=...)` →
`_compose_orchestrator_system_prompt`/`_compose_system_prompt` 의 `_render_skills_api_refs(skills, extra_refs=...)`
로 활성 SKILL refs 와 합쳐 `# Available Library APIs` 에 상시 주입한다 (도구 specs 는 손대지 않음 -
위 블록 참고). **빈 값이면 기존(SKILL 주도) 동작과 100% 동일**, 잘못된 경로는 `collect_api_docs` 가
경고 후 skip 하므로 어떤 값이어도 부팅/턴이 깨지지 않는다. 서브에이전트는 자체 meta/skill api_refs 를
쓰므로 baseline 미적용(오케스트레이터 전용).

### `scripts` 우선순위

resolver 는 명시 dotted-path 만 해석할 뿐 우선순위 로직이 없다 (`scripts.*` vs `polars.*` 는 root
이름이 다를 뿐 동급). "고수준 작업은 `scripts.*` 우선, raw 라이브러리는 scripts 로 불가능할 때만"은
**프롬프트가 유도**한다 (`PROMPTS/tools_guide.md` §8.1). 레버는 ① raw 라이브러리 함수를 api_refs 에
올리지 않아 광고하지 않음(=scripts 만 1급 표면) + ② 프롬프트 지시. `APP_ALLOWED_LIBRARIES` 의 CSV
나열 순서는 해석 우선순위와 무관하다.

---

## 산출물 재발견·재사용 도구 (always-exposed)

`backend/agent/tools/artifact_io.py` - `list_artifacts`/`load_artifact` (`ARTIFACT_IO_TOOL_NAMES`). 인프라 메타 도구와 달리 `api_refs` 조건과 무관하게 **항상 노출**된다 (markdown 재표시 등 라이브러리 런타임 없이도 필요). 서브 에이전트 화이트리스트 우회는 `_filter_specs_for_sub_agent` 에서 `INFRASTRUCTURE_TOOL_NAMES | ARTIFACT_IO_TOOL_NAMES` 로 처리. 모든 경로 해석은 `core.result_store.resolve_result_path` (RESULT_DIR 절대 기준 + containment) 로 일원화 - frozen EXE 의 CWD 함정 회피.

---

## 세션 manifest + Session Artifacts 프롬프트 섹션

`save_artifact` 성공 시 세션 루트의 `_artifacts.jsonl` 에 한 줄 append (`append_manifest_entry`, OSError 는 삼킴). `exec_code` 가 `artifact_dir()` 로 직접 쓴 파일도 실행 전/후 슬롯 diff 로 자동 등록된다 (`_register_new_slot_artifacts` - save_artifact 선행분·파생물 `DERIVED_ARTIFACT_FILENAMES` 제외, -> harness_resilience.md R6). 이 diff 의 등록 entry 목록은 `exec_code` 의 `ToolResult.data.new_artifacts` 로도 반환돼 프론트 데이터 칩(parquet) 생성에 쓰인다. `run_turn` 의 시스템 프롬프트 합성이 `_render_session_artifacts_section` 으로 최근 N개(기본 10) 산출물을 `# Session Artifacts` 섹션으로 주입한다 (manifest 우선, 없으면 디스크 스캔 fallback). **세션 복원이 tool 메시지를 버려도**(OpenAI 와이어 규약상 고아 tool 메시지 복원 불가) 디스크 manifest 가 진실원천이라 과거 산출물 재발견이 끊기지 않는다.

---

## parquet 미리보기·CSV 라우터 (`backend/api/artifact.py`)

프론트 데이터 칩 패널(ArtifactData) 전용 HTTP 경계. 경로 해석은 `resolve_result_path` 로 일원화 (containment + parquet 확장자 검사).

| 엔드포인트 | 동작 |
|---|---|
| `GET /api/artifact/preview?path=&rows=10` | head(N) 미리보기 - `scan_parquet` 으로 total_rows 만 집계(전체 로드 없음) + `read_parquet(n_rows)`. NaN/inf -> null, 비원시 타입 -> str (브라우저 JSON.parse 안전) |
| `GET /api/artifact/csv?path=` | 전체 데이터 CSV 변환 첨부 응답 - 한글 파일명 대응 RFC 5987 `filename*` |
| `POST /api/artifact/reveal {path}` | 산출물이 든 폴더를 OS 파일 탐색기(Windows `os.startfile`)로 연다 - 패널 헤더 '폴더 열기' 버튼. 파일 경로면 부모 폴더를 연다. `_open_folder` 는 테스트가 monkeypatch (실 탐색기 미기동) |

테스트: `backend/tests/test_artifact_preview_api.py`

---

## namespace LRU spill (휘발성 완화)

`APP_NAMESPACE_MAX_VARS` 초과 시 가장 오래된 변수를 **삭제하지 않고** 디스크로 spill 후 `_entries` 에서 deregister 한다 (`namespace._evict_if_needed`). 요약 크기는 bounded 로 유지되면서 같은 이름 재참조 시 lazy 재색인으로 부활한다. `__init__` 의 eager 재색인은 crash 복구용. `cleanup` 은 `disk_dir` 전체 rmtree (spill-후-deregister 파일 누수 방지). 단, presence 단절 2초 후 `cleanup_namespace` 가 디렉터리째 삭제하는 의도적 휘발 설계는 그대로 - **세션 간 영속의 정식 경로는 save->load_artifact** 이다.

---

## evaluator 보안 모델 (`backend/agent/runtime/evaluator.py`)

단일 사용자 로컬 데스크탑 앱 위협 모델에 맞게 완화됨.

- **차단**: `exec`, `eval`, `compile` (재귀 인젝션 방지), `__import__` 직접 무제한 사용
- **허용**: 그 외 모든 public builtin (`open`, `print`, `getattr`, `vars`, `dir`, `iter`, `next`, ...)
- **import 허용 목록**: stdlib 안전 목록(`math`, `statistics`, `json`, `datetime`, `pathlib`, `re`, `collections` 등) + `APP_ALLOWED_LIBRARIES`
- **차단 목록**: `os`, `sys`, `subprocess`, `socket`, `shutil` (시스템·외부통신 - runaway 방지)
- 진정한 sandbox 가 아님. dunder 우회를 완전히 막지는 않음. LLM 실수·runaway 방지 가드.

`exec_code`/`eval_expression` 은 globals/locals 를 **단일 dict(module scope)** 로 실행한다 -
분리하면 generator expression·nested def 가 free 변수를 locals 에서 못 찾아 `NameError`. 실행 후 `__builtins__` 를 제거해 namespace 오염 방지.

---

## Tool 등록 패턴 (`agent/tools/`)

새 사내 API 를 도구로 노출하려면 `backend/agent/tools/` 에 새 `.py` 파일을 만들고 `@register_tool` 데코레이터를 붙인 async 함수를 작성하면 끝. 부팅 시 `agent/tools/__init__.py` 가 모든 서브모듈을 import 해 데코레이터의 부수효과로 `_REGISTRY` 가 채워진다.

- **시그니처에서 자동 스키마 생성**: 각 파라미터의 `Annotated[T, "설명"]` 을 Pydantic `create_model` 로 묶어 JSON Schema (LLM 노출) + `TypeAdapter` (입력 검증) 를 1회 생성. 매 turn 재생성 없음.
- **오류 책임자별 분기 가드**: `validate_tool_args` 가 두 경로로 나눈다 - (1) `type=="missing"`(값 부재) -> `MissingSlot`->`AskUserEvent` 로 사용자에게 재질문, (2) 그 외 형식/타입/enum 위반(`date_from="오늘"`, 문자열 자리 dict 등 값은 줬는데 모양이 틀림) -> `SlotCheckResult.invalid_message` 로 LLM 에 도구 에러를 회신해 같은 루프 안에서 self-correct 유도(사용자 미개입). 둘이 동시면 invalid 경로가 누락 항목까지 함께 안내. 동일 잘못된 호출 반복은 `history_calls` loop-guard 가 차단.
- **중첩 Pydantic 모델 인자**: `_execute_tool` 이 `model_validate` 후 `{name: getattr(parsed, name) for name in type(parsed).model_fields}` 로 kwargs 를 추출한다. `model_dump()` 를 쓰면 `list[ImageItem]` 같은 중첩 모델이 `list[dict]` 로 직렬화돼 도구 함수의 타입 기대와 불일치한다 - **절대 `model_dump()` 로 바꾸지 말 것**.
- **`ToolResult` 구조화 응답**: 함수는 `str` 또는 `ToolResult(content, data, is_error)` 반환. LLM 컨텍스트엔 `content` 만, 프론트엔드엔 `data` 까지 노출.
- **Timeout 일등시민**: 데코레이터의 `timeout_seconds` 가 매 호출 `asyncio.wait_for` 로 강제. 기본값은 `APP_TOOL_DEFAULT_TIMEOUT` (30s). 초과 시 `ToolResult(is_error=True, content="[timeout] ...")` 자동 반환.
- **Sentinel 도구 마커**: `add_todo` / `complete_todo` / `call_sub_agent` / `complete_subagent` 같이 harness 가 tool_call 분기에서 가로채는 도구는 `sentinel=True` 로 등록. `_execute_tool` 에 도달하면 명시적 에러.
- **`complete_subagent` 종료 규약**: 서브 에이전트는 작업 완료 시 반드시 이 도구를 호출해 `summary` 를 전달한다. harness 가 `ToolResultEvent` 에서 캡처해 `AgentReturnEvent.summary` 로 사용.
- **서브 에이전트 PLANNER 지원**: `_dispatch_sub_agent` 가 격리된 `AgentState()` (sub_state) 를 생성. 서브 에이전트도 `add_todo` / `complete_todo` 로 자체 작업을 분해할 수 있다.
- **서브 에이전트 슬롯 영속**: 서브 에이전트가 `AskUserEvent` 를 발생시키면 오케스트레이터 state 에 `pending_sub_agent` / `pending_sub_task` 를 저장. 다음 턴 system prompt 의 "# Pending Sub-Agent Slot" 섹션이 재위임을 유도.

자세한 등록 how-to -> [agent_extension.md](agent_extension.md).

---

## PROMPTS / SKILLS / AGENTS 로딩 정책

| 디렉터리 | 로딩 시점 | 캐시 정책 |
|---|---|---|
| `PROMPTS/` | 매 턴 `_read()` 호출 | dev: mtime 변경 시 재로드 (핫리로드) / frozen: 1회 |
| `SKILLS/` Front Matter | 부팅 시 `load()` 1회 | 메모리 캐시 고정 |
| `SKILLS/` body | 매칭된 스킬 첫 호출 시 lazy | dev: mtime 재검사 / frozen: 1회 |
| `AGENTS/` Front Matter | 부팅 시 `load()` 1회 | 메모리 캐시 고정 |
| `AGENTS/` body | `call_sub_agent` 위임 시점에 lazy | dev: mtime 재검사 / frozen: 1회 |

> **frozen 콘텐츠 소스**: 부팅 시 `content_sync.sync_agent_content()` 가 성공하면 레지스트리가
> 번들(MEIPASS) 대신 `%APPDATA%/{APP_NAME}/content/<DIR>` 의 동기화본을 읽는다(`use_directory()`
> 재지정, `load()` 직전). 채널→브랜치 매핑·폴백은 [update_architecture.md](update_architecture.md)
> "콘텐츠 동기화" 참고. dev 는 동기화하지 않으므로 로컬 워킹트리 + mtime 핫리로드 그대로다.
