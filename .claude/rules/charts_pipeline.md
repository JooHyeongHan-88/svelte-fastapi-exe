# 차트 인터랙션 파이프라인

`backend_architecture.md` 에서 발췌. `display_chart` 호출 이후의 인터랙티브 필터링·
레전드 편집 파이프라인을 다룬다. 차트 스펙 정의·mark 별 encoding 은
[docs/guides/charts.md](../docs/guides/charts.md) 참고.

---

## 산출물 파일 구조 (spec 폴더 기준)

```
result/<session>/<ts>/
  charts.spec.json    ChartSpecV1 선언 (mark·encoding·data.source)
  *.parquet           실제 데이터
  charts.json         render_spec_to_echarts() 결과 - 프론트가 fetch
  charts.filter.json  ViewState 사이드카 - exclude·legend 통합 undo/redo 스택 (v2)
```

---

## ViewState 스택 (`backend/agent/charts/chart_filter_store.py`)

v2 스키마로 **필터(exclude)와 레전드 오버라이드(legend)를 단일 undo/redo 스택**에 통합.
cursor가 가리키는 `ViewSnapshot`이 현재 상태.

| 전이 함수 | 효과 |
|---|---|
| `apply_exclude(state, chart_index, row_ids, scope, chart_sources)` | brush/레전드 Filter -> 행 제외 push (legend carry) |
| `apply_legend(state, chart_index, *, order, colors, hidden, scope, ...)` | 순서·색상·Hide -> legend 갱신 push (exclude carry) |
| `reset(state)` | 빈 스냅샷 push (undo 로 복구 가능) |
| `undo(state)` / `redo(state)` | cursor 이동만 - 양쪽 동작 무관하게 되감음 |

---

## `/api/chart/filter` 엔드포인트 (`backend/api/chart.py`)

| action | 동작 |
|---|---|
| `exclude` | brush 선택 행 제외 |
| `exclude_legend` | 레전드 이름 -> `color.field` 값으로 행 역추적 -> 기존 exclude funnel |
| `set_legend` | order·colors·hidden 오버라이드 저장 (재집계 없음) |
| `undo` / `redo` / `reset` | ViewState cursor 조작 |

응답: `{ items, can_undo, can_redo }` - `items`로 `charts.json`도 덮어씌워 재진입 일관성 보장.

---

## 렌더러 (`backend/agent/charts/chart_renderer.py`)

`render_spec_to_echarts(spec, base_dir, exclude_by_chart=None, legend_by_chart=None)`

- `legend_by_chart`: 차트 인덱스 -> `{"order":[name], "colors":{name:hex}, "hidden":[name]}`
- `_apply_legend_config`: order(line+overlay 트윈 그룹 인접 유지)·colors(itemStyle+lineStyle)·hidden(`legend.selected`) 적용
- `resolve_legend_row_ids(chart, base_dir, legend_values)`: color.field 컬럼 기반 행 역추적 (레전드 Filter -> exclude 환원)

### 관용 파싱 + 레전드 보정 (R8)

실 LLM 의 spec 근사 오류를 렌더러 레벨에서 흡수한다:

| 경로 | 처리 |
|---|---|
| `encoding.type: "normal"` 등 근사 표기 | `chart_spec.py` field_validator(mode="before") 가 alias 정규화 (`normal`->nominal, `avg`->mean 등, 대소문자 무관). 매핑 밖 값은 ValidationError |
| histogram + `encoding.color` | `_render_histogram` 이 그룹별 시리즈로 분리. 빈 경계는 전체 범위에서 1회 계산해 그룹 공유 |
| `extra_option.legend.data` 임의 라벨 | deep-merge 후 `_restore_mismatched_legend` 가 실존 시리즈 이름과 교집합만 유지, 전부 어긋나면 시리즈 이름으로 복원 |

`display_chart` ValidationError 회신은 최대 3건 포함(`_SPEC_ERROR_DETAIL_LIMIT`) - 오류 하나 고칠 때마다 재호출하는 낭비 방지.

테스트: `backend/tests/test_chart_renderer.py` · `backend/tests/test_display_chart_spec.py`
