# Svelte + FastAPI EXE

Vite/Svelte로 만든 AI Agent 채팅 UI를 FastAPI가 서빙하고, PyInstaller로 단일 `.exe`로 패키징하는 사내 배포용 데스크톱 앱 템플릿.
다중 대화 세션(localStorage 영속화) · LLM 설정 UI · Nexus raw repository 자동 업그레이드 내장.

> **이 프로젝트는 코드를 작성하는 AI 도구가 아니다.**
> 미리 갖추어진 Python API를 plan에 따라 실행하는 **API 실행 Agent 플랫폼**이다.

> **앱 이름 변경**: `.env` 파일의 `APP_NAME=MyAgent` 값만 수정하면
> `release.ps1`과 `App.spec`이 해당 이름으로 EXE를 자동 생성한다.

## 기술 스택

| 역할 | 기술 |
|---|---|
| 프론트엔드 | Svelte 5, Vite |
| 백엔드 | FastAPI, uvicorn |
| 에이전트 런타임 | 계층형 오케스트레이터-서브에이전트 구조 |
| 패키징 | PyInstaller (onefile) |
| 패키지 관리 | uv (Python), npm (JS) |
| 업데이트 배포 | Nexus OSS raw repository |

---

## 프로젝트 구조

```
svelte-fastapi-exe/
├── .env                   # 전체 환경 변수 레퍼런스 (dev only) — SSOT for APP_NAME, Nexus 설정
├── PROMPTS/               # base.md + safety.md + orchestrator.md — system prompt 합성
├── SKILLS/                # 작업별 가이드 (Front Matter trigger 라우팅, lazy load)
├── AGENTS/                # 서브 에이전트 페르소나 (Front Matter: name/description/skills/tools)
├── backend/
│   ├── main.py            # FastAPI 앱, uvicorn 서버, SPA 라우팅
│   ├── _version.py        # 앱 버전 단일 소스 (release.ps1 이 자동 갱신)
│   ├── core/              # 앱 인프라 (LLM 무관)
│   ├── agent/             # LLM 에이전트 런타임
│   │   ├── harness.py     # 핵심 턴 루프 (loop detection, error recovery, fallback 포함)
│   │   ├── tools/         # @register_tool 기반 사내 API 도구 모음
│   │   ├── registries/    # prompts, skills, tools, agents 카탈로그
│   │   └── providers/     # factory + mock + openai (LLM 프로바이더 패키지)
│   ├── api/               # /api/* 엔드포인트 — 도메인별 분할
│   ├── settings/          # LLM 설정 저장소 (models, store, masking)
│   └── tests/             # 회귀 테스트 (pytest)
├── frontend/src/
│   ├── App.svelte         # 레이아웃 셸
│   ├── lib/               # 순수 로직 모듈 (api, sse, storage, markdown, state 등)
│   └── components/        # UI 컴포넌트
├── updater/               # self-replace 부트스트랩 (별도 EXE 로 빌드)
├── packaging/
│   ├── App.spec           # PyInstaller 스펙 — .env에서 APP_NAME 자동 읽음
│   ├── release.ps1        # 빌드 + sha256 + Nexus 업로드 자동화
│   └── release-dryrun.ps1 # 로컬 Nexus mock 으로 릴리즈 파이프라인 검증
├── build/                 # 중간 산출물 (gitignored)
└── release/               # 최종 산출물 (gitignored, Nexus 업로드 대상)
    ├── {AppName}.exe
    ├── {AppName}-X.X.X.exe
    └── latest.json
```

### 빌드 산출물 흐름

```
frontend/src        ─(vite)──────────────────────────────► build/web/          ┐
updater/updater.py  ─(PyI, Updater.spec)─► build/updater/Updater.exe           ┤
                                                                                ├─(PyI, App.spec)─► release/{AppName}.exe
                                                                                ┘
release/{AppName}.exe ─(sha256 + copy)─► release/{AppName}-X.X.X.exe + release/latest.json
```

`build/`는 EXE 안에 임베드되는 중간물, `release/`는 Nexus에 올라가는 최종물.

---

## Harness 이벤트 & UI 컴포넌트 매핑

백엔드 harness(`backend/agent/harness.py`)는 SSE 스트림으로 이벤트를 발행하고, 프론트엔드는 이를 수신해 컴포넌트를 갱신한다.

