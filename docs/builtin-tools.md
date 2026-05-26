# 기본 내장 도구 가이드

이 프로젝트에는 새 API 도구를 `@register_tool` 로 추가하기 전부터 harness 에 내장된
도구들이 있다. 이 도구들은 **파일을 수정하지 않아도 항상 LLM 에 노출**된다.

도구 종류:
- **실행 도구**: 실제 로직이 실행되고 결과를 반환 (`now`, `display_image`, `display_chart`, `display_markdown`)
- **Sentinel 도구**: harness 가 tool_call 을 가로채 직접 처리 — 함수 본문은 절대 실행되지 않음

---

## 시각화 도구 (아티팩트 패널)

채팅창 우측 아티팩트 패널에 이미지·차트를 표시하는 실행 도구.
LLM 이 호출하면 `ToolResult.data` 를 통해 프론트엔드로 전달되고, 패널이 자동으로 열린다.
메시지 버블에는 "🖼️ …" / "📊 …" 형태의 칩이 생성되어 패널 재오픈이 가능하다.

---

### `display_image`

이미지를 아티팩트 패널에 표시한다.

#### 인자

| 인자 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `source` | string | **필수** | — | 이미지 경로, URL, 또는 data URI |
| `alt` | string | 선택 | `""` | 대체 텍스트 (접근성·AI 요약) |
| `caption` | string | 선택 | `""` | 이미지 아래 캡션 |

`source` 허용 형식:
- `result/<session>/<ts>/<파일명>` — 에이전트 산출물 (백엔드 `/result` StaticFiles mount)
- `workspace/<경로>` — 워크스페이스 파일
- `build/web/assets/<파일명>` 또는 `assets/<파일명>` — 프로젝트 자산 경로 (`/assets/<파일명>` 으로 자동 변환)
- `http://` / `https://` 로 시작하는 절대 URL
- `data:image/...;base64,...` 형태의 data URI

#### 동작

1. `source` 를 정규화해 `ToolResult.data = {kind:"image", src, alt, caption}` 반환
2. `ToolResultEvent.data` 를 통해 프론트엔드가 아티팩트 패널에 이미지 표시
3. 메시지 버블에 "🖼️ {alt|caption|source}" 칩 추가 — 클릭 시 패널 재오픈
4. 패널 오른쪽 상단 "새 탭" 버튼으로 원본 크기 확인 가능

#### 예시 (LLM 이 호출하는 형태)

```json
{
  "name": "display_image",
  "arguments": {
    "source": "build/web/assets/favicon.svg",
    "alt": "앱 아이콘",
    "caption": "현재 사용 중인 앱 로고"
  }
}
```

#### SKILL 에서 활용

```markdown
## 절차
1. `now` 도구로 현재 시각 조회
2. `display_image(source="build/web/assets/favicon.svg", alt="앱 아이콘")` 호출
3. "현재 시각은 …입니다." 형식으로 응답
```

---

### `display_chart`

ECharts 인터랙티브 차트를 아티팩트 패널에 표시한다.
드래그 선택(brush), 확대(dataZoom), 저장(saveAsImage) 도구가 자동 포함된다.

#### 인자

| 인자 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `series` | `list[{name, data}]` | 조건부 | — | 시리즈 목록. `option` 지정 시 무시됨 |
| `chart_type` | string | 선택 | `"scatter"` | `scatter` \| `line` \| `bar` \| `histogram` \| `box` \| `heatmap` |
| `title` | string | 선택 | `""` | 차트 제목 |
| `x_label` | string | 선택 | `""` | X축 레이블 |
| `y_label` | string | 선택 | `""` | Y축 레이블 |
| `extra_option` | object | 선택 | `null` | ECharts option 추가 필드 (기본 option 에 deep-merge, list 는 교체) |
| `option` | object | 선택 | `null` | 완전한 ECharts option 직접 전달. **지정 시 `series`·`chart_type` 완전 무시** |

`series` 각 항목:

| 키 | 설명 |
|---|---|
| `name` | 범례·툴팁에 표시할 시리즈 이름 |
| `data` | scatter: `[[x,y], ...]` / line·bar: `[v, ...]` / box: `[[min,Q1,median,Q3,max], ...]` / heatmap: `[[x_idx,y_idx,value], ...]` |

