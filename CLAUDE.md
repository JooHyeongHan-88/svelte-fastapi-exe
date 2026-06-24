# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

Svelte(Vite) 정적 자산을 FastAPI가 서빙하고 PyInstaller로 단일 `.exe`로 패키징하는 AI Agent 채팅 UI 앱.
다중 대화 세션(localStorage 영속화) · LLM 설정 UI · GitHub Enterprise Releases 자동 업그레이드(sha256 검증, self-replace) 내장.

- Python 패키지 관리: `uv` / JS 패키지 관리: `npm`
- 빌드 산출물 흐름: **`build/` (중간)** → **`release/` (GitHub Release 첨부 대상)**
- **앱 이름 변경**: `.env`의 `APP_NAME` 값 하나만 바꾸면 된다. `App.spec`과 `release.ps1`이 이 값을 읽는다.

> ⛔ **`docs/overview/` 는 사람이 관리하는 프로젝트 소개 자료다(마크다운 원고).** 사용자가 그 폴더를
> 갱신하라고 **명시적으로 지시한 경우에만** 읽거나 편집한다. 그 외에는 — 코드/문서를 광범위하게
> 손볼 때라도 — `docs/overview/**` 를 자발적으로 열거나 수정하지 않는다.

---

## 주요 명령어

```powershell
# 개발 서버 (백엔드 먼저, Vite가 /api를 프록시)
uv run python backend/main.py          # 터미널 1
cd frontend; npm run dev               # 터미널 2 — http://localhost:5173

# 의존성
uv sync --dev
cd frontend; npm install

# 린트/포맷 — Python 변경 후 반드시 실행
uv run ruff format . && uv run ruff check --fix .

# 테스트 전체
uv run python -m pytest backend/tests/ -v

# 주요 테스트 파일 단독 실행
uv run python -m pytest backend/tests/test_guard_pydantic.py -v        # 슬롯 가드
uv run python -m pytest backend/tests/test_runtime_evaluator.py -v     # eval/exec 보안
uv run python -m pytest backend/tests/test_conversation_store.py -v    # 히스토리 정합성
uv run python -m pytest backend/tests/test_openai_provider.py -v       # provider 스트리밍
uv run python -m pytest backend/tests/test_artifact_tool.py -v         # save_artifact (바이너리 kind 포함)
uv run python -m pytest backend/tests/test_artifact_parquet.py -v      # parquet 파이프라인
uv run python -m pytest backend/tests/test_artifact_io.py -v           # list_artifacts·load_artifact·경로 해석
uv run python -m pytest backend/tests/test_artifact_manifest.py -v     # 세션 manifest·Session Artifacts 섹션
uv run python -m pytest backend/tests/test_artifact_preview_api.py -v  # /api/artifact preview·csv·reveal (데이터 칩·폴더 열기)
uv run python -m pytest backend/tests/test_harness_timeout.py -v       # _execute_tool (async)
uv run python -m pytest backend/tests/test_harness_subagent.py -v      # 서브에이전트 격리
uv run python -m pytest backend/tests/test_harness_parallel.py -v      # 서브에이전트 병렬 디스패치
uv run python -m pytest backend/tests/test_harness_error_path.py -v    # run_turn 예외 경로 영속·DoneEvent
uv run python -m pytest backend/tests/test_harness_loop_guard.py -v    # 루프 가드 파일 fingerprint
uv run python -m pytest backend/tests/test_harness_todo_reset.py -v    # 턴 시작 terminal todo 리셋
uv run python -m pytest backend/tests/test_harness_wind_down.py -v     # 반복 예산 임박 wind-down 지시
uv run python -m pytest backend/tests/test_chat_concurrent_guard.py -v # 같은 client_id 동시 턴 거부
uv run python -m pytest backend/tests/test_chart_renderer.py -v        # 차트 렌더러 (legend 적용 포함)
uv run python -m pytest backend/tests/test_chart_filter_store.py -v    # 차트 뷰 상태 undo/redo 스택
uv run python -m pytest backend/tests/test_chart_api.py -v             # /api/chart/filter 통합 (HTTP 경계)
uv run python -m pytest backend/tests/test_display_chart_spec.py -v    # display_chart spec

# 프로덕션 빌드 / 릴리즈 (-Channel 필수)
pwsh packaging/release.ps1 -Channel qa             # QA 빌드 (Mock 노출, 업데이트 차단, --prerelease)
pwsh packaging/release.ps1 -Channel prod -Upload -Notes "..."  # Prod 빌드 + GitHub Release 게시
pwsh packaging/release.ps1 -Channel prod -Force    # git dirty 상태 강제 통과
pwsh packaging/release-dryrun.ps1                  # 네트워크 없이 업데이트 파이프라인 검증
```

