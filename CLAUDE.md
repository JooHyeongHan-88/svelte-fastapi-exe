# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

Svelte(Vite) 정적 자산을 FastAPI가 서빙하고 PyInstaller로 단일 `.exe`로 패키징하는 AI Agent 채팅 UI 앱.
Nexus raw repository를 통한 자동 업그레이드(sha256 검증, self-replace) 인프라 내장.

- Python 패키지 관리: `uv`
- JS 패키지 관리: `npm`
- 빌드 산출물 흐름: **`build/` (중간)** → **`release/` (Nexus 업로드 대상)** 로 분리

**앱 이름 변경**: `App.spec`의 `name='...'` 값 하나만 바꾸면 된다. `release.ps1`이 regex로 그 값을 읽어 출력 파일명·Nexus 경로를 자동 결정한다.

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
uv sync --dev                 # Python (httpx, fastapi, uvicorn, pyinstaller)
cd frontend; npm install      # JS
```

### 프로덕션 빌드 / 릴리즈

```powershell
# 권장: 통합 스크립트 (web 번들 + Updater.exe + App.exe + latest.json 일괄 생성)
pwsh scripts/release.ps1

# Nexus 업로드까지 (EXE → latest.json 순서 보장됨)
pwsh scripts/release.ps1 -Upload `
  -NexusBaseUrl https://nexus.internal/repository/myapp `
  -NexusUser <id> -NexusPass <pw> -Notes "변경사항"

# 네트워크 없이 로컬 Nexus mock (http://127.0.0.1:19800) 으로 업데이트 파이프라인 검증
pwsh scripts/release-dryrun.ps1
```

산출물: `release/{AppName}.exe`, `release/{AppName}-X.X.X.exe`, `release/latest.json`
(`AppName` = `App.spec`의 `name=` 값)

### 수동 패키징 (스크립트 우회 시)

```powershell
cd frontend; npm run build; cd ..
uv run pyinstaller --noconfirm --clean --distpath build/updater --workpath build/pyi-updater Updater.spec
uv run pyinstaller --noconfirm --clean --distpath release --workpath build/pyi-app App.spec
```

---

## 아키텍처 — 큰 그림

### 디렉터리

```
backend/      FastAPI 앱 + 자동업데이트 로직 (main, config, browser, updater, routers/api)
frontend/     Svelte 5 SPA (App.svelte 단일 컴포넌트)
updater/      self-replace 부트스트랩 (별도 EXE)
scripts/      release.ps1, release-dryrun.ps1
build/        중간 산출물 (gitignored) — EXE 안에 임베드
release/      최종 산출물 (gitignored) — Nexus 업로드 대상
App.spec      App EXE PyInstaller 스펙 (build/web + build/updater/Updater.exe 임베드)
Updater.spec  Updater EXE PyInstaller 스펙
.env          공유 환경 변수 (APP_HOST, APP_PORT, APP_NEXUS_BASE_URL) — dev only
```

### 산출물 흐름

```
frontend/src     ─(vite)──►  build/web/                   ┐
updater/         ─(PyI)───►  build/updater/Updater.exe    ┴─►  release/{AppName}.exe  ─►  sha256+copy  ─►  release/{AppName}-X.X.X.exe + latest.json
```

`build/`는 App EXE 안에 임베드되는 중간물(`sys._MEIPASS/web`, `sys._MEIPASS/updater/Updater.exe`), `release/`는 Nexus에 올라가는 최종물.

### PyInstaller frozen 경로 분기 — 핵심

`backend/config.py`의 `_project_root()`가 모든 경로 해석의 진실 공급원.

- **frozen (EXE 실행 중)**: `sys._MEIPASS` → 정적 자산은 `MEIPASS/web`, Updater는 `MEIPASS/updater/Updater.exe`
- **dev**: 프로젝트 루트 → 정적 자산은 `build/web/`

→ **새 정적 자산/데이터 파일을 추가하면 반드시 `App.spec`의 `datas`에도 등록**해야 frozen에서 보인다.

### App 생명주기 (EXE 기동 시)

1. `backend/main.py` 진입 → `uvicorn.Config(app, ...) + Server(config)` 생성 후 `browser.server`에 보관
   (Windows에서 `os.kill(SIGTERM)`은 lifespan shutdown을 실행하지 않으므로 `server.should_exit = True` 경로만 사용)
2. watchdog + open_browser 데몬 스레드 시작 → `server.run()`
3. 브라우저가 열리면 `App.svelte`가 `crypto.randomUUID()`로 client_id 생성 → sessionStorage 저장 → `/api/register`
4. 5초 간격 `/api/heartbeat`, `pagehide` 시 `navigator.sendBeacon('/api/unregister', Blob(JSON))`
5. `browser.watchdog`이 transition 기반으로 클라이언트 부재 감지 → `SHUTDOWN_GRACE` 경과 시 `server.should_exit = True`

### 동시성 모델

`backend/browser.py`의 `clients: dict[str, float]`는 **uvicorn event-loop와 watchdog 스레드가 동시 접근**한다.

- 모든 read/write는 `_lock` 안에서 수행
- 순회는 `_snapshot()`이 `list(clients.items())`로 락 안에서 스냅샷한 뒤 락 밖에서 처리
- `_ever_registered` 플래그로 "최초 register 이전 STARTUP_GRACE(60s) 대기"와 "register 후 비어있음(SHUTDOWN_GRACE 2s)"을 구분

### Origin 가드 — 보안 경계

`backend/routers/api.py`의 `require_local_origin` 의존성이 router 레벨에 걸려 있다.

- **frozen(EXE)**에서만 활성. dev는 Vite proxy가 다른 origin이므로 자동 패스.
- `Origin` 헤더가 있으면 `ALLOWED_ORIGIN`(`http://127.0.0.1:8765`)과 일치 확인
- 없으면 `sec-fetch-site`가 `same-origin`/`none` 이어야 함
- 외부 웹사이트가 로컬 EXE의 API를 호출하는 공격 표면을 막는다

