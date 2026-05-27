# SKILLS 작성 가이드

`SKILLS/` 디렉터리의 마크다운 파일들은 **에이전트의 상황별 행동 지침**이다.
사용자 메시지에 트리거 키워드가 포함되면 해당 파일의 본문이 시스템 프롬프트에 주입된다.
코드를 수정하지 않고 파일 추가만으로 에이전트 동작을 확장할 수 있는 핵심 확장 포인트다.

---

## 파일 구조

```
SKILLS/
  report_generator.md   ← 파일명은 자유, name Front Matter 가 실제 식별자
  time_lookup.md
  data_analysis.md
```

파일마다 YAML Front Matter + 마크다운 본문으로 구성된다.

```markdown
---
name: report_generator
description: 매출 보고서를 조회·생성·이메일 발송하는 멀티스텝 작업
trigger: ["보고서", "리포트", "report", "이메일 발송", "주간 매출"]
priority: 8
requires_tools: ["fetch_sales", "render_report", "send_email"]
---

# 보고서 자동 생성 가이드
...본문...
```

---

## Front Matter 필드

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `name` | string | **필수** | — | 스킬 식별자. 슬래시 커맨드(`/report_generator`), `AGENTS/` 의 `skills` 목록에서 이 이름으로 참조 |
| `description` | string | 선택 | `""` | 한 줄 요약. 슬래시 커맨드 자동완성 패널에 표시 |
| `trigger` | string[] | 선택 | `[]` | 사용자 메시지에서 찾을 키워드 목록. 대소문자 무관 부분문자열 매칭 |
| `priority` | int | 선택 | `5` | 여러 스킬이 동시에 매칭될 때 우선순위. 값이 클수록 먼저 선택 |
| `requires_tools` | string[] | 선택 | `[]` | 이 스킬이 사용하는 도구 이름 힌트. 해당 도구가 미등록이면 priority 에서 감점 |
| `api_refs` | string[] | 선택 | `[]` | 외부 Python 라이브러리 dotted-path 목록. 활성화 시 시그니처·docstring 이 system prompt 에 자동 주입되고 메타 도구 7종이 자동 노출됨 → [library-runtime.md](library-runtime.md) |

### name

- 영소문자 + 언더스코어 형식 권장: `sales_report`, `time_lookup`
- `AGENTS/` Front Matter 의 `skills` 배열에 이 이름을 적어야 Case 3 라우팅이 작동
- 슬래시 커맨드로 강제 활성화할 때도 이 이름을 사용: `/sales_report`

### trigger

```yaml
trigger: ["보고서", "리포트", "report", "이메일 발송", "주간 매출", "일일 매출"]
```

- 사용자 메시지 전체에서 각 키워드를 **포함 여부**로 판단 (정규식 아님)
- 여러 키워드가 동시에 포함되면 hit count 가 늘어 우선순위 상승
- `trigger` 가 없어도 사용자가 `name` 자체를 입력하면 매칭됨 (`"time_lookup 써줘"` → `time_lookup` 활성)

### priority

- 동점(hit count 동일)일 때 이 값이 높은 스킬이 먼저 선택됨
- 한 턴에 최대 3개 스킬이 동시 활성화될 수 있음
- `requires_tools` 에 등록되지 않은 도구가 있으면 `priority -= 미등록_수 × 10` 감점

### requires_tools

```yaml
requires_tools: ["fetch_sales", "send_email"]
```

- 실제 실행을 강제하지 않음 — 우선순위 계산 힌트용
- 나열한 도구가 `ToolRegistry` 에 없으면 이 스킬의 priority 가 자동 감점됨
- 도구가 필요 없는 순수 가이드 스킬이면 생략하거나 빈 리스트로 둠

---

## 본문(Body) 작성 요령

본문은 시스템 프롬프트에 `# Skill: {name}\n{본문}` 형태로 그대로 주입된다.
LLM이 읽을 지시문이므로 **명확한 행동 규칙**을 우선적으로 작성한다.

### 단순 스킬 — 도구 1~2개, 단일 호출