#### 동작

1. `chart_type` + `series` 로 ECharts `option` JSON 빌드 (toolbox·dataZoom 자동 포함)
2. `extra_option` 을 깊은 병합 (list 는 교체)
3. `ToolResult.data = {kind:"chart", chart_type, title, option}` 반환
4. 프론트엔드가 ECharts 로 인터랙티브 차트 렌더링 (다크 테마 자동 연동)
5. 메시지 버블에 "📊 {title|차트유형}" 칩 추가

#### 예시 (LLM 이 호출하는 형태)

```json
{
  "name": "display_chart",
  "arguments": {
    "chart_type": "scatter",
    "series": [
      { "name": "X-Y 상관", "data": [[0.0,0.2],[1.1,0.9],[2.3,1.7]] }
    ],
    "title": "변수 X와 Y의 상관관계",
    "x_label": "변수 X",
    "y_label": "변수 Y"
  }
}
```

#### 고급 차트 타입별 예시

**시계열 Scatter** — `extra_option` 으로 x축을 time 타입으로 전환. x 값은 ISO 8601 문자열.

```json
{
  "name": "display_chart",
  "arguments": {
    "chart_type": "scatter",
    "series": [
      { "name": "측정값", "data": [["2024-01-01T09:00:00", 12.3], ["2024-01-02T09:00:00", 14.5]] }
    ],
    "title": "일별 측정값 추이",
    "x_label": "날짜",
    "y_label": "측정값",
    "extra_option": {
      "xAxis": { "type": "time" },
      "tooltip": { "trigger": "item" }
    }
  }
}
```

**ECDF** — ECharts 네이티브 타입 없음. 도구 또는 SKILL 에서 누적분포 데이터를 직접 계산한 뒤 `line` + `step: "end"` 로 전달.

```json
{
  "name": "display_chart",
  "arguments": {
    "chart_type": "line",
    "series": [
      { "name": "ECDF", "data": [1.0, 2.1, 3.4, 4.8, 6.2] }
    ],
    "title": "누적분포함수 (ECDF)",
    "x_label": "값",
    "y_label": "누적 확률",
    "extra_option": {
      "series": [{ "step": "end" }],
      "yAxis": { "min": 0, "max": 1 }
    }
  }
}
```

> data 는 정렬된 원시값 목록이 아니라 `[[값, 누적확률], ...]` 형태의 scatter 포맷으로 전달해야 정확하다.  
> 예: `[[1.0, 0.1], [2.1, 0.2], [3.4, 0.5], ...]`

**Box Plot** — `chart_type="box"` 사용. data 각 항목은 `[min, Q1, median, Q3, max]`.

```json
{
  "name": "display_chart",
  "arguments": {
    "chart_type": "box",
    "series": [
      { "name": "박스플롯", "data": [[1, 3, 5, 7, 9], [2, 4, 6, 8, 10]] }
    ],
    "title": "그룹별 분포",
    "extra_option": {
      "xAxis": { "data": ["그룹A", "그룹B"] }
    }
  }
}
```

> Python 도구 안에서는 `from agent.tools._chart_builders import build_box_series` 를 활용하면  
> 그룹별 raw 값 목록 → boxplot series + extra_option 을 자동 생성할 수 있다.

**완전 커스텀 (`option` 직접 전달)** — ECharts 가 지원하는 모든 타입(radar, candlestick, gauge, sunburst 등) 사용 가능.

```json
{
  "name": "display_chart",
  "arguments": {
    "option": {
      "title": { "text": "역량 레이더" },
      "radar": {
        "indicator": [
          { "name": "속도", "max": 100 },
          { "name": "정확도", "max": 100 },
          { "name": "안정성", "max": 100 }
        ]
      },
      "series": [
        {
          "type": "radar",
          "data": [{ "name": "현재", "value": [80, 95, 70] }]
        }
      ]
    }
  }
}
```

#### SKILL 에서 작성 방법