### 자동 업데이트 — 4단계 흐름

`backend/updater.py` + `updater/updater.py` 협업.

```
① check_latest()    NEXUS_BASE_URL/latest.json GET, 5분 캐시
                    URL prefix·sha256 hex(64자) 검증 → 실패 시 silently update_available=False
② apply_update()    스트리밍 다운로드(tempfile.mkdtemp) → sha256 검증
                    → release dir에 {stem}.new.exe로 staging(os.replace, 다른 볼륨 fallback)
                    → DETACHED Updater.exe Popen(pid, new, current)
                    → 1초 후 server.should_exit = True
③ Updater.exe       부모 pid OpenProcess+GetExitCodeProcess 폴링 (최대 60s)
                    → POST_EXIT_GRACE 3초 추가 대기 (AV/EDR 핸들 해제 여유)
④ rename-to-backup  current_exe → .old (잠긴 파일도 rename 허용)
                    → new_exe   → current_exe (목적지 비어있으므로 성공)
                    → 실패 시 .old를 원위치 복원, 새 EXE Popen 후 자기 자신 exit
```

**중요**: `os.replace(new, old)`는 방금 종료된 EXE의 이미지 섹션 잔존 잠금 + AV 스캔 핸들 때문에 `ERROR_ACCESS_DENIED`가 나기 쉽다. 그래서 **rename-to-backup 전략을 사용**하고 30회 × 0.5초 재시도한다. 직접 `os.replace`로 회귀시키지 말 것.

진행 상태 폴링: `GET /api/update/status` → `{status, progress, total, message, target_version}` (status ∈ `idle | downloading | verifying | staging | restarting | error`).

### 공유 환경 변수 (.env)

frontend ↔ backend 가 공통 의존하는 host/port는 프로젝트 루트 `.env` 한 곳에서 관리.

- `backend/config.py` — dev에서만 `os.environ.setdefault`로 로드 (shell export가 우선)
- `frontend/vite.config.js` — `loadEnv(mode, "..", "APP_")` + `envDir: ".."`
- 모듈 한정 상수(`STARTUP_GRACE`, `HEARTBEAT_TIMEOUT`, `UPDATE_*` 등)는 `.env`에 끌어내지 말고 `config.py`에 유지

### Release 스크립트 — 주의점

`scripts/release.ps1`은 PowerShell 5.1 호환:

- `param()` 블록은 **반드시 첫 실행문**이어야 한다 (앞에 `[Console]::OutputEncoding=` 같은 문장 두면 에러)
- JSON과 `_version.py`는 **BOM 없는 UTF-8**로 써야 함 — `[System.IO.File]::WriteAllText(path, content, (New-Object System.Text.UTF8Encoding $false))` 사용 (`Set-Content -Encoding utf8`은 BOM 붙어 PS5.1 `Invoke-RestMethod` 파싱 실패)
- `Write-Host` 한글이 깨지므로 스크립트 출력은 영어로 유지
- Nexus 업로드는 **EXE 먼저 → latest.json 마지막** (클라가 404 EXE 보지 않도록)

---

## 핵심 설정값 (`backend/config.py`)

| 상수 | 기본값 | 설명 |
|------|--------|------|
| `HOST` | `127.0.0.1` | 바인드 주소 (`APP_HOST`로 dev override) |
| `PORT` | `8765` | 포트 (`APP_PORT`로 dev override) |
| `STARTUP_GRACE` | `60`초 | 최초 register 대기 상한. 그 안에는 비었다고 판정하지 않음 |
| `HEARTBEAT_TIMEOUT` | `5`초 | stale 클라이언트 제거 기준 |
| `SHUTDOWN_GRACE` | `2`초 | 마지막 클라이언트 사라진 후 종료까지 대기 |
| `NEXUS_BASE_URL` | `APP_NEXUS_BASE_URL` env or 내부 기본값 | 업데이트 저장소 |
| `UPDATE_CHECK_CACHE_TTL` | `300`초 | `/api/update/check` 캐시 |
| `UPDATE_CHECK_TIMEOUT` | `5`초 | latest.json GET 타임아웃 |
| `UPDATE_DOWNLOAD_TIMEOUT` | `60`초 | EXE 다운로드 타임아웃 |

---

## 코드 컨벤션

`.claude/rules/code_conventions.md`에 Python 협업 규칙이 정의되어 있다. 핵심:

- **Ruff 강제**: 변경 후 `uv run ruff format . && uv run ruff check --fix .`
- **타입 힌트 100%**, `Any` 지양, `except Exception:` 광범위 묵살 금지
- 매직 넘버/스트링은 `UPPER_SNAKE_CASE` 상수 또는 `Enum`으로 추출
- `print()` 디버깅 지양 — `logging` 사용 (현재 코드는 단순 상태 추적 용도로 `print` 일부 남아있음)
- Google-style docstring, f-string 강제, Early Return 권장
- Pydantic `BaseModel` + `Annotated`로 데이터 계층 구조화
- 한글 주석은 **Why**만, What은 코드로 표현
