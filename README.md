# Svelte + FastAPI EXE

Vite/Svelte로 만든 AI Agent 채팅 UI를 FastAPI가 서빙하고, PyInstaller로 단일 `.exe`로 패키징하는 사내 배포용 데스크톱 앱 템플릿.
다중 대화 세션(localStorage 영속화) · LLM 설정 UI · Nexus raw repository 자동 업그레이드 내장.

> **앱 이름 변경**: `packaging/App.spec` 파일의 `name='MyAgent'` 부분만 수정하면
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
├── .env                   # 전체 환경 변수 레퍼런스 — dev only
├── backend/
│   ├── main.py            # FastAPI 앱, uvicorn 서버, SPA 라우팅
│   ├── _version.py        # 앱 버전 단일 소스 (release.ps1 이 자동 갱신)
│   ├── core/              # 앱 인프라 (LLM 무관)
│   │   ├── config.py      # 모든 환경 변수·경로·상수의 단일 진실 공급원
│   │   ├── browser.py     # presence 클라이언트 추적, watchdog, graceful shutdown
│   │   └── updater.py     # 버전 체크, 다운로드, sha256 검증, self-replace 트리거
│   ├── agent/             # LLM 에이전트 런타임
│   │   ├── config.py      # SYSTEM_PROMPT, temperature, LLM 시드값
│   │   ├── harness.py     # run_turn — 핵심 턴 루프
│   │   ├── models.py      # Pydantic 메시지·이벤트·상태
│   │   ├── stores/        # conversation(히스토리), agent_state(todo 영속)
│   │   ├── registries/    # prompts, skills, tools 카탈로그
│   │   └── providers/     # factory + mock + openai (LLM 프로바이더 패키지)
│   ├── api/               # /api/* 엔드포인트 — 도메인별 분할
│   │   ├── deps.py        # Origin 가드, 싱글톤 store 초기화
│   │   ├── chat.py        # POST /api/chat, /api/conversation CRUD
│   │   ├── settings.py    # GET/POST /api/settings, /providers, /test
│   │   ├── presence.py    # GET /api/presence
│   │   ├── update.py      # GET /api/version, /api/update/*
│   │   └── skills.py      # GET /api/skills, /api/debug/skill-route
│   └── settings/          # LLM 설정 저장소 (models, store, masking)
├── frontend/
│   ├── src/
│   │   ├── App.svelte     # 레이아웃 셸 (Sidebar + TopBar + ChatArea + Composer)
│   │   ├── app.css        # CSS 변수 기반 테마 토큰 (라이트/다크)
│   │   ├── lib/           # 순수 로직 모듈 (api, sse, storage, markdown, state 등)
│   │   └── components/    # UI 컴포넌트 (Sidebar, ChatArea, SettingsModal 등)
│   └── vite.config.js     # .env 로더, 빌드 출력 → ../build/web, /api 프록시
├── updater/
│   └── updater.py         # self-replace 부트스트랩 (별도 EXE 로 빌드)
├── packaging/             # 빌드·릴리즈 관련 파일 일체
│   ├── App.spec           # PyInstaller 스펙 — name='...' 으로 EXE 파일명 지정
│   ├── Updater.spec       # Updater.exe PyInstaller 스펙
│   ├── release.ps1        # 빌드 + sha256 + Nexus 업로드 자동화
│   └── release-dryrun.ps1 # 로컬 Nexus mock 으로 릴리즈 파이프라인 검증
├── build/                 # 중간 산출물 (gitignored)
│   ├── web/               # Vite SPA 번들    → App EXE 에 임베드
│   ├── updater/           # Updater.exe      → App EXE 에 임베드
│   ├── pyi-app/           # PyInstaller workpath
│   └── pyi-updater/       # PyInstaller workpath
└── release/               # 최종 산출물 (gitignored, Nexus 업로드 대상)
    ├── {AppName}.exe
    ├── {AppName}-X.X.X.exe
    └── latest.json
```

### 빌드 산출물 흐름

```
frontend/src        ─(vite)─────────────────────────────►  build/web/          ┐
updater/updater.py  ─(PyI, Updater.spec)─►  build/updater/Updater.exe          ┤
                                                                                ├─(PyI, App.spec)─►  release/{AppName}.exe
                                                                                ┘
release/{AppName}.exe ─(sha256 + copy)─► release/{AppName}-X.X.X.exe + release/latest.json
```

`build/`는 EXE 안에 임베드되는 중간물, `release/`는 Nexus에 올라가는 최종물.

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

## 앱 아키텍처

### 실행 흐름 (EXE 기동 시)

```
App.exe 실행
  ├─ uvicorn.Server 생성 → browser.server 에 보관
  ├─ watchdog 스레드: presence 연결 감시, 모두 사라지면 서버 종료
  └─ open_browser 스레드: 1초 후 브라우저 자동 오픈