> `pyproject.toml`에 `[tool.pytest.ini_options] asyncio_mode = "auto"` 설정 — `async def test_*` 함수가 마커 없이 자동 실행된다.

산출물: `release/{AppName}.exe`, `release/{AppName}-X.X.X.exe`, `release/latest.json`

---

## 에이전트 설계 원칙 (필독)

이 프로젝트는 **미리 갖추어진 Python API를 plan에 따라 실행하는 Agent 플랫폼**이다.
코드를 작성하거나 파일을 편집하는 AI 코딩 어시스턴트가 아니다.

| 상황 | 에이전트 행동 |
|---|---|
| 일반 질문 | 텍스트로 직접 답변 |
| 도구 실행이 필요한 작업 | `add_todo` 로 plan 작성 → 등록된 tool 순차 실행 → `complete_todo` |
| 복잡한 작업 (여러 도메인) | 오케스트레이터가 `call_sub_agent`(순차) 또는 `call_sub_agents_parallel`(독립 작업 동시) 로 서브 에이전트에게 위임 |
| 산출물을 저장해야 할 때 | `save_artifact(filename, content/source, kind)` → 반환된 `path` 를 `display_markdown` 등에 전달. kind 는 markdown/json/text/parquet + 바이너리(png/svg/pdf/pptx/xlsx, namespace `$bytes` 변수) |
| 과거 산출물을 재사용할 때 | `list_artifacts` 로 경로 재발견 → `load_artifact(path, store_as)` 로 namespace 로 복원 → 후속 분석. 단순 재표시는 `display_*` 에 경로 직접 전달 |

**서브 에이전트 제약**: 기본 순차 실행. 독립·완결 작업은 `call_sub_agents_parallel(tasks=[...])` 로 **옵트인 병렬** 실행 가능(동시성 상한 `APP_MAX_PARALLEL_SUBAGENTS`). 백그라운드 실행 없음, 서브가 `call_sub_agent`/`call_sub_agents_parallel` 재호출 불가(4중 방어선).  
→ 중첩 차단 방어선 · 병렬 디스패치 상세: `.claude/rules/agent_runtime.md`

| 디렉터리 | 역할 | 라우팅 |
|---|---|---|
| `SKILLS/` | 오케스트레이터·서브 에이전트 공통 작업 가이드 | Front Matter `trigger` 키워드 매칭 |
| `AGENTS/` | 서브 에이전트 페르소나·도구 화이트리스트 | `call_sub_agent(agent_name=...)` 명시 위임 |

---

## Mock 시나리오 (UI/Harness 검증용)

현재 `SKILLS/`, `AGENTS/`, `backend/scripts/` 의 파일들은 실제 LLM 없이 Harness와 UI를 검증하기 위한 **Mock 전용**이다. 운영 시 도메인 SKILL/AGENT로 교체하거나 삭제한다.

