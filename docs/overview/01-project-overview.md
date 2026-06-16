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
(상세 메커니즘은 [④ Backend 동작 흐름](04-backend-flow.md) 참조)

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
│       ├─ components/  #    UI 컴포넌트 약 30개 (ChatArea·ArtifactPanel·SettingsModal …)
│       └─ lib/         #    전역 상태($state)·액션 함수·API 래퍼·SSE 파서
│
├─ backend/             # ② 서버 층 + ③ 에이전트 층
│   ├─ main.py          #    엔트리포인트 (FastAPI 앱 조립·기동)
│   ├─ core/            #    경로/포트/생명주기/업데이트/산출물 저장
│   ├─ api/             #    HTTP 엔드포인트 (도메인별 라우터 7개)
│   ├─ agent/           #    LLM 에이전트 하니스 (harness/·providers/·registries/·tools/ …)
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
독립적인 시각 도구가 필요하면 `extensions/`에 폴더 하나를 더하면 된다 (호스트 코드 무수정 — [② 에이전트·확장성](02-agent-and-extensibility.md)).

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

## 9. 정리 — 이 프로젝트를 한 장으로

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

**다음 문서**: [② 에이전트·확장성](02-agent-and-extensibility.md) — 에이전트 행동 정의와 독립 확장 도구

(UX/UI는 [③ 구현된 UX/UI](03-ux-ui.md) · 빌드·배포는 [⑤ 빌드 & 업데이트](05-build-and-update.md))
