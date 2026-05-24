# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

Svelte(Vite) 정적 자산을 FastAPI가 서빙하고 PyInstaller로 단일 `.exe`로 패키징하는 AI Agent 채팅 UI 앱.
다중 대화 세션(localStorage 영속화) · LLM 설정 UI · Nexus 자동 업그레이드(sha256 검증, self-replace) 내장.

- Python 패키지 관리: `uv`
- JS 패키지 관리: `npm`
- 빌드 산출물 흐름: **`build/` (중간)** → **`release/` (Nexus 업로드 대상)**

**앱 이름 변경**: `packaging/App.spec`의 `name='...'` 값 하나만 바꾸면 된다. `release.ps1`이 regex로 읽어 파일명·Nexus 경로를 자동 결정한다.

---

## 주요 명령어

### 개발 서버

dev 모드는 백엔드/프론트엔드 분리 실행. Vite dev server가 `/api`를 백엔드로 프록시하므로 **백엔드를 먼저 띄워야** 한다.

```powershell
# 터미널 1 — 백엔드 (uvicorn)
uv run python backend/main.py

# 터미널 2 — 프론트엔드 (Vite HMR, http://localhost:5173)
cd frontend; npm run dev
```

### 의존성 설치

```powershell
uv sync --dev                 # Python
cd frontend; npm install      # JS (marked, dompurify, highlight.js 포함)
```

### 린트 / 포맷 (변경 후 반드시 실행)

```powershell
uv run ruff format . && uv run ruff check --fix .
```

### 프로덕션 빌드 / 릴리즈

```powershell
# 권장: 통합 스크립트 (web 번들 + Updater.exe + App.exe + latest.json 일괄 생성)
pwsh packaging/release.ps1

# Nexus 업로드까지
pwsh packaging/release.ps1 -Upload `
  -NexusBaseUrl https://nexus.internal/repository/myapp `
  -NexusUser <id> -NexusPass <pw> -Notes "변경사항"

# 네트워크 없이 로컬 Nexus mock으로 업데이트 파이프라인 검증
pwsh packaging/release-dryrun.ps1
```

산출물: `release/{AppName}.exe`, `release/{AppName}-X.X.X.exe`, `release/latest.json`

---

## 아키텍처 — 큰 그림

### 디렉터리

```
backend/
  config.py           경로·env var 해석의 단일 진실 공급원
  main.py             uvicorn 기동, watchdog 스레드
  browser.py          presence 클라이언트 추적 + watchdog
  updater.py          자동 업데이트 로직
  routers/api.py      FastAPI 라우터 전체 (chat, settings, presence, update)
  chat/               harness(턴 루프) · store(히스토리) · tools · models
  chat/providers/     factory + mock + openai (프로바이더 패키지)
  settings/           LLM 설정 저장소 (models, store, masking)

frontend/src/
  App.svelte          레이아웃 셸 — <Sidebar><TopBar><ChatArea><Composer> 조합만
  app.css             CSS 변수 기반 테마 토큰 (라이트/다크)
  lib/                순수 로직 모듈 (컴포넌트 의존 없음)
  components/         UI 컴포넌트

updater/              self-replace 부트스트랩 (별도 Updater.exe)
packaging/            App.spec · Updater.spec · release.ps1 · release-dryrun.ps1
build/                중간 산출물 (gitignored)
release/              최종 산출물 (gitignored)
.env                  전체 환경 변수 레퍼런스 (dev 전용)
```

> 프론트엔드 상세 구조 → `.claude/rules/frontend_architecture.md`
> LLM 설정 아키텍처 → `.claude/rules/settings_architecture.md`

### 산출물 흐름

```
frontend/src  ─(vite)──► build/web/
updater/      ─(PyI)───► build/updater/Updater.exe
                                    └──► release/{AppName}.exe ──► sha256+copy ──► release/{AppName}-X.X.X.exe + latest.json
