# ① 프로젝트 전체 흐름

> **대상 독자**: 이 프로젝트를 처음 접하는 개발자·이해관계자
> **이 문서의 목표**: "무엇을 만드는 프로젝트이고, 어떻게 만들어져서, 어떤 경로로 사용자에게 도달하는가"를 큰 그림 → 세부 순서로 이해한다.

---

## 1. 한 문장 정의

**"웹 기술(Svelte)로 만든 AI Agent 채팅 앱을, 별도 서버·설치 과정 없이 단일 `.exe` 파일 하나로 사내 PC에 배포하는 프로젝트"**

| 구성 요소 | 역할 |
|---|---|
| **Svelte SPA** | 사용자가 보는 채팅 UI (정적 빌드 산출물) |
| **FastAPI** | 정적 파일 서빙 + REST/SSE API + LLM 에이전트 하니스 |
| **PyInstaller** | 위 둘 + 에이전트 정의 파일을 묶어 단일 EXE로 패키징 |
| **Nexus (사내 저장소)** | EXE와 버전 메타데이터(`latest.json`) 배포 |
| **Updater.exe** | 실행 중인 앱을 새 버전으로 자가 교체 (자동 업데이트) |

핵심 컨셉: **브라우저가 화면이고, EXE가 서버다.** 사용자는 EXE를 더블클릭하기만 하면
로컬에서 백엔드가 켜지고 기본 브라우저에 채팅 화면이 열린다.

---

## 2. 왜 이런 구조인가 — 설계 목표

| 목표 | 채택한 해법 |
|---|---|
| **설치 과정 없는 배포** — IT 지원 없이 파일 복사만으로 실행 | PyInstaller onefile 단일 EXE (Python 런타임·웹 자산 전부 내장) |
| **보안 경계** — 외부 네트워크에 절대 노출되지 않는 로컬 앱 | `127.0.0.1` 루프백 고정 바인딩 + Origin 가드 (코드 고정, env로도 변경 불가) |
| **포트 충돌 없음** — 사용자 PC 환경을 가정하지 않음 | APP_NAME 해시로 고정 포트 배정 (47100–48999) — 재기동 후에도 localStorage 대화 기록 보존. 충돌 시 +1..+4 폴백 체인 |
| **수동 재배포 제거** — 버전 업그레이드 자동화 | 앱 내장 업데이트 체크 + sha256 검증 + Updater.exe 자가 교체 |
| **코드 수정 없는 에이전트 확장** — 도메인 로직과 앱 코드 분리 | `PROMPTS/` `SKILLS/` `AGENTS/` 마크다운 파일 + `.env` 한 줄로 동작 정의 |

이 프로젝트의 에이전트는 **"미리 등록된 Python API 도구를 계획(plan)에 따라 실행하는 플랫폼"**이다.
코드를 작성·편집하는 AI 코딩 어시스턴트가 아니라, 사내 도메인 작업(데이터 조회·분석·보고)을
대화로 수행하는 업무 에이전트를 지향한다.

---

## 3. 큰 그림 — 개발부터 사용자까지 5단계

```
① 개발      frontend/ (Svelte SPA)  +  backend/ (FastAPI + Agent)  +  PROMPTS·SKILLS·AGENTS (.md)
               │
② 빌드      pwsh packaging/release.ps1   ← 한 줄로 전체 파이프라인 실행
               ├─ npm run build   →  build/web/              (정적 웹 자산)
               ├─ PyInstaller     →  build/updater/Updater.exe
               └─ PyInstaller     →  release/MyAgent.exe     (web·updater·md·.env 전부 내장)
               │
③ 배포      release/MyAgent.exe  +  release/latest.json  →  Nexus 업로드
               │
④ 실행      사용자가 EXE 더블클릭  →  FastAPI 기동(고정 포트)  →  기본 브라우저 자동 오픈
               │
⑤ 업데이트   앱이 Nexus의 latest.json 확인  →  새 EXE 다운로드·검증  →  Updater.exe가 자가 교체
```