| 시나리오 | 트리거 예시 | 검증 대상 |
|---|---|---|
| A (echo) | (그 외 모든 입력) | 기본 스트리밍, TurnStatus |
| B (ask_user) | `추천해줘`, `골라줘` (다중: `여러개 골라줘`, `모두 선택`) | ReasoningBlock, AskUserCard(단일·다중 선택) |
| C (time_check) | `지금 시간`, `현재 시각` | SkillBadge, ArtifactMarkdown |
| D (data_summary) | `데이터 요약`, `요약 통계` | AgentTrail, TodoProgress, ArtifactChart(6개·레전드 컨트롤) |
| E (composite) | `전체 분석 보고서`, `종합 보고서` | 2단 sub-agent, ArtifactChart(7개)+ArtifactImage |
| F (parallel) | `병렬 분석`, `동시 분석` | `call_sub_agents_parallel` 2개 트레일 동시 진행·dispatch_id 라우팅 |
| G (artifact 재사용) | `이전 결과`, `지난 분석`, `예전 데이터` | `list_artifacts`→`load_artifact`→`exec_code` 읽기 방향 체인 (D 선행 전제) |
| H (큐레이션 핸드오프) | `순위 검토`, `후보 큐레이션`, `큐레이션 도구` | `exec_code`→`save_artifact`(parquet)→`open_curation` extension 칩 → 우측 패널 `/ext/evaluator/?bundle=` iframe 자동 임베드·패널 '최대화' 버튼 (`rank_review` SKILL 계약) |

`APP_ALLOWED_LIBRARIES=scripts,polars` — 운영 시 도메인 라이브러리로 교체.  
→ 시나리오 상세: `docs/guides/mock-scenarios.md`

---

## 주요 환경 변수

`.env`는 **빌드 파이프라인의 단일 진실 공급원**. frozen EXE는 빌드 시 `MEIPASS/.env`에 박제된 `.env`를 `load_dotenv(override=False)`로 읽는다. OS 환경 변수가 있으면 그쪽이 우선(`override=False`)하므로, 런타임 오버라이드는 OS 환경 변수로 가능하지만 근본 변경은 재빌드가 필요하다.  
전체 목록: `backend/core/config.py`, `backend/agent/config.py`

