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

이 프로젝트는 **미리 갖추어진 Python API를 plan에 따라 실행하는 Agent 도구**다.
코드를 작성하거나 파일을 편집하는 AI 코딩 어시스턴트가 아니다. 다음 원칙을 반드시 숙지할 것.

### 에이전트 행동 패턴

| 상황 | 에이전트 행동 |
|---|---|
| 일반 질문 | 텍스트로 직접 답변 |
| 도구 실행이 필요한 작업 | `add_todo` 로 plan 작성 → 등록된 tool 순차 실행 → `complete_todo` |
| 복잡한 작업 (여러 도메인) | 오케스트레이터가 `call_sub_agent` 로 서브 에이전트에게 위임 |

### 서브 에이전트 제약

- **병렬 실행 없음**: 서브 에이전트는 항상 순차 실행. `asyncio.gather` 류의 동시 위임은 설계 외.
- **백그라운드 실행 없음**: 모든 위임은 결과가 오케스트레이터에 반환될 때까지 동기적으로 진행.
- **파일 편집 불필요**: 에이전트는 코드를 작성하거나 파일 시스템을 수정하지 않는다. 새 기능은 `@register_tool` 로 Python 함수를 추가하는 방식으로만 확장.

### AGENTS/ vs SKILLS/

| 디렉터리 | 역할 | 라우팅 |
|---|---|---|
| `SKILLS/` | 오케스트레이터·서브 에이전트 공통 작업 가이드 | Front Matter `trigger` 키워드 매칭 |
| `AGENTS/` | 서브 에이전트 페르소나·도구 화이트리스트 | `call_sub_agent(agent_name=...)` 명시 위임 |

### Sub-agent 위임 구조 (Anthropic 가이드라인 준수)

```
Main agent
├─ SKILL 동적 매칭 → system prompt 주입
│   └─ SKILL 가이드에 따라 call_sub_agent 호출 가능 ✅
│
└─ sub-agent X  (call_sub_agent 로 위임된 에이전트)
    ├─ agent.meta.skills 에 선언된 SKILL body 사용 가능 ✅
    └─ 다시 call_sub_agent 호출 ❌  (4중 차단)
```

중첩 위임 차단 방어선 (`backend/agent/harness.py`):
- **L0** (`_dispatch_sub_agent`): `agent_registry=None` 전달 — dispatch 분기 자체를 열지 않음
- **L1** (`_filter_specs_for_sub_agent`): `SUB_AGENT_DISPATCH` 를 `forbidden` 집합으로 제거
- **L2** (`MAX_AGENT_DEPTH=1`): depth=2 진입 시 즉시 `[depth-guard]` 거부
- **L3** (`_execute_tool` sentinel guard): hallucinate 호출도 `[error] sentinel tool ...` 반환

회귀 테스트: `backend/tests/test_subagent_isolation.py`

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
cd backend && uv run python -m pytest tests/ -v         # 전체
cd backend && uv run python -m pytest tests/test_subagent_isolation.py -v  # 특정 파일

