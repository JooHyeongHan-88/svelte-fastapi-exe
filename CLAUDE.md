# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

Svelte(Vite) 정적 자산을 FastAPI가 서빙하고 PyInstaller로 단일 `.exe`로 패키징하는 AI Agent 채팅 UI 앱.
다중 대화 세션(localStorage 영속화) · LLM 설정 UI · Nexus 자동 업그레이드(sha256 검증, self-replace) 내장.

- Python 패키지 관리: `uv` / JS 패키지 관리: `npm`
- 빌드 산출물 흐름: **`build/` (중간)** → **`release/` (Nexus 업로드 대상)**
- **앱 이름 변경**: `.env`의 `APP_NAME` 값 하나만 바꾸면 된다. `App.spec`과 `release.ps1`이 이 값을 읽는다.

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

| 디렉터리 | 역할 | 라우팅 |
|---|---|---|
| `SKILLS/` | 오케스트레이터·서브 에이전트 공통 작업 가이드 | Front Matter `trigger` 키워드 매칭 |
| `AGENTS/` | 서브 에이전트 페르소나·도구 화이트리스트 | `call_sub_agent(agent_name=...)` 명시 위임 |

중첩 위임 차단 방어선 (`backend/agent/harness.py`):
- **L0** `_dispatch_sub_agent`: `agent_registry=None` 전달 — dispatch 분기 자체를 열지 않음
- **L1** `_filter_specs_for_sub_agent`: `SUB_AGENT_DISPATCH` 제거
- **L2** `MAX_AGENT_DEPTH=1`: depth=2 진입 시 즉시 `[depth-guard]` 거부
- **L3** `_execute_tool` sentinel guard: hallucinate 호출도 `[error] sentinel tool ...` 반환

회귀 테스트: `backend/tests/test_subagent_isolation.py`

### 산출물 저장 패턴 (`save_artifact` + `turn_slot`)

LLM이 파일을 직접 영속화할 수 있는 유일한 경로. `backend/agent/tools/artifact.py`.

```python
# 표준 체인 — LLM이 한 턴에서 실행하는 순서
save_artifact(filename="report.md", content="# ...", kind="markdown")
# → result/<session>/<ts>/report.md 생성, 반환값에 상대경로 포함
display_markdown(source="result/<session>/<ts>/report.md")
```