- **`build/`** = 중간 산출물 (EXE 안에 들어갈 재료, 업로드하지 않음)
- **`release/`** = 최종 산출물 (Nexus에 업로드되는 것)

---

## 4. 실행 시 모습 — 사용자 PC 한 대 안에서 일어나는 일

```
사용자 PC  (외부 네트워크 노출 없음)
┌────────────────────────────────────────────────────┐
│  MyAgent.exe  (PyInstaller onefile)                │
│  ┌──────────────────────────────────────────────┐  │
│  │  FastAPI + uvicorn   127.0.0.1:<고정 포트>     │  │
│  │   ├─ /              → 내장 web/ (Svelte SPA)  │  │
│  │   ├─ /api/*         → REST + SSE 스트리밍     │  │
│  │   ├─ /result/*      → 에이전트 산출물 파일     │  │
│  │   └─ /workspace/*   → 도구가 생성한 파일       │  │
│  └──────────────────────────────────────────────┘  │
│          ↑ HTTP (루프백 전용)                        │
│  기본 브라우저 (EXE가 자동으로 오픈)                   │
└────────────────────────────────────────────────────┘
```

생명주기는 **브라우저 탭과 연동**된다:

1. EXE 기동 → APP_NAME 해시 기반 고정 포트 바인딩 → uvicorn 시작 → 브라우저 자동 오픈
2. 브라우저가 `/api/presence` SSE 연결을 유지 = **생존 신호**
3. 탭을 닫으면 연결이 끊기고, 짧은 유예(grace) 후 watchdog이 **서버를 스스로 종료**

→ 사용자 입장에선 "더블클릭으로 켜고, 탭 닫으면 꺼지는" 일반 데스크탑 앱처럼 동작한다.
(상세 메커니즘은 [③ Backend 동작 흐름](03-backend-flow.md) 참조)

데이터 저장 위치도 일반 데스크탑 앱 관례를 따른다:

