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
| 업데이트 배포 | GitHub Enterprise Releases (gh CLI) |

---

## 프로젝트 구조

```
svelte-fastapi-exe/
├── .env                   # 전체 환경 변수 레퍼런스 (dev only) — SSOT for APP_NAME, 저장소 설정
├── PROMPTS/               # base.md + safety.md + orchestrator.md — system prompt 합성
├── SKILLS/                # 작업별 가이드 (Front Matter trigger 라우팅, lazy load)
├── AGENTS/                # 서브 에이전트 페르소나 (Front Matter: name/description/skills/tools)
├── backend/
│   ├── main.py            # FastAPI 앱, uvicorn 서버, SPA 라우팅
│   ├── _version.py        # 앱 버전 단일 소스 (release.ps1 이 자동 갱신)
│   ├── core/              # 앱 인프라 (LLM 무관)
│   │   ├── config.py      # RESULT_DIR 등 모든 경로·타이머 상수
│   │   └── result_store.py# 산출물 경로 관리 (artifact_slot, session_dir_name 등)
│   ├── scripts/           # 프로젝트 전용 Python 유틸리티 패키지 (__init__.py 필수)
│   │                      # APP_ALLOWED_LIBRARIES=scripts + api_refs 로 SKILL에서 사용
│   ├── agent/             # LLM 에이전트 런타임
│   │   ├── harness/       # 핵심 턴 루프 패키지 (loop·call_handlers·dispatch·prompt·state 등)
│   │   ├── tools/         # @register_tool 기반 사내 API 도구 모음
│   │   │   ├── runtime.py # 라이브러리 런타임 8개 메타 도구 (exec_code 등)
│   │   │   └── visualize.py # display_image / display_chart / display_markdown
│   │   ├── runtime/       # 세션 namespace · evaluator · introspect (library runtime 인프라)
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
│   ├── App.spec           # PyInstaller 스펙 — .env에서 APP_NAME/채널 자동 읽음
│   ├── release.ps1        # 빌드 + sha256 + GitHub Release 게시 자동화 (-Channel 필수)
│   └── release-dryrun.ps1 # 로컬 HTTP mock 으로 릴리즈 파이프라인 검증
├── docs/                  # 에이전트·도구 개발자 참고 문서
├── build/                 # 중간 산출물 (gitignored)
├── result/                # 에이전트 실행 산출물 (gitignored) — {제목}-{id8}/{timestamp}/
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
                                                ─(gh release create)─► GitHub Release 에 첨부
```

`build/`는 EXE 안에 임베드되는 중간물, `release/`는 GitHub Release에 첨부되는 최종물.

---

## Harness 이벤트 & UI 컴포넌트 매핑

백엔드 harness(`backend/agent/harness/`)는 SSE 스트림으로 이벤트를 발행하고, 프론트엔드는 이를 수신해 컴포넌트를 갱신한다.

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
| **루프 감지** | `harness/state/loop_guard.py` | 동일 도구·동일 인자(+파일 fingerprint) 재호출 차단, RCA 유도 메시지 주입 |
| **에러 회복** | `harness/tool_exec.py` `_execute_tool` | `is_error=True` 결과에 RCA + 1회 재시도 유도 메시지 자동 append |
| **Fallback** | `harness/loop.py` else 절 | `max_iterations` 도달 시 tools 없이 LLM 재호출 → `is_fallback=true` ErrorEvent |
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
| `analyst_agent` | "데이터 요약", "요약 통계" 등 | 데이터 분석·차트 생성 전담 (Mock 시나리오 D) |
| `writer_agent` | "전체 분석 보고서", "종합 보고서" 등 | Markdown 보고서 작성·이미지 생성 전담 (Mock 시나리오 E) |

### 라이브러리 런타임 (`api_refs`)

`.venv` 에 설치된 외부 Python 라이브러리(또는 `backend/scripts/`)를 SKILL/AGENT 에서 직접 호출할 수 있다.
`@register_tool` 래핑 없이 `api_refs` 한 줄만 추가하면 LLM 이 해당 함수의 시그니처를 인지하고 8개 메타 도구로 실행한다.

```yaml
# SKILLS/sensor_max.md Front Matter 예시
api_refs:
  - sensordx.utils.load_df   # 함수 시그니처가 system prompt 에 자동 주입
```

LLM 은 `call_function` / `eval_expression` / `exec_code` 등 8개 메타 도구로 라이브러리를 호출하고 결과를 세션 namespace 에 보관한다.
`.env` 의 `APP_ALLOWED_LIBRARIES` CSV 에 등록된 패키지만 허용 (보안 화이트리스트).
App.spec 빌드 시 이 목록을 읽어 `collect_all()` 을 자동 실행 → EXE 에도 번들링됨.

자세한 내용: [docs/guides/library-runtime.md](docs/guides/library-runtime.md)

### 아티팩트 패널 & 산출물 저장

도구가 `display_image` / `display_chart` / `display_markdown` 을 호출하면 채팅창 우측 아티팩트 패널이 열린다.  
파일 기반 산출물은 `result/` 하위에 저장되며, `/api/chat?session_title=...` query param 으로 전달된 세션 제목이 폴더명에 반영된다.