| SSE 이벤트 (`type`) | 발생 조건 | 처리 UI 컴포넌트 | 화면 표현 |
|---|---|---|---|
| `delta` | LLM 응답 텍스트 청크 | `MessageBubble` | 마크다운 스트리밍 렌더링 |
| `tool_call` | LLM이 도구 호출 결정 | `MessageBubble` | `🔧 <도구명> 호출 중...` 상태 라벨 |
| `tool_result` | 도구 실행 완료 (성공/실패) | `MessageBubble` | `🔧`/`⚠️ <도구명> → <결과>` 상태 라벨 |
| `reasoning` | LLM 내부 추론 청크 (o-series) | `ReasoningBlock` | 접을 수 있는 "추론 과정" 블록 |
| `skill_active` | SKILL 트리거 매칭 직후 | `MessageBubble` | ✦ 스킬 이름 칩(뱃지) |
| `todo_update` | `add_todo` / `complete_todo` 호출 시 | `TodoProgress` | 접을 수 있는 체크리스트 (pending/running/completed/failed/skipped) |
| `skill_complete` | todo_list 전체 terminal 상태 도달 | `SkillCompleteBadge` | "작업 완료 N완료 M실패" 배지 |
| `ask_user` | 슬롯 가드 실패 또는 `ask_user` sentinel 호출 | `AskUserCard` | 질문 + 선택지 버튼 카드 (choice/text/both 모드) |
| `agent:switch` | 오케스트레이터가 서브 에이전트에게 위임 | `MessageBubble` (agentTrail) | `🔄 orchestrator → <에이전트명>` 칩 |
| `agent:return` | 서브 에이전트 작업 완료 후 복귀 | `MessageBubble` (agentTrail) | `✓ orchestrator → <에이전트명>` 칩 (accent) |
| `agent:progress` | 서브 에이전트의 delta/tool/todo/reasoning 래핑 | `MessageBubble` (agentProgress) | 들여쓰기 슬롯 — 내부 delta·tool status·todo·reasoning 표시 |
| `error` (`is_fallback=false`) | 예외 또는 budget 초과 | `MessageBubble` | `[error] ...` 텍스트 추가 |
| `error` (`is_fallback=true`) | max_iterations 도달 후 자연어 응답 | `MessageBubble` | 메시지에 danger 테마 (점선 테두리) |
| `done` | 턴 정상 종료 | `chatActions` | `ui.streaming = false`, localStorage flush |

### Harness 안전장치

| 장치 | 구현 위치 | 동작 |
|---|---|---|
| **슬롯 가드** | `agent/guard.py` | 도구 인자 누락 시 `AskUserEvent` 발행, 채워지면 다음 턴에 재호출 |
| **루프 감지** | `harness.py` `history_calls` set | 동일 도구·동일 인자 재호출 차단, RCA 유도 메시지 주입 |
| **에러 회복** | `harness.py` `_execute_tool` | `is_error=True` 결과에 RCA + 1회 재시도 유도 메시지 자동 append |
| **Fallback** | `harness.py` else 절 | `max_iterations` 도달 시 tools 없이 LLM 재호출 → `is_fallback=true` ErrorEvent |
| **Budget 가드** | `TurnBudget` | 오케스트레이터 + 서브 에이전트 provider 호출 합산 상한 |
| **중첩 위임 차단** | L0~L3 (harness + guard) | 서브 에이전트의 `call_sub_agent` 재호출 4중 방어 |

### ask_user 두 경로 비교

| 경로 | 트리거 | 상태 저장 |
|---|---|---|
| **슬롯 가드** | 도구 인자 형식/누락 오류 | `state.pending_tool` + `state.missing_slots` — 다음 턴에 자동 재호출 |
| **ask_user sentinel** | LLM이 능동적으로 `ask_user` 도구 호출 | `state.pending_question` — 다음 턴 system prompt에 질문 재주입 |

두 경로 모두 `AskUserCard`로 렌더링되며, 사용자 답변 시 `AskUserCard`가 `answered=true`로 전환된다.

---

## 개발 환경 설정

```powershell
# Python 의존성
uv sync --dev

# JavaScript 의존성
cd frontend; npm install
```

### 개발 서버 실행

```powershell
# 터미널 1 — 백엔드
uv run python backend/main.py

# 터미널 2 — 프론트엔드 (HMR)
cd frontend; npm run dev
```

프론트엔드 개발 서버(`http://localhost:5173`)는 `/api` 요청을 `http://127.0.0.1:8765`로 프록시한다.
Origin 가드는 dev 환경에서는 비활성화되므로 별도 설정 없이 동작한다.