```markdown
## 절차
1. `add_todo` 로 수집·정제·시각화 3단계 등록
2. 수집 실행 → `complete_todo`
3. 정제 실행 → `complete_todo`
4. `display_chart(chart_type, series, title, ...)` 로 결과 시각화 → `complete_todo`
```

SKILL 에서 특수 차트를 사용할 때는 어떤 인자를 어떻게 넘길지 명시해야 LLM 이 올바르게 호출한다. 예:

```markdown
## 시각화 규칙
- 시계열 scatter: `chart_type="scatter"`, `extra_option={"xAxis": {"type": "time"}}` 필수.
  x축 값은 ISO 8601 문자열 형식으로 전달한다.
- ECDF: `chart_type="line"`, data 는 `[[값, 누적확률], ...]` scatter 포맷,
  `extra_option={"series": [{"step": "end"}], "yAxis": {"min": 0, "max": 1}}` 포함.
- 완전 커스텀: `option=` 에 ECharts option 전체를 전달하고 `series`·`chart_type` 생략.
```

---

### `display_markdown`

Markdown 산출물 파일을 아티팩트 패널에 렌더링한다.
`result/<session>/` 에 저장된 `.md` 파일을 백엔드에서 fetch 해 marked + DOMPurify + highlight.js 로 출력한다.

#### 인자

| 인자 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `source` | string | **필수** | — | 마크다운 파일 경로 (`result/...`, `workspace/...`, `assets/...`) |
| `title` | string | 선택 | `""` | 패널 헤더에 표시할 제목 |

허용 경로 프리픽스:
- `result/<session>/` — 에이전트가 생성한 산출물 (백엔드 `/result` StaticFiles mount)
- `workspace/` — 워크스페이스 산출물
- `assets/` / `build/web/assets/` — 프로젝트 정적 자산

#### 동작

1. `_resolve_image_source(source)` 로 경로를 `/result/<rest>` 형태 URL 로 정규화
2. `.md` / `.markdown` 확장자 검증 (불일치 시 `is_error=True` 반환)
3. `ToolResult.data = {kind:"markdown", src, title}` 반환
4. 프론트엔드가 `fetch(src)` 후 `renderMarkdown()` 으로 sanitized HTML 렌더링
5. 메시지 버블에 "📝 {title|파일명}" 칩 추가 — 클릭 시 패널 재오픈 (세션 복귀 후에도 동작)

#### 예시 (LLM 이 호출하는 형태)

```json
{
  "name": "display_markdown",
  "arguments": {
    "source": "result/데이터분석-a1b2c3d4/20260526-103000/report.md",
    "title": "분석 리포트"
  }
}
```

> **경로 형식**: `result/{세션제목}-{id[:8]}/{YYYYMMDD-HHmmss}/{파일명}`  
> 실제 경로는 에이전트가 `core.result_store.artifact_slot()` 으로 생성하므로,
> SKILL·AGENTS 문서에서는 `result/<session>/` 로 추상화해 표기한다.

#### SKILL 에서 작성 방법

```markdown
## 절차
1. `add_todo` 로 작성·저장·렌더링 3단계 등록
2. Markdown 본문 작성 후 `result/<session>/report.md` 에 저장 → `complete_todo`
3. `display_markdown(source="result/<session>/report.md", title="리포트")` 호출 → `complete_todo`
```

> **파일 사전 저장 필수** — `display_markdown` 을 호출하기 전에 디스크에 `.md` 파일이 존재해야 한다.
> 파일이 없으면 프론트엔드에서 "산출물 파일을 불러올 수 없습니다." 에러 UI 가 표시된다.

---

## 실행 도구

### `now`

현재 시각을 반환하는 데모 도구.

```python
# backend/agent/tools/builtin.py
@register_tool(
    description="현재 시각(로컬 타임존)을 ISO 8601 문자열로 반환한다.",
    timeout_seconds=5,
)
async def now() -> str:
    return datetime.now().isoformat(timespec="seconds")
```

**반환값**: `"2026-05-25T14:30:00"` 형태의 ISO 8601 문자열

**SKILL 에서 활용**:

```markdown
---
name: time_lookup
trigger: ["지금 시간", "현재 시각", "몇 시"]
requires_tools: ["now"]
---

`now` 도구를 한 번 호출하고 "현재 시각은 …입니다." 형식으로 한 문장으로 답한다.
```