| 환경 변수 | 기본값 | 설명 |
|---|---|---|
| `APP_NAME` | `MyAgent` | EXE 파일명, settings.json 경로 |
| `APP_PORT` | (APP_NAME 해시) | **frozen 전용** 고정 포트. 기본값은 `47100 + sha256(APP_NAME) % 1900` (47100–48999). `0` 이면 동적(대화 기록이 실행마다 격리됨). 충돌 시 +1..+4 후보 체인 자동 폴백 — `core.server_socket` |
| `APP_DEV_PORT` | `8765` | **dev 전용** 백엔드 포트 (Vite 프록시 타겟과 공유). frozen 은 APP_PORT 로 결정 — `core.server_socket`. 호스트는 `127.0.0.1` 코드 고정(env 미노출) |
| `APP_LLM_PROVIDER` | `mock` | 초기 settings.json 시드용 (`mock` \| `dtgpt` \| `openai_compatible`) |
| `APP_DTGPT_BASE_URL` | — | DTGPT 엔드포인트 (UI 비노출, factory가 직접 읽음) |
| `APP_SYSTEM_PROMPT` | (내장 한국어) | LLM 시스템 프롬프트 |
| `APP_MAX_AGENT_ITERATIONS` | `12` | 한 턴당 provider→tool 반복 상한. 잔여 2회 시점에 wind-down 지시 자동 주입(R7) |
| `APP_MAX_AGENT_CALLS_PER_TURN` | `20` | 오케스트레이터+서브에이전트 합산 provider 호출 상한 |
| `APP_MAX_PARALLEL_SUBAGENTS` | `3` | `call_sub_agents_parallel` 한 번에 동시 실행할 서브에이전트 수 상한 (semaphore) |
| `APP_TOOL_DEFAULT_TIMEOUT` | `30` | Tool 1회 실행 timeout (초) |
| `APP_DEBUG_TRACE` | `false` | **dev 전용** 디버그 트레이스 토글. 켜면 턴마다 provider in/out(프롬프트 전문·raw 응답)과 하니스 결정점(루프가드·슬롯가드·wind-down 등)을 `result/<session>/_trace/<turn>.jsonl` 로 기록 — `tracer` 확장(런처 드롭다운)으로 타임라인 조회. frozen EXE 는 강제 비활성 — `agent.debug.trace` |
| `APP_ALLOWED_LIBRARIES` | `scripts,polars` | 런타임에 노출할 패키지 루트 CSV — EXE 빌드 시 자동 번들링. `scripts`(고수준 래퍼) 우선은 프롬프트가 유도; CSV 순서는 해석 우선순위와 무관 |
| `APP_ORCHESTRATOR_API_REFS` | (빈 값) | 오케스트레이터 baseline api_refs CSV. 지정 시 활성 SKILL 없이도 그 함수들의 시그니처·docstring 을 `# Available Library APIs` 로 상시 주입(런타임 메타 도구는 원래 항상 노출이라, 이 변수가 주는 건 prompt 의 docstring). 빈 값=기존 SKILL 주도 동작. 잘못된 경로는 skip — 무오류 |
| `APP_REPO_BASE_URL` | — | GitHub 레포 루트 URL — updater가 REST API base(`.../api/v3`)·owner/repo 유도 |
| `APP_REPO_READ_TOKEN` | — | 읽기 전용 Classic PAT — EXE에 번들, REST API 릴리즈 메타·에셋 다운로드 인증용 (콘텐츠 동기화와 공유) |
| `APP_BUILD_CHANNEL` | (`qa`/`prod`) | App.spec이 주입 — 소스 `.env`에 두지 않음. `qa`: Mock 노출·업데이트 차단·콘텐츠 `dev` 브랜치; `prod`: Mock 제외·업데이트 활성·콘텐츠 `main` 브랜치 |
| `APP_CONTENT_SYNC_ENABLED` | frozen=`true`, dev=`false` | frozen 기동 시 SKILLS/AGENTS/PROMPTS를 원격 브랜치에서 동기화(EXE 재빌드 없이 콘텐츠 갱신). 실패 시 번들 폴백 — `core.content_sync` |
| `APP_CONTENT_SYNC_BRANCH` | — | 채널 매핑(qa→dev, prod→main) 무시하고 이 브랜치 강제 — frozen 카나리 검증용 |
| `APP_CONTENT_SYNC_TIMEOUT` | `5` | 기동 시 콘텐츠 동기화 블로킹 상한 (초) |

> `.env` 값의 `# 인라인 주석`은 파서가 자동 제거한다.

---

## 확장 시스템 (Extensions)

**`extensions/`** — 메인 앱과 완전히 격리된 독립 도구(Svelte5 SPA + FastAPI 라우터).  
폴더 단위로 추가·삭제 가능(host 코드 변경 없음). 로더: `backend/core/extensions_loader.py`.  
예시: [evaluator](extensions/evaluator/) (parquet 큐레이션 UI). 개발자 가이드 → `docs/guides/extensions.md`,
내부 상세 → `.claude/rules/extensions_architecture.md`

