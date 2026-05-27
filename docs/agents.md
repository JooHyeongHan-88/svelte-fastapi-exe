# AGENTS 작성 가이드

`AGENTS/` 디렉터리의 마크다운 파일들은 **서브 에이전트 페르소나와 권한**을 정의한다.
오케스트레이터는 이 카탈로그를 읽어 적절한 서브 에이전트에게 작업을 위임한다.
파일 추가만으로 새 서브 에이전트가 런타임에 등록된다 (서버 재시작 후 반영, dev는 핫리로드).

---

## 파일 구조

```
AGENTS/
  coding_agent.md    ← 코딩 전문 서브 에이전트
  research_agent.md  ← 리서치 전문 서브 에이전트
```

파일마다 YAML Front Matter + 에이전트 페르소나 본문으로 구성된다.

```markdown
---
name: coding_agent
description: 소스코드 분석·리팩토링·테스트 작성을 전담하는 코딩 에이전트
skills: ["code_review"]
tools: []
priority: 5
---

# 코딩 에이전트

당신은 숙련된 소프트웨어 엔지니어 서브 에이전트입니다.
...페르소나 및 행동 원칙...
```

---

## Front Matter 필드

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `name` | string | **필수** | — | 에이전트 식별자. `call_sub_agent(agent_name=...)` 에 사용 |
| `description` | string | **필수** | — | 오케스트레이터가 위임 결정 시 읽는 한 줄 설명. 오케스트레이터 카탈로그에 노출 |
| `skills` | string[] | 선택 | `[]` | 이 에이전트가 전담하는 SKILL 이름 목록. Case 3 자동 라우팅의 핵심 |
| `tools` | string[] | 선택 | `[]` | 허용 도구 화이트리스트. **빈 리스트면 전체 도구 노출** |
| `priority` | int | 선택 | `5` | 동일 스킬을 전담하는 에이전트가 여럿일 때 우선순위 |
| `role` | string | 선택 | `null` | 직무 정체성 한 줄. 오케스트레이터 카탈로그·에이전트 자기인식에 사용 |
| `goal` | string | 선택 | `null` | 에이전트가 달성하려는 궁극 목표 한 줄 |
| `when_to_delegate` | string | 선택 | `null` | 오케스트레이터가 이 에이전트로 위임해야 하는 신호 — 입력 패턴 설명 |
| `api_refs` | string[] | 선택 | `[]` | 외부 Python 라이브러리 dotted-path 목록. 위임 시 시그니처·docstring 이 system prompt 에 자동 주입되고 메타 도구 7종이 화이트리스트와 무관하게 노출됨 → [library-runtime.md](library-runtime.md) |

### name

- 영소문자 + 언더스코어: `sales_agent`, `coding_agent`
- `call_sub_agent(agent_name="coding_agent")` 에서 정확히 일치해야 함
- 대소문자 구분 있음

### description

오케스트레이터 system prompt 에 다음 형태로 주입된다:

```
# 가용 서브 에이전트 카탈로그
- **coding_agent**: 소스코드 분석·리팩토링·테스트 작성을 전담하는 코딩 에이전트
  전담 스킬: code_review
```

오케스트레이터 LLM이 이 설명을 보고 위임 여부를 결정하므로 **전담 도메인을 명확히** 작성한다.

### skills

```yaml
skills: ["code_review", "refactoring"]
```

- 여기에 SKILL `name` 을 등록하면 **Case 3 자동 라우팅** 작동
- 사용자 메시지에 해당 SKILL 의 trigger 가 매칭되면 오케스트레이터가 자동으로 이 에이전트에게 위임
- SKILL 이름이 `SKILLS/` 에 실제로 존재하지 않으면 부팅 시 경고 출력 (라우팅은 무해하게 건너뜀)

```
# Case 3 동작 예시
사용자: "코드 리뷰해줘"
  → code_review 스킬 트리거 매칭
  → coding_agent.skills 에 "code_review" 있음
  → 오케스트레이터가 call_sub_agent(agent_name="coding_agent", task=...) 자동 호출
```

### tools

```yaml
# 전체 도구 노출 (기본)
tools: []

# 특정 도구만 허용
tools: ["fetch_sales", "fetch_inventory", "add_todo", "complete_todo"]
```

- 빈 리스트: `call_sub_agent`, `complete_subagent` 를 제외한 **모든 등록 도구 사용 가능**
- 화이트리스트 지정 시: 목록의 도구만 이 에이전트에게 노출 (`call_sub_agent` 는 항상 제외)
- `add_todo`, `complete_todo` 를 화이트리스트에 포함시키면 서브 에이전트도 자체 Plan 작성 가능
- `ask_user` 를 포함시키면 서브 에이전트가 슬롯 부족 시 사용자에게 직접 질문 가능

---

## 본문(페르소나) 작성 요령

본문은 서브 에이전트의 **system prompt 에 그대로 주입**된다.
오케스트레이터 system prompt 와 완전히 격리되므로 도메인에 맞는 독립적 지침을 작성한다.

### 필수 포함 요소

**1. 페르소나 선언**

```markdown
당신은 숙련된 소프트웨어 엔지니어 서브 에이전트입니다.
오케스트레이터로부터 넘겨받은 코드 작업 지시를 신중히 수행합니다.
```

**2. 행동 원칙**