---

## Sentinel 도구

Sentinel 도구는 **LLM 이 호출 신호를 보내면 harness 가 가로채 처리**한다.
실제 Python 함수는 `raise RuntimeError("sentinel")` 만 있으며 절대 실행되지 않는다.

---

### `add_todo`

**두 단계 이상의 작업을 시작할 때 첫 번째로 호출**하는 플래너 도구.
호출 즉시 UI 에 `TodoProgress` 체크리스트가 표시된다.

#### 인자

| 인자 | 타입 | 설명 |
|---|---|---|
| `items` | `list[{description, tool_name?}]` | 추가할 단계 목록 |

`items` 각 항목:

| 키 | 필수 | 설명 |
|---|---|---|
| `description` | **필수** | 사용자에게 표시할 한국어 단계 설명 |
| `tool_name` | 선택 | 이 단계에서 사용할 도구 이름 힌트. 해당 도구 실행 결과가 자동으로 이 todo 에 연결됨 |

#### 동작

1. harness 가 `AgentState.todo_list` 에 `TodoItem(status=PENDING)` 추가
2. `TodoUpdateEvent` 발행 → 프론트엔드 `TodoProgress` 업데이트
3. 각 `TodoItem` 에 8자리 hex `task_id` 자동 부여

#### 예시 (LLM 이 호출하는 형태)

```json
{
  "name": "add_todo",
  "arguments": {
    "items": [
      { "description": "매출 데이터 조회", "tool_name": "fetch_sales" },
      { "description": "보고서 본문 생성", "tool_name": "render_report" },
      { "description": "이메일 발송", "tool_name": "send_email" }
    ]
  }
}
```

#### SKILL 에서 작성 방법

```markdown
## 절차
1. `add_todo` 로 아래 단계들을 한 번에 등록한다.
2. `fetch_sales(date_from, date_to)` 실행 → `complete_todo`
3. `render_report(template, data)` 실행 → `complete_todo`
4. `send_email(to, subject, body)` 실행 → `complete_todo`
```

#### `tool_name` 자동 완료 연동

`tool_name` 을 지정하면 해당 도구가 실행 완료될 때 harness 가 자동으로 대응하는
`TodoItem.status` 를 `COMPLETED` 또는 `FAILED` 로 갱신한다.
`complete_todo` 를 별도로 호출하지 않아도 되므로 **간단한 순차 작업에 편리**하다.

```json
{ "description": "매출 조회", "tool_name": "fetch_sales" }
// fetch_sales 실행 후 자동으로 이 항목이 COMPLETED 로 전환됨
```

---

### `complete_todo`

**todo_list 의 단계를 완료/실패/건너뜀으로 표시**하는 플래너 도구.

#### 인자

| 인자 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `task_id` | string | **필수** | — | 완료할 단계의 `task_id`. `add_todo` 또는 `TodoUpdateEvent` 에서 획득 |
| `summary` | string | 선택 | `""` | 완료 결과 한 줄 요약. UI 의 TodoProgress 에 표시됨 |
| `status` | string | 선택 | `"completed"` | `completed` \| `failed` \| `skipped` |

#### 동작

1. harness 가 `task_id` 로 `TodoItem` 탐색 후 `status` 갱신
2. `TodoUpdateEvent` 발행 → 프론트엔드 체크리스트 갱신
3. **todo_list 전체가 terminal 상태**(completed/failed/skipped)이면 `SkillCompleteEvent` 추가 발행 → `SkillCompleteBadge` 표시

#### 예시 (LLM 이 호출하는 형태)

```json
{
  "name": "complete_todo",
  "arguments": {
    "task_id": "a3f12b9c",
    "summary": "2026-05-01~05-25 기간 매출 데이터 1,234행 조회 완료",
    "status": "completed"
  }
}
```

#### 실패 보고

```json
{
  "name": "complete_todo",
  "arguments": {
    "task_id": "a3f12b9c",
    "summary": "DB 연결 타임아웃으로 조회 실패",
    "status": "failed"
  }
}
```

---

### `ask_user`