**진입 규약** — 모든 확장은 **채팅창 우측 아티팩트 패널에 same-origin iframe 으로 임베드**되어
열린다(`ArtifactExtension.svelte`). 두 경로: ① 에이전트가 `open_curation(tool, sources, mapping)`
도구를 호출하면 번들 스펙(`<tool>.bundle.json`)을 쓰고 **`kind:"extension"` 칩**으로
`/ext/<tool>/?bundle=` iframe 을 패널에 자동으로 연다(메시지 영속·세션 재진입 복원). ② TopBar
패널-열기 버튼의 **드롭다운 런처**(`ExtensionMenu`, `GET /api/extensions` + 선택적 `extension.json`)로
소스 없이 확장을 열면 확장의 **랜딩 페이지**가 뜬다. 패널 헤더 **'최대화'** 버튼으로 본문을
뷰포트 전체로 키울 수 있다(복귀는 상단 hover 복귀 버튼). evaluator 는 `?path=`(단일) 또는
`?bundle=`(다중 소스)로 진입하며, 다중 소스는 **소스 탭으로 한 번에 하나씩 큐레이션**(병합
아님 — 성격 다른 후보군 전제)하고 세션 manifest(`GET /sources`)에서 **소스 추가·제거·변경**으로
교정할 수 있다(단일 소스는 탭 숨김 + '소스 변경' 1단축). 추가/변경 피커는 후보 parquet 의
head(10) 미리보기(`GET /preview`, 호스트 ArtifactData 와 동일 형태)로 어떤 소스인지 보고
고른다. SKILL 작성 예시: [rank_review](SKILLS/rank_review.md).
도구는 evaluator 비특정(`tool` 인자로 임의 확장 지정) — 폴더 삭제 시 SKILL 이 호출하지 않아 무해.

evaluator UI 는 좌측 선택 리스트(**너비 조절·기본 전체 선택·드래그&드롭 순서변경·Ctrl/Shift+클릭
다중 표시·검색/legend 필터/일괄 선택**)와 본문 **차트 종류 셀렉터 + 차트 보기 제어(전체 보기·보기
해제·병합 보기) + 매핑 설정 모달 + 차트 그리드**(메인 앱 `display_chart` UX 를 클라이언트에서 자체
구현 — Tableau 풍 BI 컨셉)로 구성된다. **차트 종류**는 `display_chart` 와 동일 7종(scatter/line/bar/
box/histogram/ecdf/heatmap)을 셀렉터로 전환하며, 종류를 바꾸면 **필요한 차트별 매핑 역할(x/y/집계)도
달라진다**(공통 역할 select/sort/legend/desc 는 항상 동일). **병합 보기**는 표시 선택(클릭으로 본)된
차트들의 소스 데이터만 하나로 합쳐 보여주되 **항목별 차트의 매핑 요소(legend 포함)를 그대로 유지**
한다(legend 를 항목 키로 덮어쓰지 않음 — 읽기전용 비교 뷰). **표시 선택**은 단일 클릭·Ctrl/⌘+클릭
토글·**Shift+클릭 범위**를 지원하고, **전체 보기/보기 해제** 버튼으로 일괄 제어한다. **매핑 설정 모달**은
역할별 설명 + 컬럼 드롭다운을 제공하고
**legend 는 다중 컬럼 합성**(`POR | A`)을 지원한다. 차트 종류·매핑은 상태 사이드카에 영속(재진입
복원)되고, `desc` 매핑은 선택적(컬럼 부재 시 생략). **내보내기** 성공 시 `BroadcastChannel("evaluator:exports")`
로 메인 앱 탭에 알려 그 parquet 을 데이터 칩으로 인폼하며, **사람의 결정 요약**(후보 N개 중 M개 선택·
제외·메모)을 칩 배너로 띄우고 **"이어서 작업"** 버튼으로 후속 프롬프트를 입력창에 시드해 큐레이션
판단을 에이전트에게 환류한다(수신부 `frontend/src/lib/evaluatorBridge.svelte.js`). 진입 시
`open_curation` 은 선택적 `mark` 로 기본 차트 종류도 넘길 수 있고, **소스/번들 없이 런처로 열리면
랜딩 페이지**(소스 경로 입력 안내)를 띄운다. 상세 →
`docs/guides/extensions.md` · `.claude/rules/extensions_architecture.md`.

---

## 상세 문서

**`.claude/rules/`** — 아키텍처 참고서 (Claude Code 전용)