```
result/{세션제목}-{id[:8]}/{YYYYMMDD-HHmmss}/파일
```

`backend/core/result_store.py` 의 `artifact_slot()` 이 슬롯을 생성하고, `contextvars` 로 세션 메타를 도구까지 전달한다 — 도구 시그니처 변경 없음.

### 에이전트 런타임 안전장치

| 장치 | 동작 |
|---|---|
| **루프 감지** | 동일 도구·동일 인자 재호출 시 차단 후 RCA 유도 |
| **에러 회복** | 도구 실패 시 `result.content`에 RCA + 1회 재시도 유도 메시지 자동 주입 |
| **Fallback** | `max_iterations` 도달 시 LLM을 한 번 더 호출해 자연어 완료 보고 생성 |

### 실행 흐름 (EXE 기동 시)

```
App.exe 실행
  ├─ create_server_socket(): APP_NAME 해시 기반 고정 포트 바인딩 (47100–48999, 충돌 시 +1..+4 폴백)
  ├─ uvicorn.Server 생성 (소켓 직접 전달) → browser.server 에 보관
  ├─ watchdog 스레드: presence 연결 감시, 모두 사라지면 서버 종료
  └─ open_browser 스레드: 1초 후 바인딩된 고정 포트로 브라우저 자동 오픈

브라우저 → http://127.0.0.1:{고정 포트}   (frontend 는 상대 경로만 쓰므로 포트를 몰라도 됨)
  ├─ initApp(): localStorage 에서 세션 복원 → /api/presence SSE 오픈
  ├─ /api/conversation/restore: localStorage 히스토리 → 백엔드 LLM context 주입
  └─ /api/update/check: GitHub REST API releases/latest 조회 → latest.json 에셋 비교 (5분 캐시)
```

### 세션 관리

- **localStorage가 진실의 원천**: 세션 목록·메시지·테마를 브라우저 localStorage에 저장
- **세션 id = 백엔드 client_id**: `crypto.randomUUID()`로 생성, presence 채널·conversation store 키로 공유
- **hydrate 방향**: 앱 시작·세션 전환 시 프론트 → 백엔드로 히스토리 주입 (`POST /api/conversation/restore`)

### LLM 설정

- 사이드바 하단 **ModelPicker**에서 현재 프로바이더·모델을 표시하고 클릭 한 번으로 빠르게 모델 전환
- UI 기어 아이콘 → 설정 모달에서 프로바이더 선택 후 모델·API 키 입력 (프로바이더 순서: DTGPT → OpenAI Compatible → Mock)
- 각 프로바이더의 접속 정보는 독립 슬롯에 저장 — 프로바이더 전환 후 다시 돌아와도 이전 설정 유지
- `%APPDATA%\{APP_NAME}\settings.json` (frozen) 또는 `backend/settings/settings.json` (dev)에 영속화
- **DTGPT**: Base URL은 `.env`의 `APP_DTGPT_BASE_URL`에서 고정 로드 — UI에 노출하지 않음. 기본 모델명은 `APP_DTGPT_MODEL`로 초기 시드
- **OpenAI Compatible**: Base URL·모델·API 키 모두 UI에서 입력
- temperature, max_tokens, system_prompt는 `.env` / 환경 변수로 제어 (설정 모달 미노출)
- 설정 변경 즉시 반영 (서버 재시작 불필요 — 매 `/api/chat` 요청마다 최신 설정 로드)

### 자동 업데이트 흐름

```
① 앱 시작 → /api/update/check → GitHub REST API {api_base}/repos/{owner}/{repo}/releases/latest 조회
   → assets[]에서 latest.json 에셋을 octet-stream으로 받아 버전 비교
   QA 채널은 업데이트 차단(네트워크 호출 없이 즉시 반환)
② 새 버전 있으면 UI 배너 표시 → 사용자 "지금 업데이트" 클릭
③ /api/update/apply:
     - EXE 에셋 API URL을 APP_REPO_READ_TOKEN(read-only PAT) + octet-stream 헤더로 인증 다운로드 (스트리밍, sha256 검증)
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

`pyproject.toml`의 `version`만 수정한다. `_version.py`는 App.spec이 빌드 시 자동 생성한다.

```toml
[project]
version = "0.2.0"
```

### 2. (선택) 저장소 설정 확인

`.env` 파일이 빌드 파이프라인의 단일 진실 공급원이다.

```dotenv
APP_NAME=MyAgent                          # EXE 파일명, settings.json 경로
APP_REPO_BASE_URL=https://<ghe-host>/<org>/<repo>          # 레포 루트 (REST API base·owner/repo 유도)
APP_REPO_READ_TOKEN=ghp_...               # 읽기 전용 PAT — EXE에 번들됨 (릴리즈 메타·EXE 다운로드 인증)
```

> updater는 `APP_REPO_BASE_URL`에서 REST API base(`.../api/v3`)와 owner/repo를 자동 유도한다. private 레포 에셋은 브라우저 다운로드 URL이 PAT 헤더를 무시하므로(404), 메타·EXE 모두 REST API(`releases/latest` + `assets/{id}`)로 받는다. 그래서 별도 latest.json 포인터 URL 환경변수는 필요 없다.

업로드 인증은 **gh CLI가 담당**한다. `.env`에 쓰기 토큰을 두지 않는다.

```powershell
# GitHub.com
gh auth login
# GitHub Enterprise
gh auth login --hostname <ghe-host>
# 또는 환경 변수로 CI 주입
$env:GH_HOST = "<ghe-host>"; $env:GH_TOKEN = "<write-PAT>"
```

### 3. 릴리즈 스크립트 실행

`-Channel` 옵션이 **필수**다 — 생략하면 에러로 종료한다.

```powershell
# QA 빌드: Mock 노출, 자동업데이트 차단, --prerelease 게시
pwsh packaging/release.ps1 -Channel qa

