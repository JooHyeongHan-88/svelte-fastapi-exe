# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

Svelte(Vite) 정적 자산을 FastAPI가 서빙하고 PyInstaller로 단일 `.exe`로 패키징하는 AI Agent 채팅 UI 앱.
다중 대화 세션(localStorage 영속화) · LLM 설정 UI · Nexus 자동 업그레이드(sha256 검증, self-replace) 내장.

- Python 패키지 관리: `uv` / JS 패키지 관리: `npm`
- 빌드 산출물 흐름: **`build/` (중간)** → **`release/` (Nexus 업로드 대상)**
- **앱 이름 변경**: `.env`의 `APP_NAME` 값 하나만 바꾸면 된다. `App.spec`과 `release.ps1`이 이 값을 읽는다.

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
uv run python -m pytest backend/tests/test_artifact_tool.py -v         # save_artifact
uv run python -m pytest backend/tests/test_artifact_parquet.py -v      # parquet 파이프라인
uv run python -m pytest backend/tests/test_harness_timeout.py -v       # _execute_tool (async)
uv run python -m pytest backend/tests/test_harness_subagent.py -v      # 서브에이전트 격리
uv run python -m pytest backend/tests/test_chart_renderer.py -v        # 차트 렌더러
uv run python -m pytest backend/tests/test_display_chart_spec.py -v    # display_chart spec

# 프로덕션 빌드 / 릴리즈
pwsh packaging/release.ps1
pwsh packaging/release.ps1 -Upload -Notes "..."   # .env에서 저장소 자격증명 자동 로드
pwsh packaging/release.ps1 -Force                  # git dirty 상태나 버전 중복 강제 통과
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
| 복잡한 작업 (여러 도메인) | 오케스트레이터가 `call_sub_agent` 로 서브 에이전트에게 위임 |
| 산출물을 저장해야 할 때 | `save_artifact(filename, content, kind)` → 반환된 `path` 를 `display_markdown` 등에 전달 |

**서브 에이전트 제약**: 항상 순차 실행, 백그라운드 실행 없음, `call_sub_agent` 재호출 불가(4중 방어선).  
→ 중첩 차단 방어선 상세: `.claude/rules/backend_architecture.md`

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
| B (ask_user) | `추천해줘`, `골라줘` | ReasoningBlock, AskUserCard |
| C (time_check) | `지금 시간`, `현재 시각` | SkillBadge, ArtifactMarkdown |
| D (data_summary) | `데이터 요약`, `요약 통계` | AgentTrail, TodoProgress, ArtifactChart(4개) |
| E (composite) | `전체 분석 보고서`, `종합 보고서` | 2단 sub-agent, ArtifactChart(7개)+ArtifactImage |

`APP_ALLOWED_LIBRARIES=scripts,polars` — 운영 시 도메인 라이브러리로 교체.  
→ 시나리오 상세: `docs/mock-scenarios.md`

---

## 주요 환경 변수

`.env`는 **빌드 파이프라인의 단일 진실 공급원**. frozen EXE는 빌드 시 `MEIPASS/.env`에 박제된 `.env`를 `load_dotenv(override=False)`로 읽는다. OS 환경 변수가 있으면 그쪽이 우선(`override=False`)하므로, 런타임 오버라이드는 OS 환경 변수로 가능하지만 근본 변경은 재빌드가 필요하다.  
전체 목록: `backend/core/config.py`, `backend/agent/config.py`

| 환경 변수 | 기본값 | 설명 |
|---|---|---|
| `APP_NAME` | `MyAgent` | EXE 파일명, settings.json 경로 |
| `APP_DEV_PORT` | `8765` | **dev 전용** 백엔드 포트 (Vite 프록시 타겟과 공유). frozen 은 OS 가 빈 포트를 동적 할당하므로 무관 — `config.py:create_server_socket`. 호스트는 `127.0.0.1` 코드 고정(env 미노출) |
| `APP_LLM_PROVIDER` | `mock` | 초기 settings.json 시드용 (`mock` \| `dtgpt` \| `openai_compatible`) |
| `APP_DTGPT_BASE_URL` | — | DTGPT 엔드포인트 (UI 비노출, factory가 직접 읽음) |
| `APP_SYSTEM_PROMPT` | (내장 한국어) | LLM 시스템 프롬프트 |
| `APP_MAX_AGENT_ITERATIONS` | `8` | 한 턴당 provider→tool 반복 상한 |
| `APP_MAX_AGENT_CALLS_PER_TURN` | `20` | 오케스트레이터+서브에이전트 합산 provider 호출 상한 |
| `APP_TOOL_DEFAULT_TIMEOUT` | `30` | Tool 1회 실행 timeout (초) |
| `APP_ALLOWED_LIBRARIES` | `scripts,polars` | 런타임에 노출할 패키지 루트 CSV — EXE 빌드 시 자동 번들링 |
| `APP_REPO_BASE_URL` | (내부) | 업데이트 저장소 URL (현재 Nexus, 저장소 중립적 변수명) |
| `APP_REPO_USER` / `_PASSWORD` | — | release.ps1 자동 업로드 자격증명 |

> `.env` 값의 `# 인라인 주석`은 파서가 자동 제거한다.

---

## 상세 문서

**`.claude/rules/`** — 아키텍처 참고서 (Claude Code 전용)

| 파일 | 내용 |
|---|---|
| `backend_architecture.md` | App 생명주기 · presence · 동시성 · 에이전트 하니스 · AgentRegistry |
| `frontend_architecture.md` | Svelte 5 상태 패턴 · 컴포넌트 · TurnStatus · localStorage 스키마 |
| `settings_architecture.md` | LLM 설정 저장 구조(멀티 프로바이더) · API key 보안 · threading.Lock |
| `update_architecture.md` | 자동 업데이트 4단계 · rename-to-backup 전략 · PowerShell 5.1 주의 |
| `agent_extension.md` | 새 Tool 등록 · 서브 에이전트 등록 · AgentMeta 확장 필드 · 새 LLM 프로바이더 추가 |
| `harness_resilience.md` | Harness 복원력 패턴 — 가드 분기·히스토리 정합성·provider 재시도·pending 정리 |
| `code_conventions.md` | Python 코딩 규칙 · ruff · 타입 힌트 · Pydantic |

**`docs/`** — 에이전트·도구 개발자 참고서

| 파일 | 내용 |
|---|---|
| `builtin-tools.md` | `save_artifact` · `display_chart` · `display_markdown` 등 내장 도구 전체 + 차트 파이프라인 |
| `charts.md` | `display_chart` 차트 유형(mark)별 encoding · parquet+spec 파이프라인 · brush 필터 지원 차트 |
| `library-runtime.md` | `api_refs` 메타 도구 8개 · 세션 namespace · evaluator 보안 모델 |
| `mock-scenarios.md` | 시나리오 A~E 상세 흐름 · 산출물 경로 · 신규 시나리오 추가 방법 |
| `skills.md` | `SKILLS/*.md` Front Matter · 트리거 매칭 원리 |
| `agents.md` | `AGENTS/*.md` Front Matter · Case 3 라우팅 · 페르소나 작성법 |
| `prompts.md` | `PROMPTS/*.md` 합성 순서 · 핫리로드 정책 |
