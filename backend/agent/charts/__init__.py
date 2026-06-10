"""차트 산출물 파이프라인.

`display_chart` 가 선언한 spec 을 데이터와 함께 렌더하고, 렌더 후의
인터랙티브 필터·레전드 편집 상태를 관리한다. 코드 실행 런타임
(`agent/runtime/`)과 달리 라이브러리 실행과 무관한 산출물 관심사다.

구성:
    - chart_spec: ChartSpecV1 선언 모델 (mark·encoding·data.source).
    - chart_renderer: spec + parquet → ECharts option 렌더링.
    - chart_filter_store: ViewState 사이드카 — exclude·legend 통합 undo/redo 스택.

산출물 파일 구조 (result/<session>/<ts>/)::

    charts.spec.json     ChartSpecV1 선언
    *.parquet            실제 데이터
    charts.json          렌더 결과 — 프론트가 fetch
    charts.filter.json   ViewState 사이드카

이 패키지의 공개 API 는 backend/agent/tools/visualize.py 와
backend/api/chart.py 에서 사용된다.
"""