| 데이터 | dev | frozen EXE |
|---|---|---|
| 대화 세션·메시지 | 브라우저 localStorage | 브라우저 localStorage |
| LLM 설정 (`settings.json`) | `backend/settings/` | `%APPDATA%\{APP_NAME}\` |
| 에이전트 산출물 (`result/`) | 프로젝트 루트 | `%APPDATA%\{APP_NAME}\result\` |
| 도구 생성 파일 (`workspace/`) | 프로젝트 루트 | `%APPDATA%\{APP_NAME}\workspace\` |

---

## 5. 기술 스택

| 영역 | 기술 | 비고 |
|---|---|---|
| Frontend | **Svelte 5 (runes)** + Vite | SPA, 빌드 결과는 순수 정적 파일 |
| 차트 | **ECharts** | 인터랙티브 차트 (brush 필터·레전드 편집) |
| Backend | **FastAPI** + uvicorn | REST + SSE(Server-Sent Events) 스트리밍 |
| LLM 연동 | OpenAI 호환 API (DTGPT 포함) + Mock | provider 추상화로 핫스왑 |
| 데이터 | **polars** + parquet | 에이전트 산출물의 표준 데이터 포맷 |
| 패키징 | **PyInstaller** (onefile) | Windows 단일 EXE |
| 배포 | **Nexus** raw repository | 저장소 중립적 설계 (`APP_REPO_*` 변수) |
| 패키지 관리 | Python `uv` / JS `npm` | |
| 품질 | `ruff` (포맷+린트) / `pytest` (asyncio auto) | |

---

## 6. 아키텍처 — 3개 층의 분리

```
┌──────────────────────────────────────────────────────────┐
│ ① 화면 층  frontend/ (Svelte 5)                           │
│    - 대화 UI·세션 관리·아티팩트 패널                          │
│    - 진실의 원천: 브라우저 localStorage                      │
└──────────────┬───────────────────────────────────────────┘
               │ REST + SSE  (/api/*)
┌──────────────┴───────────────────────────────────────────┐
│ ② 서버 층  backend/ (FastAPI)                             │
│    - 정적 서빙·presence 생명주기·설정·업데이트·산출물 API      │
└──────────────┬───────────────────────────────────────────┘
               │ run_turn() 호출
┌──────────────┴───────────────────────────────────────────┐
│ ③ 에이전트 층  backend/agent/ (하니스)                      │
│    - LLM provider ↔ 도구 실행 루프                          │
│    - 동작 정의는 코드 밖: PROMPTS/ · SKILLS/ · AGENTS/ (.md) │
└──────────────────────────────────────────────────────────┘
```

특징적인 데이터 흐름 한 가지: **대화 히스토리의 진실의 원천은 프론트(localStorage)다.**
앱 시작·세션 전환 시 프론트가 보관한 메시지를 `POST /api/conversation/restore` 로 백엔드에
주입(hydrate)해 LLM 컨텍스트를 복원한다. 백엔드는 대화를 영구 저장하지 않는다
(단, 산출물 파일과 에이전트 상태는 디스크에 영속).

---

## 7. 디렉터리 구조

```
svelte-fastapi-exe/
├─ frontend/            # ① 화면 층 — Svelte 5 + Vite SPA
│   └─ src/
│       ├─ components/  #    UI 컴포넌트 26개 (ChatArea·ArtifactPanel·SettingsModal …)
│       └─ lib/         #    전역 상태($state)·액션 함수·API 래퍼·SSE 파서
│
├─ backend/             # ② 서버 층 + ③ 에이전트 층
│   ├─ main.py          #    엔트리포인트 (FastAPI 앱 조립·기동)
│   ├─ core/            #    경로/포트/생명주기/업데이트/산출물 저장
│   ├─ api/             #    HTTP 엔드포인트 (도메인별 라우터 7개)
│   ├─ agent/           #    LLM 에이전트 하니스 (harness·providers·registries·tools …)
│   ├─ settings/        #    LLM 설정 저장소 (settings.json)
│   ├─ scripts/         #    프로젝트 전용 Python 유틸 패키지 (에이전트에 노출)
│   └─ tests/           #    pytest (하니스·가드·산출물 파이프라인 검증)
│
├─ PROMPTS/             # 에이전트 기반 system prompt (.md) — 항상 적용
├─ SKILLS/              # 상황별 작업 지침 (.md) — 키워드 트리거로 주입
├─ AGENTS/              # 서브 에이전트 정의 (.md) — 위임 대상 카탈로그
│
├─ extensions/          # 메인 앱과 격리된 독립 확장 도구 (폴더 단위 추가·삭제)
│   └─ evaluator/       #    예시: parquet 큐레이션 BI 도구 (Svelte SPA + FastAPI 라우터)
│
├─ packaging/           # App.spec · Updater.spec · release.ps1 (빌드 파이프라인)
├─ updater/             # Updater.exe 소스 (자가 교체 로직)
├─ docs/                # 개발자 가이드 (이 폴더 포함)
├─ .env                 # 빌드·런타임 설정의 단일 진실 공급원
│
├─ build/               # (생성) 중간 산출물 — web/, updater/
├─ release/             # (생성) 배포 산출물 — {AppName}.exe, latest.json
├─ result/              # (생성) 에이전트 산출물 (dev 실행 시)
└─ workspace/           # (생성) 도구 생성 파일 (dev 실행 시)
```

**확장 포인트는 전부 코드 밖에 있다**: 에이전트의 행동을 바꾸려면 `PROMPTS/`·`SKILLS/`·`AGENTS/`
마크다운을 수정하고, 새 도구는 `backend/agent/tools/`에 파일 하나를 추가하면 자동 등록된다.
독립적인 시각 도구가 필요하면 `extensions/`에 폴더 하나를 더하면 된다 (호스트 코드 무수정 — 13절).

---

## 8. 개발 모드 vs 패키징 모드

같은 코드가 두 가지 모드로 동작한다. 분기 기준은 `sys.frozen` (PyInstaller 여부) 하나다.

| | dev (개발) | frozen (배포 EXE) |
|---|---|---|
| 화면 | Vite dev server (`localhost:5173`, HMR) | EXE에 내장된 `web/` 정적 파일 |
| 백엔드 포트 | `.env`의 `APP_DEV_PORT` 고정 (기본 8765) | `APP_PORT` 또는 APP_NAME 해시 기반 고정 포트 (`core.server_socket`) |
| API 연결 | Vite가 `/api`를 백엔드로 프록시 | 같은 origin이라 프록시 불필요 |
| PROMPTS/SKILLS 수정 | **핫리로드** (다음 턴부터 반영) | 빌드 시점에 박제 (재빌드 필요) |
| 종료 방식 | Ctrl+C | 탭 닫기 → watchdog 자동 종료 |

```powershell
# 개발 서버 실행
uv run python backend/main.py      # 터미널 1 — 백엔드
cd frontend; npm run dev           # 터미널 2 — http://localhost:5173
```

---

## 9. 빌드 & 릴리즈 파이프라인 (`packaging/release.ps1`)

`pwsh packaging/release.ps1` 한 줄이 아래 6단계를 순서대로 수행한다.

```
[사전 검사]  git working tree clean 확인 (-Force 로 우회 가능) · .env 로드
     │
① 버전 확인          pyproject.toml version 읽기 (App.spec이 빌드 시 _version.py 생성)
② Frontend 빌드    npm run build → build/web/
③ Updater 빌드     PyInstaller(Updater.spec) → build/updater/Updater.exe
④ App EXE 빌드     PyInstaller(App.spec) → release/{AppName}.exe
⑤ 메타데이터 생성   EXE sha256·크기 계산 → release/latest.json
⑥ 업로드 (선택)     -Upload 플래그 시 Nexus 에 EXE 먼저 → latest.json 마지막 순서로 업로드
```

**`App.spec`이 EXE에 내장하는 것** (`sys._MEIPASS`로 임베드):

| 내장 항목 | 이유 |
|---|---|
| `build/web/` → `web/` | 프론트 정적 자산 |
| `build/updater/Updater.exe` → `updater/` | 자가 교체용 헬퍼 |
| `PROMPTS/` `SKILLS/` `AGENTS/` | 에이전트 동작 정의 (파일 추가만으로 다음 빌드 반영) |
| `.env` | 빌드 시점 설정 박제 |
| `backend/scripts/` 전체 서브모듈 | `collect_submodules('scripts')` 자동 수집 |
| `APP_ALLOWED_LIBRARIES`의 각 패키지 | `.env`를 읽어 `collect_all()` — **env 한 줄 = 번들 자동 포함** |
| `extensions/<tool>/backend` + `frontend/dist` | 확장 도구 — 폴더 글롭으로 **있을 때만** 선별 번들 (런타임 필요분만, src·node_modules·tests 제외) |

업로드 순서가 "EXE 먼저, latest.json 마지막"인 이유: 메타데이터가 먼저 올라가면
클라이언트가 아직 존재하지 않는 EXE(404)를 다운로드하려고 시도할 수 있기 때문.

> 네트워크 없이 업데이트 파이프라인 전체를 검증하는 `release-dryrun.ps1`도 제공된다.

---

## 10. 자동 업데이트 구조

배포 후 재설치 없이 새 버전이 도달하는 메커니즘. **다운로드 무결성(sha256)과
실행 파일 잠금 문제**를 모두 처리한다.

```
① 확인     앱이 {Nexus}/latest.json GET (5분 캐시)
            └ URL prefix·sha256 형식 검증 실패 시 조용히 "업데이트 없음" 처리
② 적용     새 EXE 스트리밍 다운로드 → sha256 검증 → {이름}.new.exe 로 스테이징
            └ Updater.exe 를 분리(DETACHED) 프로세스로 실행 후 1초 뒤 서버 자진 종료
③ 대기     Updater.exe 가 부모 프로세스 종료를 폴링 (최대 60초 + 3초 추가 유예)
④ 교체     rename-to-backup 전략:
            현재.exe → .old (rename은 잠긴 파일도 허용)
            → new.exe → 현재.exe → 새 버전 재기동
            → 실패 시 .old 복원 후 기존 버전 재기동 (롤백)
```

`os.replace` 직접 덮어쓰기가 아닌 **rename-to-backup**인 이유: 방금 종료된 EXE의 잔존
파일 잠금 + 백신 스캔 때문에 직접 교체는 `ACCESS_DENIED`가 발생한다. rename은 잠긴
파일에도 허용되므로 30회 × 0.5초 재시도로 안전하게 교체한다.

사용자 화면에는 업데이트 배너 → 진행률 모달(다운로드/검증/재시작)로 표시된다
(→ [② 구현된 UX/UI](02-ux-ui.md)).

---

## 11. 환경 변수 — `.env` 단일 진실 공급원

`.env` 파일 하나가 **dev 런타임·EXE 빌드·릴리즈 스크립트** 세 곳에서 공통으로 읽힌다.

```
.env ──┬─ backend (load_dotenv)        : 런타임 상수
       ├─ frontend (vite.config.js)    : dev 프록시 타겟 (APP_DEV_PORT)
       ├─ packaging/App.spec           : EXE 이름·번들 라이브러리 결정
       └─ packaging/release.ps1        : 앱 이름·저장소 자격증명
```

frozen EXE는 빌드 시 박제된 `.env`를 `override=False`로 읽으므로, **OS 환경 변수가
있으면 그쪽이 우선**한다 — 런타임 임시 오버라이드는 가능하지만 근본 변경은 재빌드가 필요하다.
값 뒤의 `# 인라인 주석`은 파서가 자동 제거한다.

### 주요 환경 변수 (기능 그룹별)

**앱 정체성·네트워크**

| 변수 | 기본값 | 의미 |
|---|---|---|
| `APP_NAME` | `MyAgent` | EXE 파일명, `%APPDATA%` 하위 폴더명, settings.json 경로. **앱 이름 변경은 이 값 하나만 바꾸면 끝** |
| `APP_PORT` | (APP_NAME 해시) | **frozen 전용** 고정 포트. 기본값 `47100 + sha256(APP_NAME) % 1900`. `0`이면 동적 할당. 충돌 시 +1..+4 폴백 체인 — `core.server_socket` |
| `APP_DEV_PORT` | `8765` | dev 전용 백엔드 포트 (Vite 프록시 타겟과 공유). frozen은 `APP_PORT` 또는 APP_NAME 해시 기반 고정 포트를 쓴다 |

**생명주기 (presence/watchdog)**

| 변수 | 기본값 | 의미 |
|---|---|---|
| `APP_STARTUP_GRACE` | `60` | 첫 브라우저 연결까지 기다리는 상한 (초) |
| `APP_SHUTDOWN_GRACE` | `2` | 마지막 클라이언트가 사라진 후 서버 종료까지 대기 (초) |
| `APP_PRESENCE_RECONNECT_GRACE` | `2` | F5·네트워크 블립 시 재연결 허용 유예 (초) |
| `APP_PRESENCE_KEEPALIVE_INTERVAL` | `30` | SSE ping 주기 — 중간 프록시 idle timeout 방지 (초) |

**LLM·에이전트 한도**

| 변수 | 기본값 | 의미 |
|---|---|---|
| `APP_LLM_PROVIDER` | `mock` | 최초 기동 시 settings.json 시드값 (`mock` \| `dtgpt` \| `openai_compatible`) |
| `APP_DTGPT_BASE_URL` | — | DTGPT 엔드포인트 (UI 비노출, 환경 변수로 고정 주입) |
| `APP_LLM_TEMPERATURE` / `APP_LLM_MAX_TOKENS` | `0.7` / 무제한 | 생성 파라미터 (UI 비노출) |
| `APP_MAX_AGENT_ITERATIONS` | `12` | 한 턴당 provider→도구 반복 상한 |
| `APP_MAX_AGENT_CALLS_PER_TURN` | `20` | 오케스트레이터+서브 에이전트 합산 LLM 호출 예산 |
| `APP_MAX_PARALLEL_SUBAGENTS` | `3` | 병렬 서브 에이전트 동시 실행 상한 |
| `APP_TOOL_DEFAULT_TIMEOUT` | `30` | 도구 1회 실행 타임아웃 (초) |
| `APP_MAX_HISTORY_MESSAGES` | `40` | 클라이언트당 보관하는 대화 히스토리 상한 |
| `APP_ALLOWED_LIBRARIES` | `scripts,polars` | 에이전트 런타임에 노출할 Python 패키지 CSV — **EXE 빌드 시 자동 번들링** |

**업데이트·배포 저장소**

| 변수 | 기본값 | 의미 |
|---|---|---|
| `APP_REPO_BASE_URL` | (내부 Nexus) | 업데이트 저장소 URL (저장소 중립적 변수명) |
| `APP_REPO_USER` / `APP_REPO_PASSWORD` | — | release.ps1 업로드 자격증명 |
| `APP_UPDATE_CHECK_CACHE_TTL` | `300` | latest.json 확인 캐시 (초) |

> 전체 목록과 정확한 로딩 위치: `backend/core/config.py`, `backend/agent/config.py`

---

## 12. PROMPTS / SKILLS / AGENTS — 코드 수정 없는 에이전트 확장

이 프로젝트의 가장 중요한 설계: **에이전트의 "행동"은 Python 코드가 아니라 마크다운
파일로 정의된다.** 도메인 전문가가 코드를 모르더라도 파일 추가·수정만으로 에이전트를
확장할 수 있고, 빌드 시 EXE에 자동 번들링된다.

### 한눈에 보는 3계층

| 디렉터리 | 비유 | 적용 시점 | 무엇을 정의하나 |
|---|---|---|---|
| `PROMPTS/` | **헌법** | 모든 턴에 항상 | 에이전트의 정체성·응답 스타일·안전 규칙·라우팅 원칙 |
| `SKILLS/` | **업무 매뉴얼** | 트리거 키워드 매칭 시 | 특정 작업의 절차·필수 입력·금지 사항 |
| `AGENTS/` | **팀원 프로필** | 오케스트레이터가 위임할 때 | 서브 에이전트의 페르소나·전담 스킬·도구 권한 |

### PROMPTS — 기반 system prompt

Front Matter 없이 순수 마크다운. 매 턴 아래 순서로 합성된다.

```
base.md          ← 핵심 페르소나·응답 스타일 (항상)
safety.md        ← 보안·안전 지침 (항상)
orchestrator.md  ← 라우팅 규칙 Case 0~5 (AGENTS/ 가 1개 이상 있을 때만)
domain.md        ← 도메인 용어 사전 (존재할 때만, 선택)
tools_guide.md   ← 도구 사용 지침
```

그 뒤에 하니스가 활성 SKILL 본문, 현재 To-do, 서브 에이전트 카탈로그, 세션 산출물
목록(Session Artifacts)을 이어 붙여 최종 system prompt가 완성된다.

### SKILLS — 키워드로 발동하는 작업 지침

YAML Front Matter + 본문. 사용자 메시지에 `trigger` 키워드가 포함되면 본문이
system prompt에 주입된다 (최대 3개 동시).

```markdown
---
name: data_summary                  # 식별자 (슬래시 커맨드 /data_summary 로 강제 활성화 가능)
description: 데이터 요약 통계 생성     # UI 자동완성에 표시
trigger: ["데이터 요약", "요약 통계"]  # 부분 문자열 매칭 (대소문자 무관)
priority: 5                         # 동시 매칭 시 우선순위
requires_tools: ["exec_code"]       # 사용하는 도구 힌트 (미등록 도구 있으면 감점)
api_refs:                           # 노출할 Python 라이브러리 함수 (선택)
  - scripts.stats_df.describe_frame
---
## 절차
1. `add_todo` 로 단계를 등록한다.
2. ...
```

### AGENTS — 위임 가능한 서브 에이전트

오케스트레이터(메인 에이전트)가 복잡한 작업을 나눠줄 수 있는 **전문가 카탈로그**.

```markdown
---
name: analyst_agent                 # call_sub_agent(agent_name=...) 식별자
description: 데이터 분석 전담         # 오케스트레이터가 위임 판단에 읽는 한 줄
skills: ["data_summary"]            # 이 스킬 트리거 → 자동으로 이 에이전트에 위임 (Case 3)
tools: ["exec_code", "add_todo"]    # 도구 화이트리스트 (빈 리스트 = 전체 노출)
priority: 5
---
당신은 데이터 분석 전문 서브 에이전트입니다. ...페르소나...
```

- 서브 에이전트는 **격리된 컨텍스트**(별도 메시지·별도 상태)에서 실행되고, 완료 시
  요약만 오케스트레이터에게 반환한다 → 메인 컨텍스트 오염 방지
- 서브 에이전트는 다시 위임할 수 없다 (무한 재귀 차단, 4중 방어선)
- 독립 작업 여러 개는 `call_sub_agents_parallel`로 **동시 실행** 가능 (기본 3개 상한)

### 로딩·핫리로드 정책

| 디렉터리 | 로딩 시점 | dev | frozen |
|---|---|---|---|
| `PROMPTS/` | 매 턴 읽기 | mtime 변경 시 핫리로드 | 1회 캐시 |
| `SKILLS/` 메타 / 본문 | 부팅 1회 / 첫 매칭 시 lazy | 본문 mtime 재검사 | 1회 캐시 |
| `AGENTS/` 메타 / 본문 | 부팅 1회 / 위임 시 lazy | 본문 mtime 재검사 | 1회 캐시 |

→ dev에서는 **서버 재시작 없이** 마크다운 수정이 다음 턴부터 반영된다.

### 현재 들어있는 파일은 Mock이다

지금의 `SKILLS/`(time_check·data_summary·report_writer)·`AGENTS/`(analyst·writer)·
`backend/scripts/`는 실제 LLM 없이 하니스와 UI를 검증하기 위한 **Mock 시나리오 전용**이다.
운영 투입 시 실제 도메인의 SKILL/AGENT로 교체하거나 삭제한다.

---

## 13. 확장 시스템 (Extensions) — 폴더 단위로 더하고 빼는 독립 도구

`PROMPTS/SKILLS/AGENTS`가 **에이전트의 행동**을 코드 밖에서 정의하는 확장점이라면,
`extensions/`는 **채팅 UI에 담기 어려운 독립 도구**(시각적·상태 보존·사람 판단 중심)를
메인 앱과 완전히 격리해 붙이는 확장점이다. **폴더 하나가 곧 하나의 도구다.**

### 왜 분리하나

채팅 에이전트는 대화·프로그래밍 작업에 강하지만, 어떤 작업은 **풍부하고 상태를 가진
시각적 인터페이스**가 필요하다 (예: 사람이 후보 데이터를 눈으로 비교·선별하는 큐레이션).
이런 도구를 메인 앱 코드에 박아 넣으면 결합도가 올라간다. 그래서 호스트는 개별 도구를
모른 채 **컨벤션**만 따르고, 도구는 폴더 단위로 자급(self-contained)한다.

### 컨벤션 — 호스트가 아는 것은 이것뿐

| 컨벤션 경로 | 역할 | 마운트 |
|---|---|---|
| `extensions/<tool>/backend/router.py`의 `get_router()` | FastAPI 라우터 팩토리 | `/api/ext/<tool>` |
| `extensions/<tool>/frontend/dist` | 빌드된 Svelte SPA | `/ext/<tool>` |

둘 중 **있는 것만** 마운트된다 (라우터만·SPA만 있어도 동작). 로더
(`backend/core/extensions_loader.py`)가 부팅 시 `extensions/*`를 스캔해 자동 발견·마운트한다.

### 격리 보장 — 폴더를 통째로 지워도 안전

| 보장 | 근거 |
|---|---|
| 폴더 하나를 지워도 메인 앱 무영향 | 로더가 빈손이면 no-op, App.spec 글롭이 빈 리스트 |
| 새 도구 추가에 호스트 코드 수정 불필요 | 로더가 컨벤션으로 자동 발견 |
| 한 확장의 실패가 부팅을 막지 않음 | 확장별 try/except 격리 (경고 후 다음 확장) |

> 확장 모듈은 파일 경로로 적재되므로(frozen EXE 대응) **호스트가 이미 번들한 절대 import만**
> 쓴다 (`core.*`·`api.*`·polars·fastapi). 빌드 시 App.spec이 `backend`·`frontend/dist`를
> **있을 때만** 선별 번들한다 (9절).

### 진입 규약 — `open_curation` 핸드오프

에이전트가 후보 데이터를 만든 뒤 사람을 확장 도구로 넘기는 표준 경로:

```
① 에이전트  후보 parquet 산출 → open_curation(tool, sources, mapping, mark) 호출
② 호스트    번들 스펙(<tool>.bundle.json) 작성 + "큐레이션 도구 열기" 마크다운 카드를
            아티팩트 패널에 표시 (전용 컴포넌트 없이 기존 markdown 칩 재사용)
③ 사용자    카드 링크 클릭 → 새 탭에서 /ext/<tool>/?bundle=... 열림
④ 확장 도구  번들의 parquet 들을 로드 → 사람이 검토·선별·편집
⑤ 환류      도구가 결과를 내보내면 메인 앱 탭에 알림 → 데이터 칩 + 결정 요약으로 인폼
```

`open_curation`은 **evaluator에 특정되지 않는다** — `tool` 인자로 임의 확장을 가리키고
`mapping`도 해석 없이 번들에 그대로 실어 보낸다(확장이 해석). 확장 진입 규약을 한 곳에 모은
제네릭 호스트 훅이다.

### 예시 확장 — evaluator (parquet 큐레이션 BI)

AI가 만든 순위 후보 parquet을 **사람이 Tableau 풍 BI로 검토·선별·재정렬**해 최종 리포트용
데이터로 만드는 도구. 차트 7종(메인 앱 `display_chart`와 동일) · 컬럼 매핑 · 리스트 검색/필터 ·
드래그&드롭 순서변경 · 병합 보기 · 내보내기 환류를 갖춘다. **AI 생성 → 사람 큐레이션 → 결과 환류**의
닫힌 루프가 핵심 가치다 (사용자 화면은 [② UX/UI](02-ux-ui.md), 백엔드는 [③ Backend](03-backend-flow.md) 참조).

---

## 14. 정리 — 이 프로젝트를 한 장으로

```
만드는 것   : 로컬 단일 EXE로 배포되는 사내 AI Agent 채팅 앱
화면        : Svelte 5 SPA  (localStorage 세션, SSE 실시간 스트리밍)
서버        : FastAPI       (정적 서빙 + API + presence 생명주기 + 자동 업데이트)
에이전트     : 하니스 루프    (LLM provider ↔ 등록된 도구 실행, plan 기반)
확장        : PROMPTS/SKILLS/AGENTS 마크다운 + @register_tool + .env 한 줄
확장 도구    : extensions/ 폴더 단위 독립 도구 (격리·open_curation 핸드오프)
빌드        : release.ps1 → PyInstaller onefile EXE + latest.json
배포        : Nexus 업로드 → 앱이 스스로 확인·다운로드·sha256 검증·자가 교체
```

**다음 문서**: [② 구현된 UX/UI](02-ux-ui.md) — 사용자가 실제로 만나는 화면과 기능