# 프로덕션 빌드 / 릴리즈
pwsh packaging/release.ps1
pwsh packaging/release.ps1 -Upload -Notes "..."         # .env에서 Nexus 자격증명 자동 로드
pwsh packaging/release.ps1 -Force                       # git dirty 상태나 버전 중복 강제 통과
pwsh packaging/release-dryrun.ps1                       # 네트워크 없이 업데이트 파이프라인 검증
pwsh packaging/release-dryrun.ps1 -Force                # dirty 브랜치에서 dryrun
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
    harness.py        run_turn — 핵심 턴 루프 (fallback, loop detection, error recovery 포함)
    guard.py          슬롯 가드
    models.py         Pydantic 메시지·이벤트·상태 (StreamEvent 등)
    stores/           영속·인메모리 저장소
      conversation.py ConversationStore (대화 히스토리)
      agent_state.py  AgentStateStore (todo · missing_slots 디스크 영속)
    registries/       에이전트가 인지하는 자산 카탈로그
      prompts.py      PromptRegistry
      skills.py       SkillRegistry
      tools.py        ToolRegistry
      agents.py       AgentRegistry (AGENTS/*.md 서브 에이전트 카탈로그)
    providers/        LLM 어댑터
      factory.py      get_provider() 디스패처 (mock / dtgpt / openai_compatible)
      mock.py         Mock (테스트용)
      openai.py       OpenAI Compatible — DTGPT도 이 구현체를 재사용
    tools/            @register_tool 데코레이터 기반 사내 API 도구 모음
      __init__.py     하위 모듈 import → 데코레이터 자기등록 트리거
      builtin.py      now (기본 내장)
      planner.py      add_todo / complete_todo (sentinel)
      dispatch.py     call_sub_agent (sentinel)
      clarify.py      ask_user (sentinel)

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

  tests/              회귀 테스트
    test_subagent_isolation.py  중첩 서브 에이전트 차단 L0~L3 검증

PROMPTS/              base.md + safety.md + orchestrator.md — system prompt 합성
SKILLS/               작업별 가이드. Front Matter trigger 로 라우팅, 매칭된 본문만 lazy 로드
AGENTS/               서브 에이전트 페르소나 정의. Front Matter에 name/description/skills/tools 선언
                      현재 등록: coding_agent (코드 작업 전담), report_agent (markdown 리포트 작성·렌더링 전담)

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
> `PROMPTS/`, `SKILLS/`, `AGENTS/` 는 디렉터리 단위 등록됨 — 파일 추가만으로 다음 빌드에 반영.

---

## 환경 변수 (`.env` / `backend/core/config.py` · `backend/agent/config.py`)

`.env`는 dev 전용이며 **빌드 파이프라인(`App.spec`, `release.ps1`)의 단일 진실 공급원**. frozen EXE는 OS 환경 변수만 읽는다.

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
| `APP_MAX_AGENT_DEPTH` | `1` | 서브 에이전트 호출 깊이 상한 (1 이상 변경 시 경고) |
| `APP_MAX_HISTORY_MESSAGES` | `40` | 클라이언트당 보관 메시지 수 상한 |
| `APP_SETTINGS_TEST_TIMEOUT` | `10` | 연결 테스트 타임아웃 (초) |
| `APP_TOOL_DEFAULT_TIMEOUT` | `30` | Tool 1회 실행 timeout (초) — 도구별 `timeout_seconds` 로 override |

> `.env` 값에 `# 인라인 주석`이 있어도 파서가 자동으로 제거한다.

---

## 에이전트 런타임 주요 동작

### 루프 감지 (Smart Loop Detection)
동일 도구를 동일 인자로 재호출하면 실행을 차단하고 LLM에게 원인 분석(RCA) 후 다른 접근법을 요구하는 시스템 메시지를 주입한다. `_run_agent_turn` 내 `history_calls: set[tuple[str, str]]`로 관리.

### 에러 회복 (Error Recovery)
도구가 `is_error=True`를 반환하면 `result.content` 끝에 RCA + 1회 재시도 유도 메시지를 자동 append한다 (`_execute_tool`).

### Graceful Degradation (Fallback)
`max_iterations` 도달 시 tools 없이 LLM을 한 번 더 호출해 "지금까지 완료된 작업과 실패 원인"을 자연어로 생성한 뒤 `ErrorEvent(is_fallback=True)`를 발행한다. 프론트엔드는 이 플래그를 감지해 해당 메시지를 danger 테마로 스타일링한다.

---

## 새 API 를 Tool 로 등록하기

`backend/agent/tools/` 에 새 `.py` 파일을 만들고 `@register_tool` 데코레이터를 붙이기만 하면 된다. 부팅 시 `agent/tools/__init__.py` 가 모든 서브모듈을 import 해 자동 등록한다.

```python
# backend/agent/tools/sales.py
from datetime import date
from typing import Annotated
from agent.models import ToolResult
from agent.registries.tools import register_tool

@register_tool(
    description="매출 데이터를 기간으로 조회한다.",
    slot_prompts={"date_from": "조회 시작일(YYYY-MM-DD)을 알려주세요"},
    timeout_seconds=15,
)
async def fetch_sales(
    date_from: Annotated[date, "조회 시작일"],
    date_to: Annotated[date, "조회 종료일"],
) -> ToolResult:
    rows = await my_db.fetch_sales(date_from, date_to)
    return ToolResult(content=f"{len(rows)} rows fetched", data={"rows": rows})
```

규칙:
- 함수는 반드시 `async`. 동기 함수는 등록 시 `TypeError`.
- 각 파라미터에 `Annotated[T, "설명"]` 로 의미 부착 — JSON Schema description 으로 LLM 에 노출.
- 반환값은 `str` 또는 `ToolResult`. dict 등 임의 객체는 `str(...)` 로 폴백 변환.
- 인자 검증은 Pydantic 이 자동. 형식 오류 (e.g. `date_from="오늘"`) 도 `AskUserEvent` 로 자연스러운 재질문.
- `sentinel=True` 는 harness 가 분기 처리하는 도구 (`add_todo` 등) 전용. 함부로 쓰지 말 것.

---

## 새 서브 에이전트 등록하기

`AGENTS/` 에 새 `.md` 파일을 만들고 YAML Front Matter를 작성하면 된다.

```markdown
---
name: sales_agent
description: 매출·재고 관련 조회를 전담하는 서브 에이전트
skills:
  - sales_report      # SKILLS/ 에 동일 이름 파일 존재 시 Case 3 자동 라우팅
tools:
  - fetch_sales       # 빈 리스트면 전체 도구 노출
  - fetch_inventory
priority: 5
---

당신은 영업 데이터 분석 전문가입니다.
...에이전트 페르소나 및 작업 지침...
```

규칙:
- `name`은 `call_sub_agent(agent_name=...)` 에서 사용할 식별자.
- `skills` 에 SKILLS 이름을 등록하면 해당 트리거 발생 시 오케스트레이터가 자동 위임 (Case 3).
- `tools` 가 비어 있으면 해당 에이전트는 등록된 모든 도구를 사용할 수 있다.
- 본문(페르소나)은 위임 시점에 lazy load — 부팅 비용 없음.
- 서브 에이전트는 다시 `call_sub_agent` 를 호출할 수 없다 (4중 방어선으로 차단됨).

---

## 상세 문서 (`.claude/rules/`)

| 파일 | 내용 |
|---|---|
| `backend_architecture.md` | App 생명주기 · presence 설계 · 동시성 · Origin 가드 · frozen 경로 · 에이전트 하니스 · AgentRegistry |
| `frontend_architecture.md` | Svelte 5 상태 패턴 · 컴포넌트 책임 · localStorage 스키마 · 데이터 흐름 |
| `settings_architecture.md` | LLM 설정 저장 위치 · API key 보안 · threading.Lock 주의 · 프로바이더 추가 방법 |
| `update_architecture.md` | 자동 업데이트 4단계 흐름 · rename-to-backup 전략 · PowerShell 5.1 주의점 |
| `code_conventions.md` | Python 코딩 규칙 · ruff · 타입 힌트 · docstring · 예외 처리 |
