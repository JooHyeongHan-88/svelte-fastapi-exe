# 차트 작성 가이드 (`display_chart`)

이 문서는 **SKILL·AGENT `.md` 파일을 작성하면서 `display_chart` 로 데이터를 시각화해야 하는 사람**을 위한 참고서다.
어떤 차트 유형을 쓸 수 있는지, 각 유형이 어떤 encoding 을 요구하는지, 그리고 렌더된 차트에서 사용자가 쓸 수 있는 인터랙티브 기능(brush 필터 등)이 무엇인지 정리한다.

> 한 줄 요약: 차트는 **선언적 spec(`ChartSpecV1`)** 으로 작성한다.
> 데이터는 parquet 으로 저장하고, "무엇을 어떻게 그릴지"만 JSON spec 에 담는다. 인라인 데이터(`series.data: [[x,y],...]`)는 **더 이상 지원하지 않는다.**

---

## 1. 표준 파이프라인 (3-스텝 체인)

`display_chart` 는 인라인 데이터를 받지 않는다. 항상 **parquet + spec 분리** 방식이다.

```
① save_artifact(kind="parquet", filename="data.parquet", source="$df")
       → namespace 의 polars/pandas DataFrame 을 디스크에 직렬화
② save_artifact(kind="json", filename="charts.spec.json", content=<ChartSpecV1 JSON>)
       → "어떤 컬럼을 어떻게 그릴지"만 담은 spec 저장 (데이터 인라인 금지)
③ display_chart(source="result/<session>/<ts>/charts.spec.json", title="...")
       → 백엔드가 spec + parquet 을 읽어 ECharts option 으로 변환 → charts.json 저장
```

| 항목 | 위치 | 역할 |
|---|---|---|
| **데이터** | `*.parquet` | 실제 수치. 타입 보존·압축·재사용. 여러 차트가 같은 parquet 공유 가능 |
| **스펙** | `charts.spec.json` | 차트 정의(mark + encoding + data 참조)만. 데이터 인라인 안 함 |
| **렌더 결과** | `charts.json` | 백엔드가 생성한 ECharts option. 프론트엔드는 이 파일만 fetch (작성자가 직접 다룰 일 없음) |

`display_chart` 의 `source` 는 반드시 `save_artifact` 가 반환한 `result/...charts.spec.json` 경로를 그대로 넘긴다. 파일명은 `.spec.json` 으로 끝나야 한다.

---

## 2. ChartSpecV1 스키마

```json
{
  "version": "1",
  "charts": [
    {
      "mark": "bar | line | scatter | box | histogram | heatmap | ecdf",
      "title": "차트 제목",
      "data": { "source": "<같은 폴더의 parquet 파일명>" },
      "encoding": {
        "x":     { "field": "<컬럼명>", "type": "quantitative|nominal|temporal", "title": "<라벨>", "bin": false, "aggregate": null },
        "y":     { "field": "<컬럼명>", "type": "quantitative|nominal|temporal" },
        "color": { "field": "<컬럼명>", "type": "nominal" }
      },
      "extra_option": { "...": "ECharts option 깊은 병합 (선택)" }
    }
  ]
}
```

- `charts` 는 **1개 이상**. 여러 차트를 한 배열에 담으면 패널이 반응형 그리드(페이지당 6개)로 렌더한다.
- `data.source` 는 두 가지 표기를 허용한다:
  - **단순 파일명** (`samples.parquet`) — spec 파일과 같은 폴더의 parquet.
  - **`result/...` 전체 상대 경로** (`result/<session>/<ts>/old.parquet`) — 이전 턴에 저장한 parquet 를 재사용할 때. `RESULT_DIR` 기준으로 해석되며 containment 검증을 거친다 (frozen EXE 경로 안전).
  - ⚠️ **한 spec 안에서 같은 데이터는 표기를 통일**하라. `Filter All`(scope="all") 그룹 판정이 `data.source` 문자열 동등성으로 이뤄지므로, 한 차트는 `data.parquet`·다른 차트는 `result/.../data.parquet` 로 섞으면 같은 데이터인데도 그룹이 묶이지 않는다.
- `encoding.type`:
  - `quantitative` → 수치축(value)
  - `nominal` → 범주축(category)
  - `temporal` → 시간축(time)
