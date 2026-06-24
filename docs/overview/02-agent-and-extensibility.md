# ② 에이전트 행동 정의 & 확장성

> **대상 독자**: 이 프로젝트에 에이전트를 적용·확장하려는 개발자·기획자
> **이 문서의 목표**: 코드 수정 없이 에이전트를 정의하는 세 계층(PROMPTS·SKILLS·AGENTS)과,
> 채팅 UI에 독립 도구를 붙이는 확장 시스템을 이해한다.

---

## 1. PROMPTS / SKILLS / AGENTS — 코드 수정 없는 에이전트 확장

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

> **오케스트레이터 baseline 라이브러리**: SKILL 없이도 오케스트레이터가 라이브러리 함수를
> docstring 기반으로 쓰게 하려면 `.env` 의 `APP_ORCHESTRATOR_API_REFS`(CSV) 에 함수 경로를
> 등록한다. 그 함수들의 시그니처·docstring 이 매 턴 `# Available Library APIs` 로 상시 주입된다
> (런타임 메타 도구 `call_function` 등은 원래 오케스트레이터에 항상 노출돼 있어, 이 변수가
> 채워주는 건 "무슨 함수가 있는지"라는 단서다). 빈 값이면 기존(SKILL 주도) 동작. 고수준 작업용
> 자체 래퍼는 `backend/scripts/`(루트명 `scripts`)에 두고 프롬프트가 `scripts.*` 를 우선
> 고르도록 유도한다 — raw 라이브러리는 scripts 가 내부에서 조합해 쓴다.

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

SKILL 활성화 경로는 세 가지다:
1. **트리거 키워드 자동 매칭** — 사용자 메시지에 trigger 키워드가 포함됐을 때
2. **슬래시 커맨드 강제 지정** — 입력창에 `/data_summary` 입력 시 (키워드 무관하게 반드시 적용)
3. **LLM 능동 활성화** (`activate_skill` 도구) — 트리거를 못 잡은 경우 LLM 이 비활성 SKILL 카탈로그를 보고 스스로 활성화 → system prompt 동적 재조립

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

## 2. 확장 시스템 (Extensions) — 폴더 단위로 더하고 빼는 독립 도구

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
> **있을 때만** 선별 번들한다 (→ [⑤ 빌드 & 업데이트](05-build-and-update.md)).

### 진입 규약 — `open_curation` 핸드오프

에이전트가 후보 데이터를 만든 뒤 사람을 확장 도구로 넘기는 표준 경로:

```
① 에이전트  후보 parquet 산출 → open_curation(tool, sources, mapping, mark) 호출
② 호스트    번들 스펙(<tool>.bundle.json) 작성
            → ToolResult(data={kind:"extension"}) — 전용 extension 칩으로 패널에 표시
③ 호스트    extension 칩이 아티팩트 패널에 자동 오픈
            → 패널 안에 /ext/<tool>/?bundle=... 를 same-origin iframe으로 임베드
④ 확장 도구  번들의 parquet 들을 로드 → 사람이 검토·선별·편집
⑤ 환류      도구가 결과를 내보내면 메인 앱 탭에 알림 → 데이터 칩 + 결정 요약으로 인폼
```

패널 헤더의 '최대화' 버튼으로 도구를 뷰포트 전체로 키워 볼 수 있다.

`open_curation`은 **evaluator에 특정되지 않는다** — `tool` 인자로 임의 확장을 가리키고
`mapping`도 해석 없이 번들에 그대로 실어 보낸다(확장이 해석). 확장 진입 규약을 한 곳에 모은
제네릭 호스트 훅이다.

### 예시 확장 — evaluator (parquet 큐레이션 BI)

AI가 만든 순위 후보 parquet을 **사람이 Tableau 풍 BI로 검토·선별·재정렬**해 최종 리포트용
데이터로 만드는 도구. 차트 7종(메인 앱 `display_chart`와 동일) · 컬럼 매핑 · 리스트 검색/필터 ·
드래그&드롭 순서변경 · 병합 보기 · 내보내기 환류를 갖춘다. **AI 생성 → 사람 큐레이션 → 결과 환류**의
닫힌 루프가 핵심 가치다 (사용자 화면은 [③ UX/UI](03-ux-ui.md), 백엔드는 [④ Backend](04-backend-flow.md) 참조).

---

## 3. 정리

```
코드 밖 확장점 ①  PROMPTS/ · SKILLS/ · AGENTS/ 마크다운  →  에이전트 행동 정의
코드 밖 확장점 ②  backend/agent/tools/ 파일 하나          →  새 도구 자동 등록
코드 밖 확장점 ③  extensions/ 폴더 하나                   →  독립 시각 도구 추가 (호스트 코드 무수정)
```

개발자 참고서:
- SKILLS/AGENTS 작성법 → [docs/guides/skills.md](../guides/skills.md) · [docs/guides/agents.md](../guides/agents.md)
- 도구 등록 방법 → [docs/guides/builtin-tools.md](../guides/builtin-tools.md)
- 확장 개발자 가이드 → [docs/guides/extensions.md](../guides/extensions.md)

---

**이전 문서**: [① 프로젝트 전체 흐름](01-project-overview.md)
**다음 문서**: [③ 구현된 UX/UI](03-ux-ui.md) — 사용자가 실제로 만나는 화면과 기능
