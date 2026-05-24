# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

Svelte(Vite) 정적 자산을 FastAPI가 서빙하고 PyInstaller로 단일 `.exe`로 패키징하는 AI Agent 채팅 UI 앱.
다중 대화 세션(localStorage 영속화) · LLM 설정 UI · Nexus 자동 업그레이드(sha256 검증, self-replace) 내장.

- Python 패키지 관리: `uv` / JS 패키지 관리: `npm`
- 빌드 산출물 흐름: **`build/` (중간)** → **`release/` (Nexus 업로드 대상)**
- **앱 이름 변경**: `packaging/App.spec`의 `name='...'` 값 하나만 바꾸면 된다.

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

# 프로덕션 빌드 / 릴리즈
pwsh packaging/release.ps1
pwsh packaging/release.ps1 -Upload -NexusBaseUrl https://... -NexusUser <id> -NexusPass <pw> -Notes "..."
pwsh packaging/release-dryrun.ps1     # 네트워크 없이 업데이트 파이프라인 검증
```

산출물: `release/{AppName}.exe`, `release/{AppName}-X.X.X.exe`, `release/latest.json`

---

## 디렉터리 구조

```
backend/
  main.py             uvicorn 기동, watchdog 스레드, prompt/skill registry 부팅 로드
  _version.py         앱 버전 단일 소스

  core/               앱 인프라 (LLM 무관)
    config.py         경로·네트워크·타이머·업데이트 URL — env var 단일 진실 공급원
    browser.py        presence 클라이언트 추적 + watchdog
    updater.py        자동 업데이트 로직

  agent/              LLM 에이전트 런타임
    config.py         SYSTEM_PROMPT · temperature · LLM 시드값 · 반복 상한
    harness.py        run_turn — 핵심 턴 루프
    guard.py          슬롯 가드
    models.py         Pydantic 메시지·이벤트·상태 (StreamEvent 등)
    stores/           영속·인메모리 저장소
      conversation.py ConversationStore (대화 히스토리)
      agent_state.py  AgentStateStore (todo · missing_slots 디스크 영속)
    registries/       에이전트가 인지하는 자산 카탈로그
      prompts.py      PromptRegistry
      skills.py       SkillRegistry
      tools.py        ToolRegistry
    providers/        LLM 어댑터
      factory.py      get_provider() 디스패처
      mock.py         Mock (테스트용)
      openai.py       OpenAI Compatible

  api/                HTTP 엔드포인트 (도메인별 분할)
    __init__.py       5개 라우터 통합 export
    deps.py           require_local_origin · 싱글톤 store 초기화
    chat.py           POST /api/chat, /api/conversation CRUD
    settings.py       GET/POST /api/settings, /providers, /test
    presence.py       GET /api/presence
    update.py         GET /api/version, /api/update/*
    skills.py         GET /api/skills, /api/debug/skill-route

  settings/           사용자 가변 LLM 설정 영속화
    config.py         SETTINGS_FILE_PATH · SETTINGS_TEST_TIMEOUT
    models.py         LLMSettings · ProviderMeta · ConnectionTest*
    store.py          SettingsStore (threading.Lock)
    masking.py        API 키 마스킹

PROMPTS/              base.md + safety.md — 모든 턴 system prompt 머리에 합성
SKILLS/               작업별 가이드. Front Matter trigger 로 라우팅, 매칭된 본문만 lazy 로드

frontend/src/
  App.svelte          레이아웃 셸
  app.css             CSS 변수 기반 테마 토큰 (라이트/다크)
  lib/                순수 로직 모듈
  components/         UI 컴포넌트

updater/              self-replace 부트스트랩 (별도 Updater.exe)
packaging/            App.spec · Updater.spec · release.ps1 · release-dryrun.ps1
```

**산출물 흐름**
```
frontend/src  ─(vite)──► build/web/
updater/      ─(PyI)───► build/updater/Updater.exe
                                    └──► release/{AppName}.exe ──► sha256 ──► release/{AppName}-X.X.X.exe + latest.json
```

> 새 정적 자산 추가 시 `packaging/App.spec` `datas` 등록 필수.  
> `PROMPTS/`, `SKILLS/` 는 디렉터리 단위 등록됨 — 파일 추가만으로 다음 빌드에 반영.

---

## 환경 변수 (`backend/core/config.py` · `backend/agent/config.py` · `backend/settings/config.py` / `.env`)

`.env`는 dev 전용. frozen EXE는 OS 환경 변수만 읽는다.

| 환경 변수 | 기본값 | 설명 |
|---|---|---|
| `APP_HOST` | `127.0.0.1` | 바인드 주소 |
| `APP_PORT` | `8765` | 포트 |
| `APP_STARTUP_GRACE` | `60` | 최초 presence 연결 대기 상한 (초) |
| `APP_SHUTDOWN_GRACE` | `2` | 마지막 클라이언트 사라진 후 종료까지 (초) |
| `APP_PRESENCE_RECONNECT_GRACE` | `2` | F5/블립 흡수 재연결 허용 시간 (초) |
| `APP_PRESENCE_KEEPALIVE_INTERVAL` | `30` | presence SSE ping 주기 (초) |
| `APP_PRESENCE_RETRY_HINT_MS` | `1000` | EventSource retry 디렉티브 (ms) |
| `APP_NEXUS_BASE_URL` | (내부 기본값) | 업데이트 저장소 |
| `APP_UPDATE_CHECK_TIMEOUT` | `5` | latest.json GET 타임아웃 (초) |
| `APP_UPDATE_DOWNLOAD_TIMEOUT` | `60` | EXE 다운로드 타임아웃 (초) |
| `APP_UPDATE_CHECK_CACHE_TTL` | `300` | /api/update/check 캐시 TTL (초) |
| `APP_NAME` | `MyAgent` | 앱 이름 (settings.json 경로, EXE 파일명) |
| `APP_LLM_PROVIDER` | `mock` | 초기 settings.json 시드용 |
| `APP_LLM_BASE_URL` | — | 초기 시드용 |
| `APP_LLM_MODEL` | — | 초기 시드용 |
| `APP_LLM_API_KEY` | — | 초기 시드용 |
| `APP_SYSTEM_PROMPT` | (내장 한국어 프롬프트) | LLM 시스템 프롬프트 |
| `APP_LLM_TEMPERATURE` | `0.7` | 생성 temperature |
| `APP_LLM_MAX_TOKENS` | — | 미설정 시 provider 기본값 |
| `APP_MAX_AGENT_ITERATIONS` | `5` | 한 턴당 provider→tool 반복 상한 |
| `APP_MAX_HISTORY_MESSAGES` | `40` | 클라이언트당 보관 메시지 수 상한 |
| `APP_SETTINGS_TEST_TIMEOUT` | `10` | 연결 테스트 타임아웃 (초) |

---

## 상세 문서 (`.claude/rules/`)

| 파일 | 내용 |
|---|---|
| `backend_architecture.md` | App 생명주기 · presence 설계 · 동시성 · Origin 가드 · frozen 경로 · 에이전트 하니스 |
| `frontend_architecture.md` | Svelte 5 상태 패턴 · 컴포넌트 책임 · localStorage 스키마 · 데이터 흐름 |
| `settings_architecture.md` | LLM 설정 저장 위치 · API key 보안 · threading.Lock 주의 · 프로바이더 추가 방법 |
| `update_architecture.md` | 자동 업데이트 4단계 흐름 · rename-to-backup 전략 · PowerShell 5.1 주의점 |
| `code_conventions.md` | Python 코딩 규칙 · ruff · 타입 힌트 · docstring · 예외 처리 |