- `color` 채널 → 시리즈 분할(그룹별 다중 곡선/막대). **라이트박스 Legend 버튼도 이 채널이 있어야 활성화된다** — 항목 2개 이상 필요.
- `aggregate` (`count`/`mean`/`sum`/`min`/`max`) → groupby 집계.
- `extra_option` → 기본 ECharts option 에 깊은 병합. dict 는 재귀 병합, **list 는 통째 교체**.

---

## 3. 지원 차트 유형(mark)

| mark | 용도 | 필수 encoding | 선택 | 비고 |
|---|---|---|---|---|
| `bar` | 범주 비교 | x + y | color, y.aggregate | x 가 `nominal` 이면 category 축 |
| `line` | 시계열·추세 | x + y | color | x 는 보통 `quantitative`/`temporal` |
| `scatter` | 상관관계 | x + y | color | x, y 모두 `quantitative` |
| `box` | 분포·사분위 | y | x(그룹), color | y 컬럼에서 `[min,Q1,median,Q3,max]` 자동 계산 |
| `histogram` | 단일 변수 분포 | x (`bin:true`, `quantitative`) | — | 빈 10개 고정(현재) |
| `heatmap` | 2차원 밀도 | x(nominal) + y(nominal) + color(quantitative) | — | color 가 셀 값 |
| `ecdf` | 누적분포 | x (`quantitative`) | color(그룹별 곡선) | **y 불필요** — 정렬 후 누적비율(0~1) 자동 계산 |

### mark 선택 가이드

```
범주 비교        → bar
시계열·추세      → line
상관관계         → scatter
분포(사분위)     → box
분포(빈도)       → histogram
누적분포         → ecdf
2차원 밀도       → heatmap
```

### 유형별 주의점

- **histogram**: x 채널에 반드시 `"bin": true` + `"type": "quantitative"`. y 채널은 불필요(자동 count).
- **ecdf**: x(quantitative) **하나만** 지정. y 를 넣지 말 것. 내부에서 x 오름차순 정렬 후 `i/n` 누적비율을 계단선(`step:"end"`)으로 그린다. `color` 를 주면 그룹별 곡선을 겹쳐 비교한다.
- **box**: x 또는 color 를 주면 그룹별 박스 묶음. 둘 다 없으면 전체를 단일 박스로.
- **heatmap**: color.type 은 반드시 `quantitative`(셀 값). x·y 는 nominal 범주.

---

## 4. 인터랙티브 기능 (렌더된 차트에서 사용자가 쓰는 것)

모든 차트에 toolbox 가 자동 포함된다 — **brush(드래그 선택)**, **dataZoom(확대/축소)**, **restore(초기화)**, **saveAsImage(PNG 저장)**. 차트 셀을 클릭하면 라이트박스 모달로 확대된다.

### 4-1. Brush 필터 — 점 선택 후 데이터 솎아내기

사용자가 마우스로 영역을 드래그(brush)해 점을 선택하면 **Filter / Filter All** 버튼이 활성화되고, 선택한(또는 선택 안 한) 행을 데이터에서 제외해 차트를 다시 그릴 수 있다. 백엔드가 원본 parquet 에서 해당 행을 빼고 재렌더하므로, 집계 차트(box 등)는 통계가 재계산되고 ecdf 는 곡선이 다시 계산된다.

| 동작 | 효과 |
|---|---|
| **Filter** | 현재 차트에서만 선택 행 제외 후 재렌더 |
| **Filter All** | 같은 parquet 을 공유하는 **모든 차트**에서 동시에 제외 (교차 필터) |
| **Undo / Reset** | 직전 필터 취소 / 전체 원복 |

### 4-2. 어떤 mark 가 brush 필터를 지원하는가 (중요)

brush 필터는 **점이 원본 행과 1:1 대응**할 때만 의미가 있다. ECharts 의 brush 는 내부적으로 `scatter`/`bar`/`candlestick` 시리즈만 점을 선택할 수 있고 `line` 은 선택하지 못한다. 그래서 이 프로젝트는 **`line`·`ecdf` 에 보이지 않는 scatter 트윈(overlay)을 덧씌워** 선은 그대로 보이되 점 선택이 되도록 우회한다.

