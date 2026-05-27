---
name: data_summary
description: 숫자 데이터의 요약 통계(평균·중앙값·표준편차 등)를 계산하고 바 차트로 시각화한다
trigger:
  - 데이터 요약
  - 요약 통계
  - summary stats
  - 통계 계산
priority: 5
api_refs:
  - scripts.stats.compute_summary_stats
---

# 요약 통계 분석 작업 가이드

사용자가 숫자 데이터의 통계량을 요청할 때 따르는 표준 절차다.
`backend/scripts/stats.py` 의 `compute_summary_stats` 함수를 호출해 결정론적으로
계산하고, 결과를 차트로 시각화한다.

## 단계

1. **작업 계획 등록** — `add_todo` 로 3단계 plan 을 등록한다:
   `샘플 데이터 생성` → `통계량 계산` → `시각화 및 보고`.
2. **샘플 데이터 생성** — `exec_code` 로 분석 대상 숫자 리스트를 정의해 세션
   namespace 에 저장한다. 예시:
   ```python
   samples = [12.3, 14.5, 11.8, 13.9, 15.2, 12.7, ...]
   ```
   완료 후 `complete_todo` 로 1단계 마킹.
3. **통계량 계산** — `call_function(qualified_name="scripts.stats.compute_summary_stats",
   kwargs={"data": "$samples"}, store_as="stats")` 로 함수를 호출한다. `$samples` 는
   namespace 의 변수를 참조하는 문법이며 harness 가 실행 직전 실제 값으로 치환한다.
   완료 후 `complete_todo` 로 2단계 마킹.
4. **개별 지표 추출** — 필요 시 `eval_expression(expression="stats['mean']", store_as="avg")`
   로 단일 값을 namespace 에 분리 저장한다.
5. **시각화 및 보고** — `display_chart(chart_type="bar", series=[{name, data}],
   title, x_label, y_label)` 로 통계량 막대 차트를 표시한다. `series.data` 는 stats
   딕셔너리의 각 키-값 쌍을 변환한 리스트. 완료 후 `complete_todo` 로 3단계 마킹.
6. **자연어 최종 보고** — 평균·표준편차의 일반적 해석(예: "양수 방향 분포", "낮은 변동성")
   을 1-2문장으로 정리한다.

## 주의

- 통계량 값을 응답 본문에 박지 말 것 — 함수 실행 결과는 namespace 에 저장되어 있고,
  사용자는 우측 차트 패널에서 확인할 수 있다. 자연어 응답은 일반화된 표현만 사용한다.
- `call_function` 의 `kwargs` 에 namespace 변수를 참조할 땐 반드시 `"$varname"` 문자열
  형식. 직접 객체를 넘기지 않는다.