# Prod 빌드: Mock 제외, 자동업데이트 활성, full release 게시 → latest 포인터 갱신
pwsh packaging/release.ps1 -Channel prod -Upload -Notes "변경사항 요약"

# git dirty 상태를 강제 통과
pwsh packaging/release.ps1 -Channel prod -Upload -Force -Notes "핫픽스"
```

스크립트 수행 작업:

1. **사전 점검**: git dirty 상태 확인 (`-Force`로 우회 가능)
2. `pyproject.toml` 버전 읽기 (App.spec이 빌드 중 `_version.py` 자동 생성)
3. `npm run build` (Svelte → `build/web/`)
4. 확장 프론트 빌드 (`extensions/*/frontend` → 각 `dist/`)
5. `pyinstaller packaging/Updater.spec` → `build/updater/Updater.exe`
6. `pyinstaller packaging/App.spec` → `release/{AppName}.exe`  
   (채널 정보를 번들 `.env`에 박음 — Mock 노출·업데이트 차단 여부가 EXE에 각인됨)
7. sha256 계산 + `release/latest.json` 생성
8. `-Upload` 시: `gh release create v{version}` 으로 GitHub Release에 EXE·latest.json 첨부  
   (qa: `--prerelease` → `releases/latest` 포인터에 잡히지 않음)

### 4. Dry-run (업로드 없이 로컬 검증)

```powershell
pwsh packaging/release-dryrun.ps1                     # 클린 상태 필요
pwsh packaging/release-dryrun.ps1 -Channel qa -Force  # dirty 브랜치에서도 가능
```

로컬 HTTP 서버로 GitHub Releases를 흉내내고, 업데이트 감지·다운로드·sha256 검증까지 실제 네트워크 없이 테스트.

---

## `latest.json` 포맷

```json
{
  "version": "0.2.0",
  "url": "https://<ghe-host>/<org>/<repo>/releases/download/v0.2.0/MyAgent.exe",
  "sha256": "a1b2c3...64자 hex",
  "size": 18742912,
  "released_at": "2026-05-23T09:00:00+09:00",
  "min_supported_version": "0.0.0",
  "notes": "릴리즈 노트"
}
```

`url`은 **버전 핀 에셋 경로**(`releases/download/v{version}/...`, 브라우저 형식)다. updater는 이 url을 다운로드에 직접 쓰지 않고 **EXE 파일명 추출용**으로만 사용한다 — 실제 다운로드는 `releases/latest` REST API 응답의 `assets[].url`(API 에셋 경로)을 octet-stream으로 받는다. `releases/latest` API는 full release(비-prerelease)만 반환하므로 QA 빌드는 잡히지 않는다.

## 업데이트 API

| 엔드포인트 | 설명 |
|---|---|
| `GET /api/version` | 현재 버전 반환 |
| `GET /api/update/check` | GitHub Releases latest.json 조회, 5분 캐시 (QA 채널은 즉시 `update_available=false`) |
| `POST /api/update/apply` | 다운로드(read-only PAT 인증)·검증·updater 기동·graceful shutdown |
| `GET /api/update/status` | 진행 상태 폴링 (`idle\|downloading\|verifying\|staging\|restarting\|error`) |

## 보안 가드레일

- **Origin 가드**: EXE 환경에서 실제 바인딩된 origin(`http://127.0.0.1:{고정 포트}`) 이외에서 오는 `/api/*` 요청을 403으로 차단
- **sha256 무결성 검증**: 다운로드 후 latest.json의 sha256과 불일치하면 임시 파일 삭제, 현재 EXE 보존
- **API 키 보안**: settings.json에만 저장, 응답 시 항상 마스킹, localStorage에 저장 안 함
- **자격증명 분리**: 읽기 전용 PAT(`APP_REPO_READ_TOKEN`)만 EXE에 번들 — 업로드 쓰기 토큰은 gh CLI가 담당하며 EXE에 포함되지 않음
- **EXE 먼저, latest.json 마지막**: `gh release create`는 EXE와 latest.json을 한 번에 올리지만 GitHub 측에서 EXE가 항상 먼저 조회 가능해짐(파일 단위 원자 업로드)
