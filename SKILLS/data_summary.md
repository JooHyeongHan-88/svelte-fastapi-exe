---
name: data_summary
description: 숫자 데이터의 요약 통계(평균·중앙값·표준편차 등)를 계산하고 선언적 차트 spec 으로 시각화한다
trigger:
  - 데이터 요약
  - 요약 통계
  - summary stats
  - 통계 계산
priority: 5
api_refs:
  - scripts.stats_df.compute_summary_stats_df
---

# 요약 통계 분석 작업 가이드

사용자가 숫자 데이터의 통계량을 요청할 때 따르는 표준 절차다.
`backend/scripts/stats_df.py` 의 `compute_summary_stats_df` 를 호출해 polars
DataFrame 으로 결정론적으로 계산하고, parquet + 차트 spec 으로 분리해 시각화한다.

## 디자인 원칙 (필독)

- **데이터는 parquet** — 항상 `save_artifact(kind="parquet")` 로 디스크 직렬화 (타입 보존, 압축, 재사용)
- **스펙은 JSON** — `charts.spec.json` 은 차트 정의(어떤 컬럼을 어떻게 그릴지)만 담는다. 데이터를 인라인하지 않는다
- **렌더는 백엔드** — `display_chart` 가 spec + parquet 을 읽어 ECharts option 으로 변환해 같은 폴더의 `charts.json` 에 저장. 프론트엔드는 이 파일만 fetch

## 단계

1. **작업 계획 등록** — `add_todo` 로 3단계 plan 을 등록한다:
   `샘플+통계 산출` → `parquet 직렬화` → `spec 작성·표시`.

2. **샘플 데이터 + 통계 계산** — `exec_code` 로 polars DataFrame 을 생성하고 통계 함수를 호출한다.
   ```python
   import polars as pl
   samples_df = pl.DataFrame({
       "idx": list(range(30)),
       "value": [12.3, 14.5, 11.8, ...],
   })
   value_list = samples_df["value"].to_list()  # call_function 의 list 인자용
   ```
   이어서:
   ```
   call_function(qualified_name="scripts.stats_df.compute_summary_stats_df",
                 kwargs={"data": "$value_list"}, store_as="stats_df")
   ```
   `$value_list` 는 namespace 의 변수를 참조하는 문법이며 harness 가 실행 직전 실제 값으로 치환한다.
   필요 시 `eval_expression(expression="stats_df.filter(pl.col('metric')=='mean')['value'][0]", store_as="avg")`
   로 단일 지표를 추출 가능. 완료 후 `complete_todo` 로 1단계 마킹.

3. **parquet 직렬화** — 시각화 대상 DataFrame 을 디스크에 저장한다.
   `save_artifact` 의 새로운 `kind="parquet"` 분기는 `source="$varname"` 으로 namespace 의 DataFrame 을 받아 polars `write_parquet` 한다 (pandas DataFrame 도 자동 변환).
   ```
   save_artifact(kind="parquet", filename="samples.parquet", source="$samples_df")
   save_artifact(kind="parquet", filename="stats.parquet",   source="$stats_df")
   ```
   완료 후 `complete_todo` 로 2단계 마킹.

4. **차트 spec 작성 + 표시** — 선언적 spec 을 JSON 으로 저장하고 `display_chart` 를 호출한다.
   ```
   save_artifact(kind="json", filename="charts.spec.json",
                 content='{"version":"1","charts":[
                   {"mark":"bar","title":"통계량 요약",
                    "data":{"source":"stats.parquet"},
                    "encoding":{"x":{"field":"metric","type":"nominal","title":"지표"},
                                "y":{"field":"value","type":"quantitative","title":"값"}}}
                 ]}')
   display_chart(source="result/<session>/<ts>/charts.spec.json",
                 title="통계량 요약 차트")
   ```
   완료 후 `complete_todo` 로 3단계 마킹.

## ChartSpecV1 스키마 요약

```json
{
  "version": "1",
  "charts": [
    {
      "mark": "bar | line | scatter | box | histogram | heatmap | ecdf",
      "title": "차트 제목",
      "data": {"source": "<같은 폴더의 parquet 파일명>"},
      "encoding": {
        "x":     {"field": "<컬럼명>", "type": "quantitative|nominal|temporal", "title": "<라벨>", "bin": false, "aggregate": null},
        "y":     {"field": "<컬럼명>", "type": "quantitative|nominal|temporal"},
        "color": {"field": "<컬럼명>", "type": "nominal"}
      },
      "extra_option": { /* ECharts option 깊은 병합 (선택) */ }
    }
  ]
}
```

- **mark 선택 가이드**: 범주 비교 → bar, 시계열 → line, 상관관계 → scatter, 분포 → box/histogram, 누적분포 → ecdf, 2차원 밀도 → heatmap
- **ecdf**: x(quantitative) 하나만 지정하면 정렬 후 누적비율(0~1) 계단선을 그린다. y 불필요. color 로 그룹별 곡선 비교.
- **encoding type**: `quantitative` 는 수치축(value), `nominal` 은 범주축(category), `temporal` 은 시간축(time)
- **color 채널**: 시리즈 분할용 (예: 그룹별 다중 시리즈 bar)
- **aggregate**: 선택적 집계 (`count`/`mean`/`sum`/`min`/`max`) — groupby 동작
- **histogram**: x 채널에 `"bin": true` + `"type": "quantitative"` 필수

## 주의

- 통계량 값을 응답 본문에 박지 말 것 — namespace 와 parquet 파일에 있고, 사용자는 우측 차트 패널에서 확인한다. 자연어 응답은 일반화된 표현만 사용.
- `call_function` 의 `kwargs` 에 namespace 변수를 참조할 땐 반드시 `"$varname"` 문자열 형식. 객체를 직접 넘기지 않는다.
- 인라인 데이터(`series.data: [[x,y],...]` 등) 옛 포맷은 더 이상 지원하지 않는다. 항상 parquet + spec 분리.
