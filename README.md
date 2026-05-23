# Svelte + FastAPI EXE

Vite/Svelte로 만든 AI Agent 채팅 UI를 FastAPI가 서빙하고, PyInstaller로 단일 `.exe`로 패키징하는 사내 배포용 데스크톱 앱 템플릿.
Nexus raw repository를 통한 자동 업그레이드 기능 내장.

> **앱 이름 변경**: `App.spec` 파일의 `name='MyAgent'` 부분만 수정하면
> `release.ps1`이 해당 이름으로 EXE를 자동 생성한다.

## 기술 스택

| 역할 | 기술 |
|---|---|
| 프론트엔드 | Svelte 5, Vite |
| 백엔드 | FastAPI, uvicorn |
| 패키징 | PyInstaller (onefile) |
| 패키지 관리 | uv (Python), npm (JS) |
| 업데이트 배포 | Nexus OSS raw repository |

---

## 프로젝트 구조

```
svelte-fastapi-exe/
├── .env                   # 공유 환경 변수 (host/port, Nexus URL) — dev only
├── backend/
│   ├── main.py            # FastAPI 앱, uvicorn 서버, SPA 라우팅
│   ├── config.py          # .env 로더, 경로, 포트, Nexus URL 등 전역 상수
│   ├── browser.py         # clients 레지스트리, watchdog, graceful shutdown
│   ├── updater.py         # 버전 체크, 다운로드, sha256 검증, self-replace 트리거
│   ├── _version.py        # 앱 버전 단일 소스 (release.ps1 이 자동 갱신)
│   └── routers/
│       ├── __init__.py
│       └── api.py         # /api/* 엔드포인트, Origin 가드
├── frontend/
│   ├── src/
│   │   └── App.svelte     # 채팅 UI + 클라이언트 생명주기 + 업데이트 배너·모달
│   └── vite.config.js     # .env 로더, 빌드 출력 → ../build/web, /api 프록시
├── updater/
│   └── updater.py         # self-replace 부트스트랩 (별도 EXE 로 빌드)
├── scripts/
│   ├── release.ps1        # 빌드 + sha256 + Nexus 업로드 자동화
│   └── release-dryrun.ps1 # 로컬 Nexus mock 으로 릴리즈 파이프라인 검증
├── build/                 # 중간 산출물 (gitignored)
│   ├── web/               # Vite SPA 번들    → App EXE 에 임베드
│   ├── updater/           # Updater.exe      → App EXE 에 임베드
│   ├── pyi-app/           # PyInstaller workpath
│   └── pyi-updater/       # PyInstaller workpath
├── release/               # 최종 산출물 (gitignored, Nexus 업로드 대상)
│   ├── {AppName}.exe
│   ├── {AppName}-X.X.X.exe
│   └── latest.json
├── App.spec               # PyInstaller 스펙 — name='...' 으로 EXE 파일명 지정
└── Updater.spec           # Updater.exe PyInstaller 스펙
```

### 빌드 산출물 흐름

```
frontend/src        ─(vite)─►  build/web/         ┐
                                                   ├─(PyInstaller, App.spec)─►  release/{AppName}.exe
updater/updater.py  ─(PyI, Updater.spec)─►  build/updater/Updater.exe  ┘

release/{AppName}.exe ─(sha256 + copy)─► release/{AppName}-X.X.X.exe + release/latest.json
```

`build/`는 EXE 안에 임베드되는 중간물, `release/`는 Nexus에 올라가는 최종물.

### 공유 상수 (.env)

frontend ↔ backend 가 공통으로 의존하는 host/port는 프로젝트 루트의 `.env` 한 곳에서 관리한다.

```env
APP_HOST=127.0.0.1
APP_PORT=8765
# APP_NEXUS_BASE_URL=https://nexus.internal/repository/myapp
```

- `backend/config.py` — dev 모드(`frozen=False`)에서만 `.env`를 로드. EXE 빌드 시에는 무시되고 내장 기본값 사용.
- `frontend/vite.config.js` — Vite의 `loadEnv(mode, "..", "APP_")`로 동일 파일에서 proxy target을 읽는다.
- 모듈/스코프 한정 상수(`STARTUP_GRACE`, `HEARTBEAT_TIMEOUT` 등)는 그대로 `backend/config.py`에 유지.