**LLM 이 능동적으로 사용자에게 보완 질문을 던질 때** 호출한다.
슬롯 가드(도구 인자 검증 실패) 와는 별개의 경로다.

#### 인자

| 인자 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `question` | string | **필수** | — | 사용자에게 보일 자연어 질문 (한국어 한 문장) |
| `options` | `string[] \| null` | 선택 | `null` | 선택지 버튼 후보 (3~5개 권장) |
| `input_type` | string | 선택 | `"both"` | `choice` \| `text` \| `both` |

#### `input_type` 설명

| 값 | 화면 표시 | 사용자 입력 방식 |
|---|---|---|
| `"choice"` | 선택지 버튼만 | 버튼 클릭만 허용 |
| `"text"` | 질문 텍스트만 | Composer 에 직접 입력 |
| `"both"` | 선택지 버튼 + 직접 입력 힌트 | 버튼 클릭 또는 직접 입력 모두 허용 |

`options` 가 없으면 `input_type` 은 자동으로 `"text"` 로 강제된다.

#### 동작

1. harness 가 `AskUserEvent` 발행 → 프론트엔드 `AskUserCard` 표시
2. 현재 턴 중단 (`interrupted = True`)
3. `AgentState.pending_question` 에 질문 저장
4. 다음 턴 system prompt 에 `# Pending User Question` 섹션으로 재주입
5. 사용자가 답변 제출 시 LLM 이 해당 답변을 받아 작업 재개

#### 호출 기준 (orchestrator.md Case 0 기준)

```markdown
# 호출해야 하는 경우
- 요청 대상이 다의적: "데이터 보여줘" — 어떤 데이터인지 모름
- 핵심 파라미터가 선택지로 좁혀질 때: 기간(오늘/이번주/이번달), 부서, 카테고리
- 두 가지 행동 중 어느 쪽인지 단정 불가

# 호출하면 안 되는 경우
- 도구 인자 형식/누락 오류 → 슬롯 가드가 자동 처리하므로 ask_user 중복 불필요
- 같은 질문을 두 턴 연속 반복 → 모호하면 가장 합리적인 해석으로 진행
```

#### 예시 (LLM 이 호출하는 형태)

```json
{
  "name": "ask_user",
  "arguments": {
    "question": "어느 기간의 보고서를 생성할까요?",
    "options": ["오늘", "이번 주", "이번 달", "직접 입력"],
    "input_type": "both"
  }
}
```

---

### `call_sub_agent`

**오케스트레이터 전용** — 서브 에이전트에게 작업을 위임한다.
서브 에이전트에서는 이 도구가 specs 에서 제거되어 LLM 에 보이지 않는다.

#### 인자

| 인자 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `agent_name` | string | **필수** | `AGENTS/` 에 등록된 에이전트 `name` 과 정확히 일치해야 함 |
| `task` | string | **필수** | 에이전트에게 전달할 작업 지시문 (한국어 한 단락) |

#### 동작

1. `AgentSwitchEvent` 발행 → 프론트엔드 agent trail 칩 표시 (`🔄 orchestrator → coding_agent`)
2. 서브 에이전트 격리 컨텍스트 생성 (별도 messages, 별도 AgentState)
3. 서브 에이전트 turn 실행 (provider 호출 ~ `complete_subagent` 까지)
4. `AgentProgressEvent` 연속 발행 → 프론트엔드 서브 에이전트 슬롯에 실시간 표시
5. `AgentReturnEvent` 발행 → trail 칩 완료 표시 (`✓ orchestrator → coding_agent`)
6. 서브 에이전트 요약이 `tool_result` 로 오케스트레이터 컨텍스트에 주입

#### 예시 (LLM 이 호출하는 형태)

```json
{
  "name": "call_sub_agent",
  "arguments": {
    "agent_name": "coding_agent",
    "task": "backend/api/chat.py 파일의 sendMessage 함수를 분석하고 잠재적 버그를 보고해줘."
  }
}
```

#### 슬롯 부족 처리

`agent_name` 또는 `task` 가 누락된 경우 슬롯 가드가 작동해 사용자에게 자동으로 되묻는다.
이 경우 `AgentState.pending_sub_agent` 와 `pending_sub_task` 에 상태가 저장되고,
사용자가 답변하면 오케스트레이터가 재위임한다.