| mark | brush 점 필터 | 방식 |
|---|---|---|
| `scatter` | ✅ | 네이티브 |
| `line` | ✅ | 투명 scatter overlay 자동 추가 |
| `ecdf` | ✅ | 투명 scatter overlay 자동 추가 (필터 시 누적비율 재계산) |
| `bar` | ❌ | 집계 막대 — 개별 행 역추적 불가 |
| `box` | ❌(점 선택) | 집계 통계 — 단, **다른 차트의 Filter All 결과는 반영**되어 통계 재계산됨 |
| `histogram` | ❌ | 빈 집계 |
| `heatmap` | ❌ | 셀 집계 |

> **요약**: 개별 데이터 선택이 필요한 시각화(scatter·line·ecdf)는 brush 필터가 된다. 집계 차트(bar·box·histogram·heatmap)는 점을 직접 선택할 수 없지만, **같은 parquet 의 다른 차트에서 Filter All 을 누르면 함께 재집계**된다.

이 모든 동작은 자동이다. SKILL/AGENT 작성자는 **mark 와 encoding 만 올바르게 적으면** 되고, overlay·필터 로직을 위해 추가로 설정할 것은 없다.

### 4-3. 레전드 컨트롤 — 순서·색상·Hide·Filter (color 채널 차트)

`encoding.color`(seaborn 의 hue)를 준 차트는 그룹별 시리즈가 생기고, 라이트박스 툴바의 **Legend** 버튼으로 레전드를 편집할 수 있다. 레전드 항목이 2개 이상일 때만 활성화된다(단일 시리즈·히트맵·집계 box 는 비대상).

| 동작 | 효과 | 데이터 |
|---|---|---|
| **순서 변경** | 항목을 드래그해 시리즈/레전드 표시 순서 재배치 | 시각적 |
| **색상 변경** | 색상 스와치 클릭 → 해당 그룹 색 오버라이드 | 시각적 |
| **Hide(눈)** | 시리즈를 숨김/표시 토글 (`legend.selected`) | 시각적, **재집계 없음** |
| **Filter** | 항목 체크 후 위의 **Filter / Filter All** 버튼으로 그 그룹의 원본 행을 제외 | **데이터 제거 → 재집계** |

- **Hide vs Filter** 구분: Hide 는 곡선만 가렸다 다시 보일 수 있는 시각 토글이고, Filter 는 그 그룹의 행을 실제로 빼서 box·histogram 등 같은 parquet 의 다른 차트까지(Filter All) 통계가 재계산된다.
- 순서·색상·Hide·Filter 모두 brush 필터와 **하나의 Undo/Redo/Reset 스택**을 공유한다 — Undo 한 번이 종류와 무관하게 마지막 동작을 되감는다.
- 모든 상태는 `charts.json`+`charts.filter.json` 에 영속되어 새로고침·세션 재진입 후에도 복원된다.

> 작성자는 `color` 채널만 올바르게 지정하면 된다. 레전드 컨트롤 UI·영속화는 자동이다.

---

## 5. SKILL/AGENT 본문 작성 패턴

차트를 그리는 작업은 보통 `add_todo` 로 plan 을 세우고 순차 실행한다. 표준 골격:

```markdown
## 절차
1. `add_todo` 로 `데이터 산출` → `parquet 직렬화` → `spec 작성·표시` 3단계 등록
2. `exec_code` / `call_function` 으로 DataFrame 산출 → `complete_todo`
3. `save_artifact(kind="parquet", filename="samples.parquet", source="$samples_df")` → `complete_todo`
4. `save_artifact(kind="json", filename="charts.spec.json", content='<ChartSpecV1>')`
   이어서 `display_chart(source="result/<session>/<ts>/charts.spec.json", title="...")` → `complete_todo`
```

### 예시 — 단일 scatter

```json
{
  "version": "1",
  "charts": [
    {
      "mark": "scatter",
      "title": "X-Y 상관관계",
      "data": { "source": "samples.parquet" },
      "encoding": {
        "x": { "field": "x", "type": "quantitative", "title": "변수 X" },
        "y": { "field": "y", "type": "quantitative", "title": "변수 Y" }
      }
    }
  ]
}
```

### 예시 — 여러 차트 한 번에 (그리드 비교)

```json
{
  "version": "1",
  "charts": [
    { "mark": "bar",  "title": "지표 요약",
      "data": { "source": "stats.parquet" },
      "encoding": { "x": { "field": "metric", "type": "nominal" },
                    "y": { "field": "value",  "type": "quantitative" } } },
    { "mark": "line", "title": "값 추세",
      "data": { "source": "samples.parquet" },
      "encoding": { "x": { "field": "idx",   "type": "quantitative" },
                    "y": { "field": "value", "type": "quantitative" } } },
    { "mark": "ecdf", "title": "값 누적분포",
      "data": { "source": "samples.parquet" },
      "encoding": { "x": { "field": "value", "type": "quantitative", "title": "값" } } }
  ]
}
```