```

`build/`는 App EXE 안에 임베드되는 중간물(`sys._MEIPASS/web`, `sys._MEIPASS/updater/Updater.exe`).

### PyInstaller frozen 경로 분기 — 핵심

`backend/config.py`의 `_project_root()`가 모든 경로의 진실 공급원.

- **frozen**: `sys._MEIPASS` → 정적 자산 `MEIPASS/web`, Updater `MEIPASS/updater/Updater.exe`
- **dev**: 프로젝트 루트 → 정적 자산 `build/web/`

→ **새 정적 자산을 추가하면 반드시 `packaging/App.spec`의 `datas`에도 등록**해야 frozen에서 보인다.

### App 생명주기 (EXE 기동 시)

1. `backend/main.py` → `uvicorn.Config + Server` 생성, `browser.server`에 보관
   (Windows `os.kill(SIGTERM)`은 lifespan shutdown을 실행하지 않으므로 `server.should_exit = True` 경로만 사용)
2. watchdog + open_browser 데몬 스레드 시작 → `server.run()`
3. 브라우저 로드 → `initApp()`이 localStorage에서 세션 복원, 활성 세션 id로 `/api/presence` EventSource 오픈
4. `browser.connect_client(id)` 호출됨 — 연결 유지 = 생존 신호. 30초마다 `: ping`으로 idle timeout 방지
5. 탭 닫기 → EventSource 종료 → `finally`에서 `browser.disconnect_client` → `PRESENCE_RECONNECT_GRACE`(2s) 후 실제 제거
6. `browser.watchdog`이 클라이언트 부재 감지 → `SHUTDOWN_GRACE` 경과 시 `server.should_exit = True`

### 동시성 모델

`backend/browser.py`의 `clients: set[str]`과 `_pending_disconnects: dict[str, threading.Timer]`는 **uvicorn event-loop · watchdog 스레드 · `threading.Timer` 콜백** 3곳에서 동시 접근한다.

- 모든 read/write는 `_lock` 안에서 수행
- 순회는 `_snapshot()`이 `set(clients)`를 락 안에서 스냅샷한 뒤 락 밖에서 처리
- `Timer.cancel()` / `Timer.start()`는 자체 락을 가지므로 우리 `_lock` **밖**에서 호출 (lock ordering)
- `_ever_registered` 플래그로 "최초 연결 이전 STARTUP_GRACE 대기"와 "연결 후 비어있음(SHUTDOWN_GRACE)"을 구분

### Origin 가드 — 보안 경계

`backend/routers/api.py`의 `require_local_origin`이 router 레벨에 걸려 있다.

- **frozen(EXE)**에서만 활성. dev는 Vite proxy가 다른 origin이므로 자동 패스.
- `Origin` 헤더 있으면 `ALLOWED_ORIGIN`(`http://127.0.0.1:8765`)과 일치 확인
- 없으면 `sec-fetch-site`가 `same-origin`/`none`이어야 함

### 자동 업데이트 — 4단계 흐름

```
① check_latest()    NEXUS_BASE_URL/latest.json GET, 5분 캐시
                    URL prefix·sha256 hex(64자) 검증 → 실패 시 silently update_available=False
② apply_update()    스트리밍 다운로드 → sha256 검증 → {stem}.new.exe staging
                    → DETACHED Updater.exe Popen(pid, new, current) → 1s 후 server.should_exit
③ Updater.exe       부모 pid 폴링(최대 60s) → POST_EXIT_GRACE 3s 추가 대기
④ rename-to-backup  current → .old (rename은 잠긴 파일도 허용)
                    → new → current → 실패 시 .old 복원 후 재기동
```

**중요**: 방금 종료된 EXE의 잔존 잠금 + AV 스캔 때문에 `os.replace(new, current)` 직접 시도는 `ERROR_ACCESS_DENIED` 발생. **rename-to-backup 전략**으로 30회 × 0.5s 재시도. 이 전략으로 회귀시키지 말 것.

진행 상태: `GET /api/update/status` → `{status, progress, total, message, target_version}` (`idle|downloading|verifying|staging|restarting|error`)

---

## 환경 변수 (`backend/config.py` / `.env`)

`.env`는 dev 전용. frozen EXE는 OS 환경 변수만 읽는다 (`load_dotenv` 호출 안 함).
모든 상수는 `os.environ.get("APP_*", "<기본값>")` 패턴 — `.env`에서 주석 해제하거나 시스템 환경 변수로 주입.

| 환경 변수 | 기본값 | 설명 |
|---|---|---|
| `APP_HOST` | `127.0.0.1` | 바인드 주소 (vite.config.js와 공유) |
| `APP_PORT` | `8765` | 포트 (vite.config.js와 공유) |
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
| `APP_LLM_PROVIDER` | `mock` | 초기 settings.json 시드용 (이후엔 settings.json 우선) |
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

## Release 스크립트 — PowerShell 5.1 주의점

- `param()` 블록은 **반드시 첫 실행문** (앞에 `[Console]::OutputEncoding=` 두면 파싱 에러)
- JSON·`_version.py`는 **BOM 없는 UTF-8** — `[System.IO.File]::WriteAllText(path, content, (New-Object System.Text.UTF8Encoding $false))` 사용 (`Set-Content -Encoding utf8`은 BOM 붙어 `Invoke-RestMethod` 파싱 실패)
- `Write-Host` 한글 깨짐 → 스크립트 출력은 영어 유지
- Nexus 업로드: **EXE 먼저 → latest.json 마지막** (클라이언트가 404 EXE 보지 않도록)

---

## 코드 컨벤션

Python 협업 규칙 → `.claude/rules/code_conventions.md`

핵심 요약:
- 변경 후 반드시 `uv run ruff format . && uv run ruff check --fix .`
- 타입 힌트 100%, `Any` 지양, `except Exception:` 광범위 묵살 금지
- Google-style docstring, f-string 강제, Early Return 권장
- Pydantic `BaseModel` + `Annotated`로 데이터 계층 구조화
- 한글 주석은 **Why**만 (What은 코드로)
