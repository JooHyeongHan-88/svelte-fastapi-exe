"""차트 데이터 준비 헬퍼 — @register_tool 함수에서 display_chart 인자를 준비할 때 사용한다.

이 모듈의 함수들은 LLM 에 직접 노출되지 않으며 (@register_tool 없음),
사내 API 도구가 display_chart 를 호출하기 전에 데이터를 변환하기 위한 순수 파이썬 유틸리티다.

사용 예::

    from agent.tools._chart_builders import build_heatmap_series

    series, extra = build_heatmap_series(corr_matrix, row_labels, col_labels, "상관계수")
    result = await display_chart(
        series=series,
        chart_type="heatmap",
        title="변수 간 상관관계",
        extra_option=extra,
    )
"""

from __future__ import annotations

import statistics
from typing import Any


def build_heatmap_series(
    matrix: list[list[float]],
    row_labels: list[str],
    col_labels: list[str],
    series_name: str = "값",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """2D 값 행렬을 heatmap series + extra_option 형태로 변환한다.

    Args:
        matrix: row × col 부동소수점 행렬. ``matrix[r][c]`` 가 ``(col_labels[c], row_labels[r])`` 위치의 값.
        row_labels: y축(행) 레이블. ``len(row_labels) == len(matrix)``.
        col_labels: x축(열) 레이블. ``len(col_labels) == len(matrix[0])``.
        series_name: 범례·툴팁에 표시할 시리즈명.

    Returns:
        ``(series, extra_option)`` 튜플.
        ``display_chart(series=series, chart_type="heatmap", extra_option=extra_option)`` 에 전달한다.
    """
    data = [
        [col_idx, row_idx, row[col_idx]]
        for row_idx, row in enumerate(matrix)
        for col_idx in range(len(row))
    ]
    series: list[dict[str, Any]] = [{"name": series_name, "data": data}]
    extra_option: dict[str, Any] = {
        "xAxis": {"data": col_labels},
        "yAxis": {"data": row_labels},
    }
    return series, extra_option


def build_histogram_series(
    values: list[float],
    bins: int = 10,
    series_name: str = "빈도",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """수치 목록을 균등 구간 히스토그램 시리즈로 변환한다.

    Args:
        values: 집계할 수치 목록.
        bins: 구간 개수. 기본 10.
        series_name: 범례에 표시할 시리즈명.

    Returns:
        ``(series, extra_option)`` 튜플.
        ``display_chart(series=series, chart_type="histogram", extra_option=extra_option)`` 에 전달한다.
    """
    if not values:
        return [{"name": series_name, "data": []}], {}

    min_val = min(values)
    max_val = max(values)

    if min_val == max_val:
        return (
            [{"name": series_name, "data": [[str(min_val), len(values)]]}],
            {"xAxis": {"type": "category"}},
        )

    bin_width = (max_val - min_val) / bins
    counts = [0] * bins
    for v in values:
        idx = min(int((v - min_val) / bin_width), bins - 1)
        counts[idx] += 1

    labels = [
        f"{min_val + i * bin_width:.3g}~{min_val + (i + 1) * bin_width:.3g}"
        for i in range(bins)
    ]
    series: list[dict[str, Any]] = [
        {"name": series_name, "data": list(zip(labels, counts))}
    ]
    extra_option: dict[str, Any] = {"xAxis": {"type": "category"}}
    return series, extra_option


def build_box_series(
    groups: dict[str, list[float]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """그룹별 수치 목록을 boxplot 시리즈로 변환한다.

    min·Q1·median·Q3·max 를 자동 계산한다.

    Args:
        groups: ``{그룹명: [값, ...]}`` 딕셔너리.

    Returns:
        ``(series, extra_option)`` 튜플.
        ``display_chart(series=series, chart_type="box", extra_option=extra_option)`` 에 전달한다.
    """
    names = list(groups.keys())
    box_data: list[list[float]] = []

    for name in names:
        vals = sorted(groups[name])
        if not vals:
            box_data.append([0.0, 0.0, 0.0, 0.0, 0.0])
            continue
        n = len(vals)
        q1 = float(vals[n // 4])
        med = float(statistics.median(vals))
        q3 = float(vals[min(3 * n // 4, n - 1)])
        box_data.append([float(vals[0]), q1, med, q3, float(vals[-1])])

    series: list[dict[str, Any]] = [{"name": "분포", "data": box_data}]
    extra_option: dict[str, Any] = {"xAxis": {"data": names}}
    return series, extra_option
