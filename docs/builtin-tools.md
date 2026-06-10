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

이미지(들)를 아티팩트 패널에 표시한다. **한 번의 호출에 여러 이미지를 list 로 전달**하면
패널이 세로 갤러리 + 무한 스크롤 + N/M 카운터로 자동 렌더링한다. 단일 이미지도
1-element list 로 전달한다.

#### 인자

| 인자 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `images` | `list[ImageItem]` | **필수** | 이미지 항목 리스트. 빈 list 면 에러 반환 |

`ImageItem` 구조:

| 키 | 타입 | 필수 | 기본값 | 설명 |
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

1. 각 `images[i].source` 를 정규화해 `items[i] = {src, alt, caption}` 로 변환
2. `ToolResult.data = {kind:"image", items:[...]}` 반환
3. 한 항목이라도 경로 검증 실패 시 전체 호출이 `is_error=True` 로 실패하고 인덱스를 메시지에 포함
4. 프론트엔드: 패널 갤러리 6장씩 lazy load + IntersectionObserver 무한 스크롤, 클릭 시 리사이즈 가능한 라이트박스 모달 오픈
5. 메시지 버블에 "🖼️ 이미지 N장" 칩 추가 — 클릭 시 패널 재오픈

#### 예시 — 단일 이미지

```json
{
  "name": "display_image",
  "arguments": {
    "images": [
      {
        "source": "build/web/assets/favicon.svg",
        "alt": "앱 아이콘",
        "caption": "현재 사용 중인 앱 로고"
      }
    ]
  }
}
```

#### 예시 — 다중 이미지 갤러리

```json
{
  "name": "display_image",
  "arguments": {
    "images": [
      {"source": "result/<session>/<ts>/fig1.png", "alt": "수율 추이"},
      {"source": "result/<session>/<ts>/fig2.png", "alt": "장비별 비교"},
      {"source": "result/<session>/<ts>/fig3.png", "alt": "결함 맵"}
    ]
  }
}
```

#### SKILL 에서 활용

```markdown
## 절차
1. `now` 도구로 현재 시각 조회
2. `display_image(images=[{source: "build/web/assets/favicon.svg", alt: "앱 아이콘"}])` 호출
3. "현재 시각은 …입니다." 형식으로 응답
```

---

### `display_chart`

`save_artifact` 로 저장한 **선언적 차트 spec(`ChartSpecV1`)** 파일을 읽어, 같은 폴더의 parquet
데이터를 로드해 ECharts 인터랙티브 차트(들)를 아티팩트 패널에 표시한다. spec 의 `charts` 배열에
여러 차트를 담으면 패널이 반응형 그리드(최대 6개/페이지) + prev/next 페이지네이션으로 렌더링한다.
드래그 선택(brush), 확대(dataZoom), 초기화(restore), 저장(saveAsImage) 도구가 각 차트에 자동 포함된다.

> **인라인 데이터(`series.data: [[x,y],...]`)는 더 이상 지원하지 않는다.** 항상 parquet + spec 분리 방식이다.
> 차트 유형·encoding·brush 필터 등 작성 전반은 → **[charts.md](charts.md)** (전용 가이드).

#### 인자

| 인자 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `source` | string | **필수** | — | `save_artifact` 가 반환한 `result/...charts.spec.json` 경로. 파일명은 `.spec.json` 으로 끝나야 함 |
| `title` | string | 선택 | `""` | 아티팩트 패널 헤더에 표시할 제목 |

#### 표준 체인 (parquet + spec)

```
① save_artifact(kind="parquet", filename="data.parquet", source="$df")
② save_artifact(kind="json", filename="charts.spec.json", content=<ChartSpecV1 JSON>)
③ display_chart(source="result/<session>/<ts>/charts.spec.json", title="...")
```

`ChartSpecV1` 스키마 요약:

```json
{
  "version": "1",
  "charts": [
    {
      "mark": "bar | line | scatter | box | histogram | heatmap | ecdf",
      "title": "차트 제목",
      "data": { "source": "<같은 폴더의 parquet 파일명>" },
      "encoding": {
        "x":     { "field": "<컬럼명>", "type": "quantitative|nominal|temporal", "title": "<라벨>" },
        "y":     { "field": "<컬럼명>", "type": "quantitative" },
        "color": { "field": "<컬럼명>", "type": "nominal" }
      },
      "extra_option": { "...": "ECharts option 깊은 병합 (선택)" }
    }
  ]
}
```