| 파일 | 내용 |
|---|---|
| `app_lifecycle.md` | PyInstaller 경로 분기 · App 기동 시퀀스 · Presence · 동시성 · Origin 가드 |
| `agent_runtime.md` | 에이전트 원칙 · AgentRegistry · 런타임 메타 도구 · 아티팩트 IO · manifest · namespace · evaluator 보안 · 도구 등록 · 로딩 정책 |
| `charts_pipeline.md` | ViewState 스택 · `/api/chart/filter` · 렌더러 확장(R8) |
| `harness_resilience.md` | Harness 복원력 불변식 — F1~F12·R1~R8 카탈로그 ("이 방어 코드가 있는 이유") |
| `frontend_state.md` | `$state ui` · 액션 함수 · localStorage 스키마 · 데이터 흐름 · 세션 동기화 · reactive proxy 주의 |
| `frontend_components.md` | 컴포넌트 카탈로그 · ModelPicker · TurnStatus · 서브에이전트 트레일 · 차트 인터랙션 UI · 테마 |
| `extensions_architecture.md` | 확장 시스템 공통 — 격리 원칙 · 로더 · `open_curation` 규약 · 런처 · App.spec 번들 · 새 확장 추가 |
| `extensions_evaluator.md` | evaluator 심화 — API 라우터 · ColumnMapping · export · 프론트 진입 · 차트 구현 |
| `settings_architecture.md` | LLM 설정 저장 구조(멀티 프로바이더) · API key 보안 · threading.Lock |
| `update_architecture.md` | 자동 업데이트 4단계 · rename-to-backup 전략 · 콘텐츠 동기화(SKILLS/AGENTS/PROMPTS 런타임 갱신) · PowerShell 5.1 주의 |
| `agent_extension.md` | 새 Tool 등록 · 서브 에이전트 등록 · AgentMeta 확장 필드 · 새 LLM 프로바이더 추가 |
| `code_conventions.md` | Python 코딩 규칙 · ruff · 타입 힌트 · Pydantic |

**`docs/guides/`** — 에이전트·도구 개발자 참고서

| 파일 | 내용 |
|---|---|
| `guides/builtin-tools.md` | `save_artifact` · `display_chart` · `display_markdown` · `open_curation` 등 내장 도구 전체 + 차트 파이프라인 |
| `guides/extensions.md` | 확장 시스템 개발자 가이드 — 디렉터리 컨벤션 · 패널 iframe 임베드 · 런처 드롭다운/`extension.json` · 랜딩 페이지 · 새 확장 추가 |
| `guides/charts.md` | `display_chart` 차트 유형(mark)별 encoding · parquet+spec 파이프라인 · brush 필터 지원 차트 |
| `guides/library-runtime.md` | `api_refs` 메타 도구 8개 · 세션 namespace · evaluator 보안 모델 |
| `guides/mock-scenarios.md` | 시나리오 A~H 상세 흐름 · 산출물 경로 · 신규 시나리오 추가 방법 |
| `guides/skills.md` | `SKILLS/*.md` Front Matter · 트리거 매칭 원리 · `activate_skill` (3번째 경로) |
| `guides/agents.md` | `AGENTS/*.md` Front Matter · Case 3 라우팅 · 페르소나 작성법 |
| `guides/prompts.md` | `PROMPTS/*.md` 합성 순서 · 핫리로드 정책 |

**`docs/harness/`** — 하니스 동작 흐름·구조 (패키지 단위, 개발자 심화)

| 파일 | 내용 |
|---|---|
| `harness/README.md` | 턴 생애주기 다이어그램 · 모듈 맵 · 중복방지 안내 |
| `harness/turn-loop.md` | `loop.py` — run_turn · _run_agent_turn · budget · tool_exec · wind-down(R7)/fallback(F6) |
| `harness/call-handlers.md` | `call_handlers.py` — 3단계 파이프라인 · sentinel 라우트 · 가드(`activate_skill` 포함) |
| `harness/dispatch.md` | `dispatch/` — 순차·병렬(dispatch_id·semaphore) · spec_filter(4중 차단) · result_format |
| `harness/prompt.md` | `prompt/` — compose · sections · artifacts · api_refs · wind_down |
| `harness/state.md` | `state/` — todo · balancing · loop_guard · pending |