> line·ecdf 차트는 위처럼 평범하게 적으면 brush 필터가 자동으로 활성화된다. 별도 overlay 설정 불필요.

### 예시 — 그룹별 산점도 + 누적분포 (color 채널 → 레전드 컨트롤 활성)

`encoding.color` 를 주면 그룹별 시리즈가 생기고, 라이트박스에서 Legend 버튼으로 순서·색상·Hide·Filter 를 제어할 수 있다.

```json
{
  "version": "1",
  "charts": [
    {
      "mark": "scatter",
      "title": "그룹별 산점도",
      "data": { "source": "samples.parquet" },
      "encoding": {
        "x":     { "field": "value",         "type": "quantitative", "title": "값" },
        "y":     { "field": "anomaly_score", "type": "quantitative", "title": "이상치" },
        "color": { "field": "group",         "type": "nominal",      "title": "그룹" }
      }
    },
    {
      "mark": "ecdf",
      "title": "그룹별 누적분포",
      "data": { "source": "samples.parquet" },
      "encoding": {
        "x":     { "field": "value", "type": "quantitative", "title": "값" },
        "color": { "field": "group", "type": "nominal" }
      }
    }
  ]
}
```

> scatter 는 brush 점 필터 + 레전드 Filter 둘 다 지원. ecdf 는 line+overlay 경로라 동일하게 동작한다.

---

## 6. 흔한 실수 체크리스트

- ❌ `series.data` 에 좌표를 인라인으로 넣음 → **지원 안 함.** parquet + spec 으로 분리.
- ❌ `display_chart(source=...)` 에 parquet 경로를 넘김 → `.spec.json` 파일 경로를 넘겨야 한다.
- ❌ ecdf 에 y 채널을 지정 → y 불필요. x(quantitative)만.
- ❌ histogram 에 `bin:true` 누락 → "histogram 은 x.bin=true 가 필요하다" 에러.
- ❌ heatmap 의 color.type 을 nominal 로 → color 는 `quantitative` 여야 셀 값이 된다.
- ❌ spec 을 저장하기 전에 parquet 을 안 만듦 → 렌더 시 "parquet 파일을 찾을 수 없다".
- ✅ bar·box 에서 brush 점 필터가 안 된다고 당황하지 말 것 — **설계상 집계 차트는 점 필터 비대상**(Filter All 의 교차 재집계는 받음).
- ❌ Legend 버튼이 비활성 → `encoding.color` 채널이 없거나 그룹(시리즈)이 1개 이하. `color.field` 가 있고 데이터에 실제로 2종 이상의 값이 있어야 활성화된다.
- ❌ heatmap 의 `color` 를 레전드 컨트롤에 쓰려 함 → heatmap 의 color 는 셀 수치값(`quantitative`)이라 시리즈 분할이 아님. 레전드 컨트롤 비대상.
- ❌ 레전드 Filter 로 숨긴 그룹이 Undo 후에도 유지됨 → Hide(눈 토글)와 Filter(데이터 제외)는 다른 동작. Hide 는 ECharts `legend.selected` 시각 토글, Filter 는 parquet 행 제외 재집계.

---

## 7. 관련 문서

- [builtin-tools.md](builtin-tools.md) — `display_chart` 를 포함한 전체 내장 도구 인자 레퍼런스
- [skills.md](skills.md) / [agents.md](agents.md) — SKILL·AGENT Front Matter 와 본문 작성법
- `backend/agent/runtime/chart_spec.py` — ChartSpecV1 Pydantic 모델(스키마 단일 진실)
- `backend/agent/runtime/chart_renderer.py` — mark 별 렌더러·brush overlay 구현·legend 적용(`_apply_legend_config`)·레전드→행 역추적(`resolve_legend_row_ids`)
- `backend/agent/runtime/chart_filter_store.py` — ViewState undo/redo 스택 (exclude·legend 통합 v2 스키마)
- `backend/api/chart.py` — `/api/chart/filter` 엔드포인트 (exclude·exclude_legend·set_legend·undo·redo·reset)
