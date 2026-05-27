# Mock Provider 시나리오 가이드

`backend/agent/providers/mock.py` 의 `MockProvider` 는 실제 LLM 없이 harness·UI 전체 흐름을
결정론적으로 검증하기 위한 가짜 응답기다. 사용자가 특정 트리거 문구를 입력하면 미리 정의된
시나리오가 발동되어 도구 호출·산출물 저장·스트리밍 응답을 자동으로 재현한다.

---

## 산출물 경로 규약

Mock Provider 가 생성하는 파일은 모두 `result/` 하위에 저장된다.

```
result/
  {세션제목}-{client_id[:8]}/      ← session_dir_name()
    {YYYYMMDD-HHmmss}/             ← artifact_slot()  (호출마다 새 슬롯)
      favicon.svg                  ← B1 이미지 데모
      correlation.json             ← B3 산점도 데이터
      report.md                    ← D5 리포트 본문
```

- 폴더명은 `result_store.sanitize_title()` 로 Windows/POSIX 안전 처리된다.
- 같은 세션에서 동일 파일이 이미 있으면 (`_find_existing_artifact`) 재사용 — 새 슬롯을 만들지 않는다.
- `result/` 는 `.gitignore` 에 등재되어 있으므로 생성된 파일은 추적되지 않는다.

---

## 시나리오 목록

### Category A — UI 표현 검증

| ID | 트리거 문구 | 검증 대상 |
|---|---|---|
| **A1** | `생각해`, `추론`, `think`, `reason` | `ReasoningEvent` → 접을 수 있는 ReasoningBlock 토글 |
| **A2** | `자유 질문`, `ask text` | `AskUserCard` — `input_type: text` (자유 입력만) |
| **A3** | `기간 선택`, `기간을 골라`, `ask choice` | `AskUserCard` — `input_type: choice` (버튼만) |
| **A4** | `데이터 좀 보여줘`, `모호한 요청`, `ask both` | `AskUserCard` — `input_type: both` (버튼+자유입력) |
| **A5** | *(위 트리거 미매칭 시 기본)* | 입력 echo — 기본 markdown 렌더링 |

**A2~A4** 후속 턴: 사용자 답변을 받으면 `"'{답변}'으로 조회를 시작하겠습니다."` echo 를 반환한다.

---

### Category B — SKILL 라우팅 검증

#### B1 `skill_time_lookup`

**트리거**: `지금 시간`, `현재 시각`, `몇 시`, `what time`, `now()`

**흐름 (3회 provider 호출)**:

```
호출 1  → now() 도구 실행
호출 2  → favicon.svg 를 result/{session}/{ts}/favicon.svg 에 복사
          → display_image(source="result/...", alt="앱 아이콘")
호출 3  → "현재 시각은 {time} 입니다." 자연어 응답
```

**검증**: `SkillActiveEvent(time_lookup)` → `now` 도구 → 파일 복사 → 아티팩트 패널 이미지 표시

---

#### B2 `skill_report_planner`

**트리거**: `보고서`, `리포트`, `report`  
*(단, "전체 보고서" / "리포트 에이전트" 는 각각 C2/D5 가 먼저 차지)*

**흐름 (1회 provider 호출)**:

```
호출 1  → add_todo(["매출 데이터 조회", "보고서 본문 생성", "이메일 발송"])
```

**검증**: `SkillActiveEvent(report_writer)` → `TodoProgress` 체크리스트 생성만 하고 완료는 하지 않음.
실제 에이전트 플래너 동작 학습용으로 활용한다.

---

#### B3 `skill_data_analysis`

**트리거**: `데이터 분석`, `data analysis`, `산점도`, `scatter 차트`

**흐름 (3회 provider 호출)**:

```
호출 1  → correlation.json 생성 (30포인트 가상 산점도 데이터)
          → add_todo(["데이터 수집", "정제", "시각화 및 요약"])
호출 2  → complete_todo × 3 (각 단계 요약 포함)
          → display_chart(scatter, series=[{name:"X-Y 상관", data:[...]}])
호출 3  → "## 데이터 분석 완료" markdown 최종 보고
```