#### 동작

1. `source` 경로(`result/...`, `.spec.json`)와 존재 여부를 검증 → 실패 시 `is_error=True`
2. spec 을 `ChartSpecV1` 로 파싱·검증 (실패 시 첫 오류 위치 회신)
3. `render_spec_to_echarts()` 가 각 차트의 parquet 를 읽어 ECharts option 리스트 생성 (mark·encoding 비호환 시 에러)
4. 결과를 같은 폴더의 `charts.json` 으로 저장 (spec 원본은 인터랙티브 재처리를 위해 보존)
5. `ToolResult.data = {kind:"chart", src:"/result/.../charts.json", spec:"result/.../charts.spec.json", title}` 반환
6. 프론트엔드: 패널 반응형 그리드, 페이지당 최대 6개, 셀 클릭 시 라이트박스 모달. brush 선택 후 Filter/Filter All 로 행 제외 재렌더
7. 메시지 버블에 "📊 차트 N개" 칩 추가 — `spec` 경로가 칩 payload 에 영속되어 세션 재진입 후에도 필터 가능

#### 예시 — 단일 scatter spec

```json
{
  "version": "1",
  "charts": [
    {
      "mark": "scatter",
      "title": "변수 X와 Y의 상관관계",
      "data": { "source": "samples.parquet" },
      "encoding": {
        "x": { "field": "x", "type": "quantitative", "title": "변수 X" },
        "y": { "field": "y", "type": "quantitative", "title": "변수 Y" }
      }
    }
  ]
}
```

저장 후 호출:

```json
{
  "name": "display_chart",
  "arguments": {
    "source": "result/데이터분석-a1b2c3d4/20260530-101500/charts.spec.json",
    "title": "상관 분석"
  }
}
```

#### SKILL 에서 작성 방법

```markdown
## 절차
1. `add_todo` 로 `데이터 산출` → `parquet 직렬화` → `spec 작성·표시` 3단계 등록
2. `exec_code` / `call_function` 으로 DataFrame 산출 → `complete_todo`
3. `save_artifact(kind="parquet", filename="samples.parquet", source="$samples_df")` → `complete_todo`
4. `save_artifact(kind="json", filename="charts.spec.json", content='<ChartSpecV1>')`
   이어서 `display_chart(source="result/<session>/<ts>/charts.spec.json")` → `complete_todo`
```

> mark 별 필수 encoding, brush 필터가 되는 차트(scatter·line·ecdf) vs 집계 차트(bar·box·histogram·heatmap),
> 그룹별 곡선(color 채널), 흔한 실수 체크리스트는 **[charts.md](charts.md)** 에 정리돼 있다.

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

## 산출물 재발견·재사용 도구

`save_artifact` 가 쓰기 방향(namespace → 디스크)이라면, 아래 두 도구는 읽기 방향이다 —
과거 턴/세션에 저장한 산출물을 다시 작업 입력으로 끌어온다. 모든 경로 해석은
`core.result_store.resolve_result_path` 로 일원화되어 frozen EXE 에서도 CWD 와 무관하게 동작한다.

### `list_artifacts`

현재 세션의 산출물 목록을 최신순으로 조회한다 (세션 rename 으로 폴더가 여러 개여도 cid8 로 전부 병합).

| 인자 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `kind` | `"all"\|"markdown"\|"json"\|"text"\|"parquet"\|"binary"` | 선택 | `"all"` | 필터링할 산출물 종류 |
| `limit` | int | 선택 | `20` | 반환 최대 개수 (최신순) |

- parquet 은 pyarrow footer 만 읽어 `rows×cols` 를 요약 (데이터 본문 미로드).
- 파생물(`charts.json`/`charts.filter.json`)·내부 폴더(`_namespace`)는 제외.
- 반환 `data={"artifacts":[{path, kind, size, filename, ts, rows?, columns?}]}`.

### `load_artifact`

`result/...` 경로의 파일을 읽어 세션 namespace 변수로 복원한다 (save_artifact 의 역방향).