### 린트·테스트

```powershell
# 린트/포맷 (변경 후 반드시 실행)
uv run ruff format . && uv run ruff check --fix .

# 테스트
cd backend && uv run python -m pytest tests/ -v
```

---

## 앱 아키텍처

### 에이전트 설계 원칙

이 프로젝트는 **미리 갖추어진 Python API를 plan에 따라 실행하는 Agent 플랫폼**이다.

| 상황 | 에이전트 행동 |
|---|---|
| 일반 질문 | 텍스트로 직접 답변 |
| 도구 실행 필요 | `add_todo` 로 plan 작성 → tool 순차 실행 → `complete_todo` |
| 복잡한 작업 | 오케스트레이터가 `call_sub_agent` 로 서브 에이전트에게 순차 위임 |

```
사용자 메시지
  └─ 오케스트레이터
       ├─ 단순 작업 → 직접 도구 실행 (add_todo → tool → complete_todo)
       └─ 복잡 작업 → call_sub_agent → 서브 에이전트
                                          └─ 자체 plan → 도구 실행 → complete_subagent
```

**서브 에이전트가 다시 서브 에이전트를 부르는 중첩 위임은 4중 방어선으로 차단된다.**
`AGENTS/` Front Matter의 `skills` 목록에 선언된 SKILL만 서브 에이전트가 사용할 수 있다.

현재 등록된 서브 에이전트:

| 에이전트 | 트리거 | 역할 |
|---|---|---|
| `coding_agent` | "코딩", "코드 작성" 등 | 코드 작업 전담 |
| `report_agent` | "리포트 에이전트", "report_agent" | Markdown 리포트 작성·`display_markdown` 렌더링 전담 |

### 에이전트 런타임 안전장치

| 장치 | 동작 |
|---|---|
| **루프 감지** | 동일 도구·동일 인자 재호출 시 차단 후 RCA 유도 |
| **에러 회복** | 도구 실패 시 `result.content`에 RCA + 1회 재시도 유도 메시지 자동 주입 |
| **Fallback** | `max_iterations` 도달 시 LLM을 한 번 더 호출해 자연어 완료 보고 생성 |

### 실행 흐름 (EXE 기동 시)

```
App.exe 실행
  ├─ uvicorn.Server 생성 → browser.server 에 보관
  ├─ watchdog 스레드: presence 연결 감시, 모두 사라지면 서버 종료
  └─ open_browser 스레드: 1초 후 브라우저 자동 오픈

브라우저 → http://127.0.0.1:8765
  ├─ initApp(): localStorage 에서 세션 복원 → /api/presence SSE 오픈
  ├─ /api/conversation/restore: localStorage 히스토리 → 백엔드 LLM context 주입
  └─ /api/update/check: Nexus latest.json 비교 (5분 캐시)
```

### 세션 관리

- **localStorage가 진실의 원천**: 세션 목록·메시지·테마를 브라우저 localStorage에 저장
- **세션 id = 백엔드 client_id**: `crypto.randomUUID()`로 생성, presence 채널·conversation store 키로 공유
- **hydrate 방향**: 앱 시작·세션 전환 시 프론트 → 백엔드로 히스토리 주입 (`POST /api/conversation/restore`)

### LLM 설정

- UI 기어 아이콘 → 설정 모달에서 프로바이더 선택 후 모델·API 키 입력 (프로바이더 순서: DTGPT → OpenAI Compatible → Mock)
- `%APPDATA%\{APP_NAME}\settings.json` (frozen) 또는 `backend/settings/settings.json` (dev)에 영속화
- **DTGPT**: Base URL은 `.env`의 `APP_DTGPT_BASE_URL`에서 고정 로드 — UI에 노출하지 않음. 기본 모델명은 `APP_DTGPT_MODEL`로 초기 시드
- **OpenAI Compatible**: Base URL·모델·API 키 모두 UI에서 입력
- temperature, max_tokens, system_prompt는 `.env` / 환경 변수로 제어 (설정 모달 미노출)
- 설정 변경 즉시 반영 (서버 재시작 불필요 — 매 `/api/chat` 요청마다 최신 설정 로드)

### 자동 업데이트 흐름