---

### `complete_subagent`

**서브 에이전트 전용** — 작업 완료 시 오케스트레이터에게 결과를 반환하고 서브 에이전트 turn 을 종료한다.
오케스트레이터에서는 이 도구가 specs 에서 제거되어 LLM 에 보이지 않는다.

#### 인자

| 인자 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `summary` | string | **필수** | 수행한 작업과 핵심 결과 1~3문장 |

#### 동작

1. harness 가 `summary` 를 캡처
2. `AgentReturnEvent(summary=..., todo_log=..., tool_calls_count=..., error_count=...)` 발행
3. 오케스트레이터 LLM 컨텍스트에 구조화된 `tool_result` 로 주입:
   ```
   [coding_agent 완료] 분석 완료. sendMessage 함수에서 경쟁 조건 1건 발견.
   실행 단계: 3개 (완료 2 · 실패 1)
     [✓] 함수 시그니처 분석
     [✓] 비동기 흐름 추적
     [✗] 테스트 커버리지 확인: 테스트 파일 미존재
   ```

#### AGENTS 본문에서 명시하는 방법

```markdown
## 종료 규약 (필수)
작업을 마칠 때 반드시 `complete_subagent` 도구를 호출한다.
summary 에 수행 내용과 핵심 결과를 1~3문장으로 기술한다.
```

---

## 슬롯 가드 (자동 동작, 도구가 아님)

`ask_user` 와 별개로 **모든 일반 도구 인자에 자동 적용**되는 검증 레이어.

도구 호출 시 필수 인자가 누락되거나 타입이 맞지 않으면:

1. `AskUserEvent` 자동 발행 → `AskUserCard` 표시
2. `AgentState.missing_slots` + `pending_tool` + `pending_args` 에 상태 저장
3. 사용자 답변 후 다음 턴에 `pending_args` 를 채워 자동 재호출

```python
# 도구 정의 예시 — slot_prompts 로 재질문 문구 커스터마이징
@register_tool(
    description="매출 데이터를 조회한다.",
    slot_prompts={
        "date_from": "조회 시작일(YYYY-MM-DD)을 알려주세요.",
        "date_to": "조회 종료일(YYYY-MM-DD)을 알려주세요.",
    },
)
async def fetch_sales(
    date_from: Annotated[date, "조회 시작일"],
    date_to: Annotated[date, "조회 종료일"],
) -> ToolResult:
    ...
```

`slot_prompts` 키가 파라미터 이름과 일치하면 해당 문구를 `AskUserCard` 에 표시한다.
지정하지 않으면 Pydantic 검증 에러 메시지를 그대로 사용한다.

---

## 도구 전체 목록 요약

| 도구 | 종류 | 사용 주체 | 핵심 효과 |
|---|---|---|---|
| `now` | 실행 도구 | 오케스트레이터 · 서브 에이전트 | 현재 시각 반환 |
| `display_image` | 실행 도구 | 오케스트레이터 · 서브 에이전트 | 우측 아티팩트 패널에 이미지 표시 |
| `display_chart` | 실행 도구 | 오케스트레이터 · 서브 에이전트 | 우측 아티팩트 패널에 ECharts 인터랙티브 차트 표시 |
| `display_markdown` | 실행 도구 | 오케스트레이터 · 서브 에이전트 | 우측 아티팩트 패널에 Markdown 파일 렌더링 |
| `add_todo` | Sentinel | 오케스트레이터 · 서브 에이전트 | TodoProgress 체크리스트 생성 |
| `complete_todo` | Sentinel | 오케스트레이터 · 서브 에이전트 | 단계 완료/실패 표시, SkillCompleteBadge |
| `ask_user` | Sentinel | 오케스트레이터 · 서브 에이전트 | AskUserCard 표시, 턴 중단 |
| `call_sub_agent` | Sentinel | **오케스트레이터 전용** | 서브 에이전트 위임, AgentTrail 표시 |
| `complete_subagent` | Sentinel | **서브 에이전트 전용** | 오케스트레이터에 결과 반환, 턴 종료 |