| 인자 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `path` | string | **필수** | — | `result/...` 형식 산출물 경로 (list_artifacts/save_artifact 가 반환) |
| `store_as` | string | 조건부 | `""` | namespace 변수 이름. parquet/바이너리는 필수, json/텍스트는 생략 시 내용만 반환 |

확장자별 동작: `.parquet`→polars DataFrame, `.json`→파싱된 객체, `.md/.txt`→문자열,
바이너리(`.png/.svg/.pdf/.pptx/.xlsx`)→bytes. 실패 시 "list_artifacts 로 확인" 유도 에러.

**표준 체인**: `list_artifacts` → `load_artifact(path, store_as='df')` → `exec_code`/`call_function` 에서 `df` 참조.

> 단순 재표시(차트·마크다운·이미지)는 load 없이 `display_*` 에 경로를 직접 전달하면 된다.

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
| `list_artifacts` | 실행 도구 | 오케스트레이터 · 서브 에이전트 | 현재 세션 산출물 목록 조회 (재발견) |
| `load_artifact` | 실행 도구 | 오케스트레이터 · 서브 에이전트 | 산출물 파일을 namespace 로 로드 (역방향 브리지) |
| `display_image` | 실행 도구 | 오케스트레이터 · 서브 에이전트 | 우측 아티팩트 패널에 이미지 표시 |
| `display_chart` | 실행 도구 | 오케스트레이터 · 서브 에이전트 | 우측 아티팩트 패널에 ECharts 인터랙티브 차트 표시 |
| `display_markdown` | 실행 도구 | 오케스트레이터 · 서브 에이전트 | 우측 아티팩트 패널에 Markdown 파일 렌더링 |
| `add_todo` | Sentinel | 오케스트레이터 · 서브 에이전트 | TodoProgress 체크리스트 생성 |
| `complete_todo` | Sentinel | 오케스트레이터 · 서브 에이전트 | 단계 완료/실패 표시, SkillCompleteBadge |
| `ask_user` | Sentinel | 오케스트레이터 · 서브 에이전트 | AskUserCard 표시, 턴 중단 |
| `call_sub_agent` | Sentinel | **오케스트레이터 전용** | 서브 에이전트 위임, AgentTrail 표시 |
| `complete_subagent` | Sentinel | **서브 에이전트 전용** | 오케스트레이터에 결과 반환, 턴 종료 |

---

## 라이브러리 런타임 메타 도구 (api_refs 활성 시 자동 노출)

SKILL/AGENT 의 `api_refs` 가 비어있지 않으면 harness 가 다음 7개 도구를 specs 에 자동 주입한다. 자세한 사용법과 보안 모델은 [library-runtime.md](library-runtime.md) 참고.

| 도구 | 인자 | 효과 |
|---|---|---|
| `inspect_callable` | `qualified_name: str` | 라이브러리 함수/클래스의 시그니처 + docstring 반환 |
| `list_module_members` | `module_path: str` | 모듈의 public 멤버 목록과 한줄 docstring |
| `call_function` | `qualified_name: str`, `kwargs: dict`, `store_as: str` | 함수 실행 후 결과를 세션 namespace 에 변수로 저장. `kwargs` 값에 `"$varname"` 이 있으면 namespace 변수로 자동 치환 |
| `eval_expression` | `expression: str`, `store_as: str = ""` | namespace 변수 + 안전 builtins 환경에서 짧은 식 평가. `store_as` 가 있으면 결과 저장 |
| `exec_code` | `code: str` | 다중 statement Python 코드 실행 (import / 할당 / for / 함수 정의). stdout 캡쳐 + 신규 변수 namespace 자동 저장 |
| `list_namespace` | (없음) | 세션 namespace 의 모든 변수 한 줄씩 요약 |
| `describe_variable` | `name: str` | 변수 타입별 상세 (DataFrame head, ndarray shape 등) |
| `delete_variable` | `name: str` | namespace 변수 영구 삭제 (memory + disk 모두) |

**자동 노출 조건**:
- 활성 SKILL 중 하나라도 `api_refs` 가 있으면 오케스트레이터에 자동 노출.
- 서브 에이전트의 `api_refs` 또는 학습 SKILL 의 `api_refs` 가 있으면 서브 에이전트에 노출 (화이트리스트 `tools` 와 무관).