**생성 파일**: `result/{session}/{ts}/correlation.json`

```json
{
  "x_label": "변수 X",
  "y_label": "변수 Y",
  "points": [[0.0, 0.0], [0.35, 0.20], ...]  // 30포인트, y≈0.7x+노이즈
}
```

**검증**: 파일 산출물 → `TodoProgress` 3단계 → ECharts 산점도 인터랙티브 차트

---

### Category C — TOOL 실행 검증

| ID | 트리거 문구 | 흐름 | 검증 대상 |
|---|---|---|---|
| **C1** | `검색`, `search`, `데이터 조회` | `demo_search({})` 인자 없이 호출 | 슬롯 가드 → `AskUserCard` (필수 인자 누락) |
| **C2** | `전체 보고서`, `full report` | `add_todo(3)` → `complete_todo × 3` 순차 완료 | `TodoProgress` `PENDING → COMPLETED` 전환 |

---

### Category D — 서브 에이전트 위임 검증

> **우선순위**: D 카테고리 트리거가 B/C 보다 먼저 검사된다.

| ID | 트리거 문구 | 위임 대상 | 검증 |
|---|---|---|---|
| **D1** | `코딩 에이전트`, `coding_agent`, `코드 리팩토링` | `coding_agent` | Case 2 명시 위임 + `AgentTrail` 칩 |
| **D2** | `리서치 에이전트`, `research_agent`, `조사 에이전트` | `research_agent` | Case 2 명시 위임 |
| **D3** | `전체 분석`, `full analysis` | `coding_agent` → `research_agent` | 순차 체이닝 → 통합 보고 |
| **D4** | *(D1/D2/D3 위임 후 sub-agent context)* | — | 서브 에이전트 내부 `now` 호출 + Task Summary |
| **D5** | `리포트 에이전트`, `report_agent` | `report_agent` | markdown 산출물 생성 + 패널 렌더링 |

#### D5 상세 — `report_agent`

```
sub-agent 호출 1  → report.md 를 result/{session}/{ts}/ 에 기록
                    → display_markdown(source="result/...", title="분기별 매출 분석 리포트")
sub-agent 호출 2  → complete_subagent(summary="report.md 생성 후 렌더링 완료")
```

**생성 파일**: `result/{session}/{ts}/report.md`

포함 요소: H1/H2 헤더, 분기별 매출 표, 불릿 인사이트, fenced code block, blockquote.
`ArtifactMarkdown` 컴포넌트의 렌더링 전반을 검증하기 위한 복합 구조.

---

### Category E — 복합 통합 시나리오

#### E1 `composite_full_demo`

**트리거**: `종합 시연`, `전체 시연`, `full demo`, `복합 시연`

**흐름 전체 (오케스트레이터 6단계 + 서브 에이전트 각 3단계)**:

```
오케스트레이터
  Step 1  add_todo(["리서치 단계", "코드 검토 단계"])
  Step 2  call_sub_agent(research_agent, task="[E1-composite] 데이터 분석 단계 수행")
    └─ sub: SkillActiveEvent(data_analysis) → ReasoningEvent → add_todo(3) → complete_todo×3 → complete_subagent
  Step 3  complete_todo(리서치 단계)
  Step 4  call_sub_agent(coding_agent, task="[E1-composite] 코드 검토 단계 수행")
    └─ sub: SkillActiveEvent(code_review) → ReasoningEvent → add_todo(3) → complete_todo×3 → complete_subagent
  Step 5  complete_todo(코드 검토 단계)
  Step 6  ReasoningEvent + "## 종합 시연 결과" markdown 최종 보고
```

**검증 대상**:
- 오케스트레이터 `TodoProgress` (2단계)
- `AgentTrail` — 에이전트 전환 칩
- 서브 에이전트 슬롯 내부 `SkillBadge`
- 서브 에이전트 슬롯 내부 `ReasoningBlock`
- 서브 에이전트 슬롯 내부 `TodoProgress` (3단계)
- 최종 마크다운 응답 렌더링