```
① 앱 시작 → /api/update/check → Nexus latest.json 비교
② 새 버전 있으면 UI 배너 표시 → 사용자 "지금 업데이트" 클릭
③ /api/update/apply:
     - 새 App.exe 다운로드 (스트리밍, sha256 검증)
     - 번들된 Updater.exe 를 detached 프로세스로 기동
     - uvicorn graceful shutdown
④ Updater.exe:
     - 기존 App.exe 종료 대기
     - 기존 EXE → .old 로 rename, 새 EXE → 원래 이름으로 rename
     - 새 App.exe 기동 후 자기 자신 종료
```

> **rename-to-backup 전략**: `os.replace()` 직접 시도는 잔존 잠금 + AV 스캔으로 `ERROR_ACCESS_DENIED` 발생.
> `current → .old` rename은 잠긴 파일에도 허용되므로 이 방식으로 우회한다.

---

## 릴리즈 절차

### 1. 버전 올리기

`pyproject.toml`의 `version`만 수정한다. `_version.py`는 스크립트가 자동 갱신한다.

```toml
[project]
version = "0.2.0"
```

### 2. (선택) 앱 이름 / Nexus URL 변경

`.env` 파일을 수정한다. 이 파일이 빌드 파이프라인의 단일 진실 공급원이다.

```dotenv
APP_NAME=MyAgent                         # EXE 파일명, settings.json 경로
APP_NEXUS_BASE_URL=https://nexus.internal/repository/myapp
APP_NEXUS_USER=nexus_admin               # 선택 — 없으면 실행 시 프롬프트
APP_NEXUS_PASSWORD=secret                # 선택 — 없으면 실행 시 프롬프트
```

### 3. 릴리즈 스크립트 실행

```powershell
# 빌드 + sha256 + latest.json 생성 + Nexus 업로드
# Nexus 자격증명은 .env 에서 자동 로드, 없으면 대화형 프롬프트
pwsh packaging/release.ps1 -Upload -Notes "변경사항 요약"

# git dirty 상태이거나 Nexus에 동일 버전이 이미 있을 때 강제 진행
pwsh packaging/release.ps1 -Upload -Force -Notes "핫픽스"
```

스크립트 수행 작업:

1. **사전 점검**: git dirty 상태·Nexus 버전 중복 확인 (`-Force`로 우회 가능)
2. `pyproject.toml` 버전 → `backend/_version.py` 동기화
3. `npm run build` (Svelte → `build/web/`)
4. `pyinstaller packaging/Updater.spec` → `build/updater/Updater.exe`
5. `pyinstaller packaging/App.spec` → `release/{AppName}.exe`
6. sha256 계산 + `release/latest.json` 생성
7. Nexus에 EXE 업로드 후 `latest.json` 업로드 (순서 보장, 3회 자동 재시도)

### 4. Dry-run (업로드 없이 로컬 검증)

```powershell
pwsh packaging/release-dryrun.ps1          # 클린 상태 필요
pwsh packaging/release-dryrun.ps1 -Force   # dirty 브랜치에서도 가능
```

로컬 HTTP 서버(기본 19800 포트)로 Nexus를 흉내내고, 업데이트 감지·다운로드·sha256 검증까지 실제 네트워크 없이 테스트.

---

## `latest.json` 포맷

```json
{
  "version": "0.2.0",
  "url": "https://nexus.internal/repository/myapp/MyAgent-0.2.0.exe",
  "sha256": "a1b2c3...64자 hex",
  "size": 18742912,
  "released_at": "2026-05-23T09:00:00+09:00",
  "min_supported_version": "0.0.0",
  "notes": "릴리즈 노트"
}
```

## 업데이트 API

| 엔드포인트 | 설명 |
|---|---|
| `GET /api/version` | 현재 버전 반환 |
| `GET /api/update/check` | Nexus latest.json 조회, 5분 캐시 |
| `POST /api/update/apply` | 다운로드·검증·updater 기동·graceful shutdown |
| `GET /api/update/status` | 진행 상태 폴링 (`idle\|downloading\|verifying\|staging\|restarting\|error`) |

## 보안 가드레일

- **Origin 가드**: EXE 환경에서 `http://127.0.0.1:8765` 이외의 origin에서 오는 `/api/*` 요청을 403으로 차단
- **sha256 무결성 검증**: 다운로드 후 latest.json의 sha256과 불일치하면 임시 파일 삭제, 현재 EXE 보존
- **API 키 보안**: settings.json에만 저장, 응답 시 항상 마스킹, localStorage에 저장 안 함
- **latest.json 나중 업로드**: EXE 업로드 완료 후 latest.json 업로드 — 404 EXE 경쟁 조건 방지