- **`turn_slot()`** (`core/result_store.py`): 같은 턴 내 `save_artifact` 를 여러 번 호출해도 단일 타임스탬프 폴더를 재사용한다. 새 턴 진입 시 `set_session_context()` 가 캐시를 리셋.
- filename 에 `/`, `\`, `..`, 절대경로 포함 시 `is_error=True` 반환.
- `kind` 와 파일 확장자가 불일치해도 `is_error=True` (예: `kind="markdown"`, `filename="data.json"`).

### AgentMeta 확장 필드 (`AGENTS/*.md` Front Matter)

`backend/agent/registries/agents.py`의 `AgentMeta` 에 CrewAI 스타일 Optional 필드 추가:

| 필드 | 설명 |
|---|---|
| `role` | 에이전트 직무 정체성 한 줄 (예: "시니어 소프트웨어 엔지니어") |
| `goal` | 에이전트가 달성하려는 궁극 목표 한 줄 |
| `when_to_delegate` | 오케스트레이터가 이 에이전트로 위임해야 하는 상황 설명 |

세 필드 모두 Optional — 기존 `.md` 파일은 변경 없이 파싱 가능. 값이 있으면 오케스트레이터 카탈로그와 서브 에이전트 자기 인식 헤더에 자동으로 주입된다.

---

## 주요 명령어

```powershell
# 개발 서버 (백엔드 먼저, Vite가 /api를 프록시)
uv run python backend/main.py          # 터미널 1
cd frontend; npm run dev               # 터미널 2 — http://localhost:5173

# 의존성
uv sync --dev
cd frontend; npm install

# 린트/포맷 — 변경 후 반드시 실행
uv run ruff format . && uv run ruff check --fix .

# 테스트
cd backend && uv run python -m pytest tests/ -v
cd backend && uv run python -m pytest tests/test_subagent_isolation.py -v

# 프로덕션 빌드 / 릴리즈
pwsh packaging/release.ps1
pwsh packaging/release.ps1 -Upload -Notes "..."         # .env에서 Nexus 자격증명 자동 로드
pwsh packaging/release.ps1 -Force                       # git dirty 상태나 버전 중복 강제 통과
pwsh packaging/release-dryrun.ps1                       # 네트워크 없이 업데이트 파이프라인 검증
pwsh packaging/release-dryrun.ps1 -Force
```

산출물: `release/{AppName}.exe`, `release/{AppName}-X.X.X.exe`, `release/latest.json`

---

## 환경 변수 (`.env` / `backend/core/config.py` · `backend/agent/config.py`)

`.env`는 dev 전용이며 **빌드 파이프라인의 단일 진실 공급원**. frozen EXE는 OS 환경 변수만 읽는다.

| 환경 변수 | 기본값 | 설명 |
|---|---|---|
| `APP_HOST` | `127.0.0.1` | 바인드 주소 |
| `APP_PORT` | `8765` | 포트 |
| `APP_NAME` | `MyAgent` | 앱 이름 (EXE 파일명, settings.json 경로) |
| `APP_NEXUS_BASE_URL` | (내부 기본값) | 업데이트 저장소 URL |
| `APP_NEXUS_USER` | — | release.ps1 자동 업로드용 계정 |
| `APP_NEXUS_PASSWORD` | — | release.ps1 자동 업로드용 비밀번호 |
| `APP_STARTUP_GRACE` | `60` | 최초 presence 연결 대기 상한 (초) |
| `APP_SHUTDOWN_GRACE` | `2` | 마지막 클라이언트 사라진 후 종료까지 (초) |
| `APP_PRESENCE_RECONNECT_GRACE` | `2` | F5/블립 흡수 재연결 허용 시간 (초) |
| `APP_UPDATE_CHECK_TIMEOUT` | `5` | latest.json GET 타임아웃 (초) |
| `APP_UPDATE_DOWNLOAD_TIMEOUT` | `60` | EXE 다운로드 타임아웃 (초) |
| `APP_UPDATE_CHECK_CACHE_TTL` | `300` | /api/update/check 캐시 TTL (초) |
| `APP_LLM_PROVIDER` | `mock` | 초기 settings.json 시드용 (`mock` \| `dtgpt` \| `openai_compatible`) |
| `APP_DTGPT_BASE_URL` | — | DTGPT 엔드포인트 — UI 비노출, 런타임에 factory가 직접 읽음 |
| `APP_DTGPT_MODEL` | — | DTGPT 기본 모델명 — settings.json 최초 시드 시만 적용, 이후 UI 우선 |
| `APP_SYSTEM_PROMPT` | (내장 한국어 프롬프트) | LLM 시스템 프롬프트 |
| `APP_LLM_TEMPERATURE` | `0.7` | 생성 temperature |
| `APP_LLM_MAX_TOKENS` | — | 미설정 시 provider 기본값 |
| `APP_MAX_AGENT_ITERATIONS` | `5` | 한 턴당 provider→tool 반복 상한 |
| `APP_MAX_AGENT_CALLS_PER_TURN` | `10` | 오케스트레이터+서브 에이전트 합산 provider 호출 상한 (TurnBudget) |
| `APP_MAX_AGENT_DEPTH` | `1` | 서브 에이전트 호출 깊이 상한 (1 이상 변경 시 경고) |
| `APP_MAX_HISTORY_MESSAGES` | `40` | 클라이언트당 보관 메시지 수 상한 |
| `APP_SETTINGS_TEST_TIMEOUT` | `10` | 연결 테스트 타임아웃 (초) |
| `APP_TOOL_DEFAULT_TIMEOUT` | `30` | Tool 1회 실행 timeout (초) — 도구별 `timeout_seconds` 로 override |

> `.env` 값에 `# 인라인 주석`이 있어도 파서가 자동으로 제거한다.

---

## 상세 문서

**`.claude/rules/`** — Claude Code 전용 아키텍처 참고서

| 파일 | 내용 |
|---|---|
| `backend_architecture.md` | App 생명주기 · presence 설계 · 동시성 · Origin 가드 · frozen 경로 · 에이전트 하니스 · AgentRegistry |
| `frontend_architecture.md` | Svelte 5 상태 패턴 · 컴포넌트 책임 · ModelPicker · localStorage 스키마 · 데이터 흐름 |
| `settings_architecture.md` | LLM 설정 저장 구조(멀티 프로바이더) · API key 보안 · ModelPicker API · threading.Lock 주의 |
| `update_architecture.md` | 자동 업데이트 4단계 흐름 · rename-to-backup 전략 · PowerShell 5.1 주의점 |
| `agent_extension.md` | 새 API Tool 등록 패턴 · 새 서브 에이전트 등록 방법 |
| `code_conventions.md` | Python 코딩 규칙 · ruff · 타입 힌트 · docstring · 예외 처리 |

**`docs/`** — 에이전트·도구 개발자 참고서

| 파일 | 내용 |
|---|---|
| `builtin-tools.md` | 내장 도구(save_artifact·display_image·display_chart·display_markdown·add_todo 등) 인자·동작·예시 |
| `mock-scenarios.md` | MockProvider 전체 시나리오(A~E) 트리거·흐름·산출물 경로·신규 시나리오 추가 방법 |
| `skills.md` | `SKILLS/*.md` Front Matter 필드, 트리거 매칭 원리, 본문 작성 패턴 |
| `agents.md` | `AGENTS/*.md` Front Matter 필드, Case 3 라우팅, 페르소나 작성법 |
| `prompts.md` | `PROMPTS/*.md` 파일별 역할, 합성 순서(`base → safety → tools_guide → orchestrator`), 핫리로드 정책 |