---

## 앱 아키텍처

### 실행 흐름 (EXE 기동 시)

```
App.exe 실행
  ├─ uvicorn.Server 생성 → app.state 에 보관
  ├─ watchdog 스레드: 클라이언트 heartbeat 감시, 모두 사라지면 서버 종료
  └─ open_browser 스레드: 1초 후 브라우저 자동 오픈

브라우저 → http://127.0.0.1:8765
  ├─ /api/register (client_id UUID 등록)
  ├─ /api/heartbeat (5초 간격, keepalive)
  ├─ /api/update/check (시작 시 1회, Nexus latest.json 조회)
  └─ 탭 닫힐 때 → pagehide 이벤트 → sendBeacon /api/unregister
```

### 자동 업데이트 흐름

```
① 앱 시작 → /api/update/check → Nexus latest.json 비교
② 새 버전 있으면 UI 배너 표시 → 사용자 "지금 업데이트" 클릭
③ /api/update/apply:
     - 새 App.exe 다운로드 (스트리밍, sha256 검증)
     - 번들된 Updater.exe 를 detached 프로세스로 기동
     - uvicorn graceful shutdown (server.should_exit = True)
④ Updater.exe:
     - 기존 App.exe 종료 대기
     - 기존 EXE → .old 로 rename, 새 EXE → 원래 이름으로 rename
     - 새 App.exe 기동 후 자기 자신 종료
```

> **왜 Updater.exe가 필요한가**
> Windows는 실행 중인 EXE 파일을 잠그기 때문에, App.exe가 종료된 이후에 별도 프로세스가 파일을 교체해야 한다.
> Updater.exe는 App.exe 내부에 번들로 포함되어 있으며 Nexus에 별도 배포하지 않는다.

> **왜 rename-to-backup 전략인가**
> `os.replace(new, old)` 는 Windows에서 방금 종료된 EXE의 이미지 섹션이 아직 해제되지 않았거나 AV/EDR이 파일을 스캔하는 동안 `ERROR_ACCESS_DENIED`로 실패할 수 있다.
> `current_exe → .old` rename은 잠긴 파일에도 허용되므로 이 방식으로 우회한다.

### 보안 가드레일

- **Origin 가드**: EXE 환경에서 `http://127.0.0.1:8765` 이외의 origin에서 오는 `/api/*` 요청을 403으로 차단 (외부 웹사이트의 로컬 API 호출 방지)
- **sha256 무결성 검증**: 다운로드 후 latest.json의 sha256과 불일치하면 임시 파일 즉시 삭제, 현재 EXE 보존
- **URL prefix 검증**: latest.json의 url이 `NEXUS_BASE_URL`로 시작하지 않으면 거부
- **latest.json 나중 업로드**: 릴리즈 스크립트가 EXE 업로드 완료 후 latest.json을 업로드 — 클라이언트가 404 EXE를 받는 경쟁 조건 방지
- **graceful shutdown**: `server.should_exit = True` 경로만 사용 — Windows에서 `os.kill(SIGTERM)`은 lifespan 훅을 실행하지 않고 즉시 종료한다

---

## 개발 환경 설정

```powershell
# Python 의존성
uv sync --dev

# JavaScript 의존성
cd frontend; npm install
```

### 개발 서버 실행

터미널 2개를 사용한다.

```powershell
# 터미널 1 — 백엔드
uv run python backend/main.py

# 터미널 2 — 프론트엔드 (HMR)
cd frontend; npm run dev
```

프론트엔드 개발 서버(`http://localhost:5173`)는 `/api` 요청을 `http://127.0.0.1:8765`로 프록시한다.
Origin 가드는 dev 환경(`frozen=False`)에서는 비활성화되므로 별도 설정 없이 동작한다.

---

## 핵심 설정값 (`backend/config.py`)