---

## 분기 우선순위 (MockProvider.astream)

```
1  sub-agent context  → E1 sub / D4 generic sub
2  E1 composite       트리거 매칭
3  D3 chain           트리거 매칭
4  D1/D2/D5 위임      트리거 매칭 (이미 위임 결과 없을 때)
5  위임 결과 수신 후  → 자연어 최종 보고
6  B1 time_lookup     트리거 매칭
7  C2 full_report     트리거 매칭 (B2보다 먼저 검사)
8  B2 report_planner  트리거 매칭
8b B3 data_analysis   트리거 매칭
9  C1 slot_guard      트리거 매칭
10 A2~A4 ask_user     트리거 매칭
11 A2~A4 답변 후 echo
12 A1 reasoning       트리거 매칭
13 A5 echo            (기본 폴백)
```

---

## 개발 활용 팁

### 새 시나리오 추가

1. 트리거 상수를 `_XXX_TRIGGERS = (...)` 형태로 파일 상단에 선언한다.
2. `async def _xxx_scenario(messages) -> AsyncIterator[StreamEvent]` 함수를 작성한다.
3. `MockProvider.astream` 내 우선순위에 맞는 위치에 분기를 삽입한다.
4. 도구 호출마다 `tool_call_id` prefix 를 `"mock-xxx-"` 처럼 고유하게 짓고,
   `_has_recent_tool_result(messages, "mock-xxx-")` 로 상태를 추적한다.

### 산출물 파일이 필요한 시나리오

```python
from core.result_store import artifact_slot, session_dir_name

def _ensure_my_artifact() -> Path:
    existing = _find_existing_artifact("my_output.json")
    if existing:
        return existing          # 동일 세션 재사용
    slot = artifact_slot()       # contextvars 에서 client_id/title 자동 조회
    dest = slot / "my_output.json"
    dest.write_text(json.dumps(data), encoding="utf-8")
    return dest
```

반환 경로를 도구 인자로 전달할 때:

```python
# display_image / display_markdown source 인자 형식
f"result/{session_dir_name()}/{slot.name}/{dest.name}"

# 또는 artifact 로부터 직접 구성
f"result/{artifact.parent.parent.name}/{artifact.parent.name}/{artifact.name}"
```

### LLM-visible 산출물 저장 패턴 (권장)

가능하면 mock 시나리오도 Python 이 직접 디스크에 쓰지 말고 **`save_artifact` 도구 호출
이벤트를 yield** 해 실제 LLM 동작을 모방한다. 이렇게 하면 mock → real LLM 전환 시
파이프라인이 그대로 작동하며, save_artifact 의 검증·turn_slot 캐시 동작도 함께 검증된다.

```python
yield ToolCallEvent(
    call=ToolCall(
        id=f"mock-xxx-save-{uuid.uuid4().hex[:8]}",
        name="save_artifact",
        arguments={
            "filename": "my_output.json",
            "content": json.dumps(data, ensure_ascii=False, indent=2),
            "kind": "json",
        },
    )
)
```

후속 호출에서 파일을 읽을 때는 `_find_existing_artifact(filename)` 로 같은 세션 디렉터리를
역순 탐색하면 turn_slot 이 만든 폴더에서 곧바로 발견된다.

**현재 상태**:
- B3 (data_analysis) 시나리오 — `save_artifact` 호출 패턴으로 시연 (권장 패턴 레퍼런스)
- D5 (report_agent) 시나리오 — 직접 write 유지 (신/구 패턴 비교용 디버깅 레퍼런스)

새 시나리오는 가능하면 B3 패턴을 따른다.

### Mock Provider 전환

설정 UI(`/api/settings`) 에서 provider 를 `mock` 으로 전환하거나,
`.env` 에 `APP_LLM_PROVIDER=mock` 을 설정하면 LLM 연결 없이 시나리오 전체를 실행할 수 있다.

서버를 재시작하지 않아도 `/api/settings` POST 로 핫스왑 가능하다.