브라우저 → http://127.0.0.1:8765
  ├─ initApp(): localStorage 에서 세션 복원 → 활성 세션으로 /api/presence SSE 오픈
  ├─ /api/conversation/restore: localStorage 히스토리 → 백엔드 LLM context 주입
  ├─ /api/update/check (시작 시 1회, Nexus latest.json 조회)
  └─ 탭 닫힐 때 → EventSource 종료 → 서버 generator finally 가 disconnect 처리
```

### 세션 관리

- **localStorage가 진실의 원천**: 세션 목록·메시지·테마를 브라우저 localStorage에 저장
- **세션 id = 백엔드 client_id**: `crypto.randomUUID()`로 생성, presence 채널·conversation store 키로 공유
- **hydrate 방향**: 앱 시작·세션 전환 시 프론트 → 백엔드로 히스토리 주입 (`POST /api/conversation/restore`)

### LLM 설정

- UI 기어 아이콘 → 설정 모달에서 프로바이더·모델·API키·Base URL 변경 후 저장
- `%APPDATA%\{APP_NAME}\settings.json` (frozen) 또는 `backend/settings/settings.json` (dev) 에 영속화
- temperature, max_tokens, system_prompt는 `backend/agent/config.py` / 환경 변수로 제어 (설정 모달 미노출)
- 설정 변경 즉시 반영 (서버 재시작 불필요 — 매 `/api/chat` 요청마다 최신 설정 로드)

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

> **왜 rename-to-backup 전략인가**
> `os.replace(new, current)` 는 방금 종료된 EXE의 잔존 잠금 + AV/EDR 스캔 때문에 `ERROR_ACCESS_DENIED` 로 실패할 수 있다.
> `current_exe → .old` rename은 잠긴 파일에도 허용되므로 이 방식으로 우회한다.

### 보안 가드레일

- **Origin 가드**: EXE 환경에서 `http://127.0.0.1:8765` 이외의 origin에서 오는 `/api/*` 요청을 403으로 차단
- **sha256 무결성 검증**: 다운로드 후 latest.json의 sha256과 불일치하면 임시 파일 삭제, 현재 EXE 보존
- **API 키 보안**: settings.json에만 저장, 응답 시 항상 마스킹, localStorage에 저장 안 함
- **latest.json 나중 업로드**: EXE 업로드 완료 후 latest.json 업로드 — 404 EXE 경쟁 조건 방지

---

## 릴리즈 절차

### 1. 버전 올리기

`pyproject.toml`의 `version`만 수정한다. `_version.py`는 스크립트가 자동 갱신한다.

```toml
[project]
version = "0.2.0"   # ← 여기만 수정
```

### 2. (선택) EXE 파일명 변경

`packaging/App.spec`의 `name=` 값만 바꾸면 된다.

```python
name='MyAgent',  # ← 여기만 수정 (예: 'MyTool', 'CorpHelper' 등)
```

### 3. 릴리즈 스크립트 실행

```powershell
# 빌드 + sha256 + latest.json 생성 + Nexus 업로드
pwsh packaging/release.ps1 `
  -Upload `
  -NexusBaseUrl https://nexus.internal/repository/myapp `
  -NexusUser <id> `
  -NexusPass <pw> `
  -Notes "변경사항 요약"
```

스크립트가 수행하는 작업:

1. `pyproject.toml` 버전 → `backend/_version.py` 동기화
2. `npm run build` (Svelte → `build/web/`)
3. `pyinstaller packaging/Updater.spec` → `build/updater/Updater.exe`
4. `pyinstaller packaging/App.spec` → `release/{AppName}.exe` (web 번들 + Updater.exe 포함)
5. sha256 계산 + `release/latest.json` 생성
6. Nexus에 `{AppName}-{version}.exe` 업로드 후 `latest.json` 업로드 (순서 보장)

### 4. Dry-run (업로드 없이 로컬 검증)

```powershell
pwsh packaging/release-dryrun.ps1
```

로컬 HTTP 서버(기본 19800 포트)로 Nexus를 흉내내고, 업데이트 감지·다운로드·sha256 검증까지 실제 네트워크 없이 테스트할 수 있다.

### 5. 수동 패키징 (스크립트 우회 시)

```powershell
cd frontend; npm run build; cd ..
uv run pyinstaller --noconfirm --clean --distpath build/updater --workpath build/pyi-updater packaging/Updater.spec
uv run pyinstaller --noconfirm --clean --distpath release --workpath build/pyi-app packaging/App.spec
```

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