| 상수 | 기본값 | 설명 |
|---|---|---|
| `HOST` | `127.0.0.1` | 서버 바인드 주소 (`.env`의 `APP_HOST`로 dev 시 override) |
| `PORT` | `8765` | 서버 포트 (`.env`의 `APP_PORT`로 dev 시 override) |
| `STARTUP_GRACE` | `60`초 | 최초 client register 대기 상한 (초과 시 자동 종료) |
| `HEARTBEAT_TIMEOUT` | `5`초 | 이 시간 동안 heartbeat 없으면 stale 클라이언트로 제거 |
| `SHUTDOWN_GRACE` | `2`초 | 마지막 클라이언트 사라진 후 종료까지 대기 |
| `NEXUS_BASE_URL` | `APP_NEXUS_BASE_URL` 환경변수 또는 내부 기본값 | 업데이트 파일 저장소 |
| `UPDATE_CHECK_CACHE_TTL` | `300`초 | 버전 체크 결과 캐시 유효 시간 |

---

## 릴리즈 절차

### 1. 버전 올리기

`pyproject.toml`의 `version`만 수정한다. `_version.py`는 스크립트가 자동 갱신한다.

```toml
[project]
version = "0.2.0"   # ← 여기만 수정
```

### 2. (선택) EXE 파일명 변경

`App.spec`의 `name=` 값만 바꾸면 된다. 스크립트가 자동으로 읽어 사용한다.

```python
name='MyAgent',  # ← 여기만 수정 (예: 'MyTool', 'CorpHelper' 등)
```

### 3. 릴리즈 스크립트 실행

```powershell
# 빌드 + sha256 + latest.json 생성 + Nexus 업로드
pwsh scripts/release.ps1 `
  -Upload `
  -NexusBaseUrl https://nexus.internal/repository/myapp `
  -NexusUser <id> `
  -NexusPass <pw> `
  -Notes "버그 수정 및 업데이트 인프라 추가"
```

스크립트가 수행하는 작업:

1. `pyproject.toml` 버전 → `backend/_version.py` 동기화
2. `npm run build` (Svelte → `build/web/`)
3. `pyinstaller Updater.spec` → `build/updater/Updater.exe`
4. `pyinstaller App.spec` → `release/{AppName}.exe` (web 번들 + Updater.exe 포함)
5. sha256 계산 + `release/latest.json` 생성
6. Nexus에 `{AppName}-{version}.exe` 업로드 후 `latest.json` 업로드 (순서 보장)

### 4. Dry-run (업로드 없이 로컬 검증)

```powershell
pwsh scripts/release-dryrun.ps1
```

로컬 HTTP 서버(기본 19800 포트)로 Nexus를 흉내내고, 업데이트 감지·다운로드·sha256 검증까지 실제 네트워크 없이 테스트할 수 있다.
스크립트 실행 후 안내에 따라 수동 검증 시나리오(정상·sha256 mismatch·네트워크 단절)를 수행한다.

---

## `latest.json` 포맷

Nexus에 EXE와 함께 업로드되는 버전 메타데이터 파일.

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

---

## EXE 패키징 (수동)

릴리즈 스크립트를 쓰지 않고 직접 빌드할 때의 순서.

```powershell
# 1. 프론트엔드 빌드
cd frontend; npm run build; cd ..

# 2. Updater.exe 빌드 (먼저)
uv run pyinstaller --noconfirm --clean `
  --distpath build/updater --workpath build/pyi-updater `
  Updater.spec

# 3. App EXE 빌드 (Updater.exe + web 번들 임베드)
uv run pyinstaller --noconfirm --clean `
  --distpath release --workpath build/pyi-app `
  App.spec

# 결과: release/{AppName}.exe  (AppName = App.spec 의 name= 값)
```

---

## 업데이트 API

| 엔드포인트 | 설명 |
|---|---|
| `GET /api/version` | 현재 버전 반환 `{ "version": "0.1.0" }` |
| `GET /api/update/check` | Nexus latest.json 조회, 5분 캐시. `update_available` 포함 |
| `POST /api/update/apply` | 다운로드·검증·updater 기동·graceful shutdown 트리거 |
| `GET /api/update/status` | 진행 상태 폴링 (`idle` \| `downloading` \| `verifying` \| `staging` \| `restarting` \| `error`) |

`/api/update/check` 응답 예시:

```json
{
  "current": "0.1.0",
  "latest": "0.2.0",
  "update_available": true,
  "notes": "버그 수정",
  "size": 18742912,
  "released_at": "2026-05-23T09:00:00+09:00"
}
```