```markdown
---
name: time_lookup
trigger: ["지금 시간", "현재 시각", "몇 시", "now"]
priority: 3
requires_tools: ["now"]
---

# 가이드
- `now` 도구를 한 번만 호출한다.
- 결과는 "현재 시각은 …입니다." 한 문장으로 답한다.
- 시각 외 정보 요청(날짜 계산, 타임존 변환)은 명확하지 않으면 되묻는다.
```

### 멀티스텝 스킬 — add_todo 패턴 필수

두 단계 이상의 순차 작업이 있으면 반드시 `add_todo` 패턴을 명시한다.

```markdown
---
name: report_generator
trigger: ["보고서", "리포트", "주간 매출"]
priority: 8
requires_tools: ["fetch_sales", "render_report", "send_email"]
---

# 보고서 자동 생성 가이드

## 절차
1. `add_todo` 로 아래 3단계를 한 번에 등록한다.
2. `fetch_sales(date_from, date_to)` 데이터 조회 → `complete_todo`
3. `render_report(template, data)` 본문 생성 → `complete_todo`
4. `send_email(to, subject, body)` 발송 → `complete_todo`

## 필수 슬롯
- 보고 기간: 명시하지 않으면 되묻는다.
- 수신자: 명시하지 않으면 선택지를 제시한다.

## 금지
- 임의 수신자나 이메일 주소를 추측하지 않는다.
- 데이터가 없을 때 더미 값을 채워 넣지 않는다.
```

### 서술 구조 권장 패턴

| 섹션 | 내용 |
|---|---|
| `## 절차` | 순서가 중요한 경우 numbered list |
| `## 필수 슬롯` | 반드시 확인해야 할 입력값과 확인 방법 |
| `## 행동 원칙` | 어떤 방식으로 판단할지 |
| `## 금지` | 해선 안 되는 행동 명시 |
| `## 출력 형식` | 최종 응답의 형태 |

---

## 라우팅 동작 상세

```
사용자: "이번 주 매출 보고서 뽑아줘"
  ↓
SkillRegistry.select("이번 주 매출 보고서 뽑아줘")
  ↓
trigger 매칭:
  report_generator: "보고서"(1hit), "주간 매출"(1hit) → 2hits, priority=8
  data_analysis:    "보고서"(0hit)                     → skip
  ↓
상위 3개 선택 → [report_generator]
  ↓
system prompt 에 주입:
  # Skill: report_generator
  {report_generator.md 본문}
```

### 슬래시 커맨드로 강제 활성화

trigger 매칭 없이 특정 스킬을 강제 활성화하려면 UI Composer 에서 슬래시를 입력한다.

```
사용자: /report_generator
```

`force_skills=["report_generator"]` 로 API 에 전달되어 trigger 매칭을 우회하고
해당 스킬이 바로 시스템 프롬프트에 포함된다.

### 멀티 스킬 동시 활성화

3개까지 동시 활성화된다. 이 경우 harness 가 자동으로 다음 지침을 추가 주입한다:

> "실제 작업을 시작하기 전에 반드시 `add_todo` 로 각 스킬의 실행 순서를 등록하세요."

---

## 자주 하는 실수

| 실수 | 결과 | 수정 방법 |
|---|---|---|
| `name` 을 파일명과 다르게 설정 | `AGENTS/` 에서 참조 실패 | `name` 과 파일명을 일치시킬 것 (필수는 아니지만 권장) |
| `trigger` 를 문자열로 작성 | Front Matter 파싱 오류, 스킬 로드 실패 | 반드시 YAML 배열 형식 `["a", "b"]` |
| `requires_tools` 에 실제 미등록 도구 나열 | priority 감점으로 다른 스킬에 밀림 | 미등록 도구는 나열하지 않거나 먼저 등록 |
| 본문에 `add_todo` 언급 없이 다단계 지시 | LLM이 plan 없이 단계 실행, TodoProgress UI 미표시 | 2단계 이상이면 반드시 절차 섹션에 `add_todo` 패턴 명시 |