```markdown
## 행동 원칙
- 파일을 수정하기 전에 항상 현황을 파악한다.
- 필수 정보(파일 경로, 함수명)가 부족하면 추정하지 말고 "[정보 부족]" 으로 표기한다.
- 위임받은 범위 밖의 작업을 임의로 확장하지 않는다.
```

**3. 종료 규약 (반드시 명시)**

서브 에이전트는 작업 완료 시 `complete_subagent` 도구를 호출해야 한다.
harness 가 자동으로 종료 규약을 system prompt 끝에 추가하지만,
본문에도 명시하면 LLM 준수율이 높아진다.

```markdown
## 종료 규약 (필수)
작업을 마칠 때 반드시 `complete_subagent` 도구를 호출한다.
summary 에 수행 내용과 핵심 결과를 1~3문장으로 기술한다.
이 도구를 호출하지 않으면 오케스트레이터가 결과를 인식하지 못한다.
```

> **참고**: `complete_subagent` 를 호출하지 않아도 harness 가 마지막 텍스트 응답에서
> `Task Summary:` 헤더를 찾아 폴백 요약을 추출하므로, 아예 응답이 없는 경우가 아니면
> 오케스트레이터는 최소한의 요약을 받게 된다.

### 전체 예시

```markdown
---
name: sales_agent
description: 매출·재고 관련 데이터 조회와 분석을 전담하는 서브 에이전트
skills: ["sales_report", "inventory_check"]
tools: ["fetch_sales", "fetch_inventory", "add_todo", "complete_todo", "complete_subagent"]
priority: 7
---

# 매출 분석 에이전트

당신은 영업 데이터 분석 전문 서브 에이전트입니다.
오케스트레이터로부터 위임받은 매출·재고 조회 작업을 정확하게 수행합니다.

## 행동 원칙
- 요청된 기간과 세그먼트 범위만 조회한다. 임의로 확장하지 않는다.
- 수치는 조회 결과 그대로 보고한다. 추정값을 단정형으로 보고하지 않는다.
- 데이터가 비어 있으면 "해당 기간 데이터 없음"으로 명확히 보고한다.

## 종료 규약 (필수)
작업 완료 시 반드시 `complete_subagent` 를 호출한다.
summary 에 조회한 기간, 핵심 수치, 이상 여부를 2문장 이내로 기술한다.
```

---

## 라우팅 메커니즘

### Case 2 — 사용자 명시 위임

사용자가 에이전트 이름을 직접 언급하면 오케스트레이터가 즉시 위임한다.

```
사용자: "coding_agent 한테 리팩토링 맡겨줘"
  → orchestrator: call_sub_agent(agent_name="coding_agent", task="리팩토링 ...")
```

### Case 3 — 스킬 트리거 자동 위임

사용자 메시지에 SKILL 트리거가 매칭되고 해당 SKILL 을 전담하는 에이전트가 있으면 자동 위임된다.

```
사용자: "코드 리뷰해줘"
  → SkillRegistry: code_review 스킬 매칭
  → AgentRegistry: coding_agent.skills = ["code_review"] → 매핑 확인
  → orchestrator: call_sub_agent(agent_name="coding_agent", task=...)
```

오케스트레이터 system prompt 에 다음 형태로 강제 규칙이 주입된다:

```
## Case 3 결정론 매핑 (반드시 준수)
- 'code_review' 트리거가 들어오면 반드시 `coding_agent` 에게 `call_sub_agent` 로 위임
```

---

## 서브 에이전트 제약 사항

서브 에이전트는 아래 동작이 **4중 방어선으로 완전 차단**된다.

| 제약 | 이유 |
|---|---|
| `call_sub_agent` 호출 불가 | 무한 재귀 위임 방지 |
| 병렬·비동기 실행 불가 | 순차 실행만 지원 |
| 백그라운드 실행 불가 | 결과가 반환될 때까지 동기 대기 |

서브 에이전트가 할 수 있는 것:

| 기능 | 설명 |
|---|---|
| `add_todo` / `complete_todo` | 자체 작업을 단계로 분해 (서브 에이전트 격리 상태 사용) |
| `ask_user` | 슬롯 부족 시 사용자에게 직접 질문 (orchestrator 에 pending 저장 후 다음 턴 재위임) |
| `complete_subagent` | 작업 완료 보고 및 종료 |
| 화이트리스트 내 일반 도구 | 등록된 사내 API 도구 실행 |

---

## 자주 하는 실수

| 실수 | 결과 | 수정 방법 |
|---|---|---|
| `skills` 에 SKILLS 에 없는 이름 등록 | 부팅 시 경고, Case 3 라우팅 미작동 | SKILLS `name` 과 정확히 일치시킬 것 |
| `tools` 에 `call_sub_agent` 포함 | 부팅 시 경고 없이 harness 가 specs 에서 제거 | 명시할 필요 없음, 항상 제외됨 |
| 종료 규약(`complete_subagent`) 미언급 | LLM 미준수율 상승 → 오케스트레이터가 요약 폴백 사용 | 본문에 명시적으로 안내 |
| `description` 에 도메인 범위 모호하게 작성 | 오케스트레이터가 위임 여부를 잘못 판단 | 구체적인 도메인 키워드 포함 |
| 여러 에이전트가 같은 `skills` 등록 | priority 높은 쪽으로 자동 위임 | priority 로 의도를 명확히 하거나 skills 를 분리 |
