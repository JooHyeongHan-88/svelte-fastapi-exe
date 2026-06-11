"""ChartSpecV1 → ECharts option 변환기.

polars 로 parquet 을 읽어 encoding 채널에 따라 ECharts option JSON 을 생성한다.
프론트엔드는 이 결과를 ``echarts.init().setOption(option)`` 으로 그대로 사용한다.

이 모듈은 순수 함수 모음 — FastAPI/harness 의존성 없이 단독 테스트 가능.
(예외: data.source 가 'result/...' 전체 경로일 때만 core.result_store 의 경로
해석을 지연 import 한다. 단순 파일명 경로는 여전히 외부 의존성이 없다.)

지원 mark / encoding 매트릭스:
    bar       : x(nominal|quantitative) + y(quantitative) + color(nominal) optional
    line      : x(quantitative|temporal) + y(quantitative) + color optional
    scatter   : x(quantitative) + y(quantitative) + color optional
    box       : y(quantitative) [+ x(nominal) for grouped boxplot] + color optional
    histogram : x(quantitative, bin=True) → bin count [+ color(nominal) for grouped bins]
    heatmap   : x(nominal) + y(nominal) + color(quantitative)
    ecdf      : x(quantitative) [+ color(nominal) for grouped curves] → 누적분포 계단선

aggregate 지원: count·mean·sum·min·max. groupby 키는 색/x 채널 조합으로 결정.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

import polars as pl

from .chart_spec import (
    ChartSpecV1,
    ChartV1,
    Encoding,
    EncodingChannel,
    EncodingType,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 상수 — ECharts 공통 toolbox / axis type 매핑
# ---------------------------------------------------------------------------

_TOOLBOX_FEATURE: dict[str, Any] = {
    "brush": {"type": ["rect", "polygon", "clear"]},
    "dataZoom": {},
    "restore": {},
    "saveAsImage": {},
}

_ENCODING_TO_AXIS_TYPE: dict[EncodingType, str] = {
    "quantitative": "value",
    "nominal": "category",
    "temporal": "time",
}

# 인터랙티브 brush 필터링용 내부 행 식별자. _load_data_frame 직후 with_row_index 로
# 원본 parquet 순서의 행 번호를 부여해, 렌더된 점(scatter/line)을 원본 행으로 역추적한다.
# encoding field 와 절대 충돌하지 않도록 dunder 접두/접미를 쓴다.
_ROW_ID_COL = "__row_id__"


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def render_spec_to_echarts(
    spec: ChartSpecV1,
    base_dir: Path,
    exclude_by_chart: dict[Any, list[int]] | None = None,
    legend_by_chart: dict[Any, dict] | None = None,
) -> list[dict[str, Any]]:
    """spec 의 각 차트를 ECharts option dict 로 변환해 리스트로 반환한다.

    Args:
        spec: 검증된 ChartSpecV1 인스턴스.
        base_dir: parquet 파일을 찾을 디렉터리 (spec 파일이 위치한 폴더).
        exclude_by_chart: 차트 인덱스(int 또는 str) → 제외할 원본 행 인덱스 리스트.
            인터랙티브 brush 필터링 상태. None 이면 무필터 (최초 렌더와 동일).
        legend_by_chart: 차트 인덱스(int 또는 str) → 레전드 오버라이드
            ``{"order": [name], "colors": {name: hex}, "hidden": [name]}``.
            None 이면 레전드 기본값 (최초 렌더와 동일).

    Returns:
        ``[{chart_type, title, option, source, row_ids}, ...]`` — 프론트엔드가
        직접 소비하는 형태. ``source`` 는 차트의 parquet 파일명(Filter All 의 동일
        데이터 그룹 판정용), ``row_ids`` 는 점 기반 차트의 시리즈별 원본 행 인덱스
        평행 배열(brush 선택 → 행 역추적용). 집계 차트는 ``row_ids=None``.

    Raises:
        FileNotFoundError: data.source 가 가리키는 parquet 파일이 없을 때.
        ValueError: encoding 또는 mark 가 데이터와 호환되지 않을 때.
    """
    rendered: list[dict[str, Any]] = []
    for idx, chart in enumerate(spec.charts):
        try:
            df = _load_data_frame(chart.data.source, base_dir)
            # 원본 순서의 행 식별자 부여 후, 필터 상태가 있으면 제외 행을 떨군다.
            df = df.with_row_index(_ROW_ID_COL)
            excluded = _excluded_for_chart(exclude_by_chart, idx)
            if excluded:
                df = df.filter(~pl.col(_ROW_ID_COL).is_in(excluded))
            option, row_ids = _render_chart(chart, df)
        except (FileNotFoundError, ValueError) as exc:
            raise type(exc)(
                f"charts[{idx}] ({chart.mark}, {chart.title!r}): {exc}"
            ) from exc

        if chart.extra_option:
            option = _deep_merge(option, chart.extra_option)
            option = _restore_mismatched_legend(option)

        legend_cfg = _legend_for_chart(legend_by_chart, idx)
        if legend_cfg:
            option = _apply_legend_config(option, legend_cfg)

        rendered.append(
            {
                "chart_type": chart.mark,
                "title": chart.title,
                "option": option,
                "source": chart.data.source,
                "row_ids": row_ids,
            }
        )
    return rendered


def _excluded_for_chart(
    exclude_by_chart: dict[Any, list[int]] | None, idx: int
) -> list[int] | None:
    """차트 인덱스의 제외 행 리스트를 정규화해 반환한다 (없으면 None).

    JSON 라운드트립으로 키가 str 로 바뀔 수 있어 int/str 양쪽을 조회한다.
    """
    if not exclude_by_chart:
        return None
    raw = exclude_by_chart.get(idx)
    if raw is None:
        raw = exclude_by_chart.get(str(idx))
    if not raw:
        return None
    return [int(v) for v in raw]


def _legend_for_chart(legend_by_chart: dict[Any, dict] | None, idx: int) -> dict | None:
    """차트 인덱스의 레전드 오버라이드를 반환한다 (없으면 None).

    JSON 라운드트립으로 키가 str 로 바뀔 수 있어 int/str 양쪽을 조회한다.
    """
    if not legend_by_chart:
        return None
    cfg = legend_by_chart.get(idx)
    if cfg is None:
        cfg = legend_by_chart.get(str(idx))
    if not cfg:
        return None
    return cfg


def resolve_legend_row_ids(
    chart: ChartV1, base_dir: Path, legend_values: list[str]
) -> list[int]:
    """레전드 이름(들)에 해당하는 원본 parquet 행 인덱스를 반환한다.

    "레전드 Filter" 를 기존 행-기반 exclude 로 환원하는 다리 — color 채널의 컬럼
    값이 ``legend_values`` 에 속하는 모든 행의 ``__row_id__`` 를 모은다. 시리즈
    name 은 ``str(group_value)`` 라, 비교도 컬럼을 문자열로 캐스팅해 맞춘다.

    Args:
        chart: 레전드 그룹을 가진 차트 정의 (color 채널 필요).
        base_dir: parquet 파일이 위치한 폴더.
        legend_values: 제외 대상 레전드 이름 리스트 (시리즈 name).

    Returns:
        매칭된 원본 행 인덱스 리스트. color 채널이 없거나 컬럼 부재 시 ``[]``.
    """
    if chart.encoding.color is None or not legend_values:
        return []
    field_name = chart.encoding.color.field
    df = _load_data_frame(chart.data.source, base_dir).with_row_index(_ROW_ID_COL)
    if field_name not in df.columns:
        return []
    targets = [str(v) for v in legend_values]
    matched = df.filter(pl.col(field_name).cast(pl.Utf8, strict=False).is_in(targets))
    return [int(v) for v in matched[_ROW_ID_COL].to_list()]


# ---------------------------------------------------------------------------
# 데이터 로딩
# ---------------------------------------------------------------------------


def _load_data_frame(source: str, base_dir: Path) -> pl.DataFrame:
    """spec 의 data.source → polars DataFrame.

    두 가지 표기를 허용한다:
        1. 단순 파일명 ('data.parquet') — 같은 폴더(base_dir)에서 로드.
        2. 'result/...' 전체 상대 경로 — RESULT_DIR 기준으로 해석 (이전 턴의 다른
           타임스탬프 폴더에 있는 parquet 재사용). 경로 해석만 core.result_store 에
           의존하며 containment 검증을 포함한다.

    Args:
        source: data.source 문자열.
        base_dir: 단순 파일명일 때 parquet 을 찾을 폴더 (spec 위치).

    Returns:
        로드된 polars DataFrame.

    Raises:
        ValueError: 경로가 허용 형식이 아닐 때.
        FileNotFoundError: parquet 파일이 없을 때.
    """
    normalized = source.replace("\\", "/")

    # 'result/...' 전체 경로 — RESULT_DIR 기준 해석 (frozen EXE 안전).
    if normalized.startswith("result/"):
        # 지연 import — 이 모듈이 core 에 import-time 종속되지 않게 한다.
        from core.result_store import resolve_result_path

        target, error = resolve_result_path(normalized)
        if error or target is None:
            raise FileNotFoundError(f"data.source 해석 실패: {error}")
        if target.suffix.lower() != ".parquet":
            raise ValueError(f"data.source 는 parquet 이어야 한다: {source!r}")
        return pl.read_parquet(target)

    # 단순 파일명 — 같은 폴더에서 로드.
    if "/" in normalized or ".." in normalized:
        raise ValueError(
            f"data.source 는 단순 파일명 또는 'result/...' 경로만 허용한다: {source!r}"
        )

    target = base_dir / source
    if not target.exists():
        raise FileNotFoundError(f"parquet 파일을 찾을 수 없다: {source!r}")

    return pl.read_parquet(target)


# ---------------------------------------------------------------------------
# 마크별 렌더러
# ---------------------------------------------------------------------------


def _render_chart(
    chart: ChartV1, df: pl.DataFrame
) -> tuple[dict[str, Any], list[list[int]] | None]:
    """mark 별 렌더러 분기. ``(option, row_ids)`` 반환.

    ``row_ids`` 는 점 기반 차트(비집계 scatter/line)에서만 시리즈별 원본 행
    인덱스 배열로 채워지고, 집계 차트(bar/box/histogram/heatmap, category 축)는
    개별 점을 단일 행으로 역추적할 수 없어 None 이다.
    """
    if chart.mark == "bar":
        return _render_standard(chart, df, echarts_type="bar")
    if chart.mark == "line":
        return _render_standard(chart, df, echarts_type="line")
    if chart.mark == "scatter":
        return _render_standard(chart, df, echarts_type="scatter")
    if chart.mark == "ecdf":
        return _render_ecdf(chart, df)
    if chart.mark == "box":
        return _render_box(chart, df), None
    if chart.mark == "histogram":
        return _render_histogram(chart, df), None
    if chart.mark == "heatmap":
        return _render_heatmap(chart, df), None
    raise ValueError(f"미지원 mark: {chart.mark!r}")


def _render_standard(
    chart: ChartV1,
    df: pl.DataFrame,
    *,
    echarts_type: str,
) -> tuple[dict[str, Any], list[list[int]] | None]:
    """bar / line / scatter 공용 렌더러.

    encoding.color 가 있으면 color field 로 groupby 해 여러 시리즈를 만든다.
    """
    enc = chart.encoding
    if enc.x is None or enc.y is None:
        raise ValueError(f"{chart.mark} 차트는 x, y encoding 모두 필요하다")

    _ensure_columns(
        df, [enc.x.field, enc.y.field] + ([enc.color.field] if enc.color else [])
    )

    x_axis_type = _ENCODING_TO_AXIS_TYPE[enc.x.type]
    y_axis_type = _ENCODING_TO_AXIS_TYPE[enc.y.type]

    # bar 차트는 보통 category x. type 이 quantitative 여도 사용자가 명시했으면 존중.
    series, x_categories, row_ids = _build_series(df, enc, echarts_type)

    # line 은 ECharts brush 가 점을 선택하지 못하므로(scatter/bar/candlestick 만 지원)
    # 보이지 않는 scatter 트윈을 덧씌워 brush 선택을 가능케 한다.
    if echarts_type == "line" and row_ids is not None:
        series, row_ids = _with_brush_overlay(series, row_ids)

    # 레전드는 원본 시리즈 이름만 (overlay 는 같은 이름을 공유하므로 dedupe).
    legend_names = list(dict.fromkeys(s["name"] for s in series))

    option: dict[str, Any] = {
        "tooltip": {"trigger": "axis" if echarts_type != "scatter" else "item"},
        "legend": {"data": legend_names},
        "toolbox": {"feature": _TOOLBOX_FEATURE},
        "brush": {},
        "dataZoom": [{"type": "inside"}, {"type": "slider"}],
        "xAxis": _axis_definition(enc.x, x_axis_type, x_categories),
        "yAxis": _axis_definition(enc.y, y_axis_type, None),
        "series": series,
    }
    return option, row_ids


# brush overlay scatter 의 점 크기 — 충분히 커야 드래그 선택이 쉽다.
_BRUSH_OVERLAY_SYMBOL_SIZE = 12


def _with_brush_overlay(
    series: list[dict[str, Any]],
    row_ids: list[list[int] | None],
) -> tuple[list[dict[str, Any]], list[list[int] | None]]:
    """line 시리즈마다 동일 좌표의 투명 scatter 트윈을 추가한다.

    ECharts brush 의 ``brushSelector`` 는 scatter/bar/candlestick 만 구현돼 있어
    line 시리즈의 점은 brush 로 선택되지 않는다(apache/echarts#18155). 선은 그대로
    렌더하되, 같은 데이터의 보이지 않는 scatter 를 위에 깔아 brush 가 점을 잡게 하고,
    그 scatter 의 dataIndex 를 원본 행으로 역추적한다.

    Args:
        series: ``_build_series`` 가 만든 line 시리즈 리스트.
        row_ids: 시리즈별 원본 행 인덱스 평행 배열 (같은 길이).

    Returns:
        ``(확장된 series, 확장된 row_ids)``. 원본 line 시리즈의 row_ids 항목은
        ``None`` 으로 바꿔 brush 매핑에서 제외하고(선택은 overlay 담당), 새로 추가한
        overlay scatter 항목이 실제 행 인덱스를 갖는다.
    """
    new_series: list[dict[str, Any]] = []
    new_row_ids: list[list[int] | None] = []
    for line_series, ids in zip(series, row_ids):
        new_series.append(line_series)
        new_row_ids.append(None)  # 선택은 overlay 가 담당
        overlay = {
            "name": line_series["name"],
            "type": "scatter",
            "data": line_series["data"],
            "symbolSize": _BRUSH_OVERLAY_SYMBOL_SIZE,
            "itemStyle": {"opacity": 0},  # 보이지 않지만 brush hit-test 는 유효
            "emphasis": {"disabled": True},  # hover 시 점이 드러나지 않게
            "tooltip": {"show": False},  # axis tooltip 중복 방지
            "silent": True,  # hover/클릭 이벤트는 line 에 맡김 (brush 는 영향 없음)
            "z": 5,
        }
        new_series.append(overlay)
        new_row_ids.append(ids)
    return new_series, new_row_ids


def _render_ecdf(
    chart: ChartV1, df: pl.DataFrame
) -> tuple[dict[str, Any], list[list[int] | None] | None]:
    """ECDF(경험적 누적분포함수) 렌더러 — quantitative x 를 정렬해 누적 비율 계단선.

    각 점의 y 는 F(x) = (x 이하 표본 수)/n 으로, x 오름차순 i 번째(1-base) 점에서
    ``i/n`` 이다. color 채널이 있으면 그룹별로 별도 ECDF 곡선을 그린다.

    line 과 마찬가지로 ECharts brush 가 계단선의 점을 못 잡으므로 투명 scatter
    트윈을 덧씌워 brush 선택·필터를 가능케 한다. 정렬 순서의 ``__row_id__`` 가 곧
    점별 원본 행 인덱스라, 점을 제외하면 백엔드 재렌더에서 n 이 줄며 곡선이 다시
    계산된다.

    Args:
        chart: ecdf mark 차트 정의.
        df: ``__row_id__`` 가 부여된(그리고 필터가 적용된) DataFrame.

    Returns:
        ``(option, row_ids)`` — row_ids 는 line overlay 규약을 따라 본체 시리즈는
        None, overlay scatter 시리즈가 정렬된 원본 행 인덱스를 갖는다.

    Raises:
        ValueError: x encoding 이 없거나 quantitative 가 아닐 때.
    """
    enc = chart.encoding
    if enc.x is None:
        raise ValueError("ecdf 차트는 x encoding 이 필요하다")
    if enc.x.type != "quantitative":
        raise ValueError("ecdf 의 x.type 은 quantitative 여야 한다")

    _ensure_columns(df, [enc.x.field] + ([enc.color.field] if enc.color else []))

    series: list[dict[str, Any]] = []
    row_ids: list[list[int] | None] = []

    if enc.color is not None:
        groups = df[enc.color.field].unique(maintain_order=True).to_list()
        for group_value in groups:
            subset = df.filter(pl.col(enc.color.field) == group_value)
            points, ids = _ecdf_points(subset, enc.x.field)
            series.append(_ecdf_series(str(group_value), points))
            row_ids.append(ids)
    else:
        points, ids = _ecdf_points(df, enc.x.field)
        series.append(_ecdf_series(enc.x.title or enc.x.field, points))
        row_ids.append(ids)

    # 계단선도 line 이라 brush 가 점을 못 잡는다 → 투명 scatter overlay 추가.
    series, row_ids = _with_brush_overlay(series, row_ids)
    legend_names = list(dict.fromkeys(s["name"] for s in series))

    option: dict[str, Any] = {
        "tooltip": {"trigger": "axis"},
        "legend": {"data": legend_names},
        "toolbox": {"feature": _TOOLBOX_FEATURE},
        "brush": {},
        "dataZoom": [{"type": "inside"}, {"type": "slider"}],
        "xAxis": {"type": "value", "name": enc.x.title or enc.x.field},
        "yAxis": {"type": "value", "name": "누적 비율", "min": 0, "max": 1},
        "series": series,
    }
    return option, row_ids


def _ecdf_points(df: pl.DataFrame, field: str) -> tuple[list[list[Any]], list[int]]:
    """x 컬럼을 오름차순 정렬해 ``[[x, i/n], ...]`` 누적 비율 점과 원본 행 인덱스 반환.

    null 은 분포 계산에서 제외한다(통상적인 ECDF 관례).
    """
    ordered = df.filter(pl.col(field).is_not_null()).sort(field)
    n = ordered.height
    if n == 0:
        return [], []
    xs = ordered[field].to_list()
    ids = [int(v) for v in ordered[_ROW_ID_COL].to_list()]
    points = [[_to_jsonable(xs[i]), (i + 1) / n] for i in range(n)]
    return points, ids


def _ecdf_series(name: str, data: list[list[Any]]) -> dict[str, Any]:
    """ECDF 계단선 시리즈 — step='end' 로 우측 계단, 본체 심볼은 숨김."""
    return {
        "name": name,
        "type": "line",
        "step": "end",
        "showSymbol": False,
        "data": data,
    }


def _render_box(chart: ChartV1, df: pl.DataFrame) -> dict[str, Any]:
    """boxplot 렌더러 — y 컬럼에서 [min, Q1, median, Q3, max] 계산.

    x 채널이 있으면 x 값별로 박스 묶음 (categorical x).
    color 채널이 있으면 색별로 추가 그루핑.
    """
    enc = chart.encoding
    if enc.y is None:
        raise ValueError("box 차트는 y encoding 이 필요하다")

    _ensure_columns(
        df,
        [enc.y.field]
        + ([enc.x.field] if enc.x else [])
        + ([enc.color.field] if enc.color else []),
    )

    # 그룹 키 결정: x + color (있는 것만)
    group_fields = [c.field for c in (enc.x, enc.color) if c is not None]

    if not group_fields:
        # 전체 데이터를 단일 박스로
        categories = [chart.title or enc.y.field]
        box_data = [_box_stats(df[enc.y.field])]
        series_data = [
            {"name": enc.y.title or enc.y.field, "type": "boxplot", "data": box_data}
        ]
    else:
        grouped = df.group_by(group_fields, maintain_order=True).agg(
            pl.col(enc.y.field)
        )
        categories = [
            _compose_group_label(row, group_fields)
            for row in grouped.iter_rows(named=True)
        ]
        box_values = [
            _box_stats(pl.Series(row[enc.y.field]))
            for row in grouped.iter_rows(named=True)
        ]
        series_data = [
            {
                "name": enc.y.title or enc.y.field,
                "type": "boxplot",
                "data": box_values,
            }
        ]

    option: dict[str, Any] = {
        "tooltip": {"trigger": "item"},
        "legend": {"data": [s["name"] for s in series_data]},
        "toolbox": {"feature": _TOOLBOX_FEATURE},
        "xAxis": {
            "type": "category",
            "name": (enc.x.title if enc.x else "") or "",
            "data": categories,
        },
        "yAxis": _axis_definition(enc.y, _ENCODING_TO_AXIS_TYPE[enc.y.type], None),
        "series": series_data,
    }
    return option


def _render_histogram(chart: ChartV1, df: pl.DataFrame) -> dict[str, Any]:
    """histogram 렌더러 — x.bin=True 인 quantitative 컬럼을 빈으로 나눠 카운트.

    encoding.color 가 있으면 color field 값별로 시리즈를 분리한다 (그룹 분포 비교).
    빈 경계는 전체 데이터 범위에서 한 번만 계산해 모든 그룹이 공유한다 — 그룹마다
    빈을 따로 잡으면 같은 x 축 위에서 막대가 비교 불가능해지기 때문.
    """
    enc = chart.encoding
    if enc.x is None:
        raise ValueError("histogram 은 x encoding 이 필요하다")
    if not enc.x.bin:
        raise ValueError("histogram 은 x.bin=true 가 필요하다")
    if enc.x.type != "quantitative":
        raise ValueError("histogram 의 x.type 은 quantitative 여야 한다")

    _ensure_columns(df, [enc.x.field] + ([enc.color.field] if enc.color else []))

    all_values = df[enc.x.field].drop_nulls()
    if all_values.len() == 0:
        raise ValueError("histogram: 데이터가 비어 있다")

    bin_count = 10  # 향후 spec 으로 노출 가능. 현재는 합리적 기본값.
    bins = _equal_width_bins(all_values, bin_count)
    bin_labels = [f"[{bins[i]:.2f}, {bins[i + 1]:.2f})" for i in range(len(bins) - 1)]

    series_list: list[dict[str, Any]]
    if enc.color is not None:
        groups = df[enc.color.field].unique(maintain_order=True).to_list()
        series_list = [
            {
                "name": str(group_value),
                "type": "bar",
                "data": _bin_counts(
                    df.filter(pl.col(enc.color.field) == group_value)[
                        enc.x.field
                    ].drop_nulls(),
                    bins,
                ),
            }
            for group_value in groups
        ]
    else:
        series_list = [
            {"name": "count", "type": "bar", "data": _bin_counts(all_values, bins)}
        ]

    option: dict[str, Any] = {
        "tooltip": {"trigger": "axis"},
        "legend": {"data": [s["name"] for s in series_list]},
        "toolbox": {"feature": _TOOLBOX_FEATURE},
        "xAxis": {
            "type": "category",
            "name": enc.x.title or enc.x.field,
            "data": bin_labels,
        },
        "yAxis": {
            "type": "value",
            "name": (enc.y.title if enc.y else "count") or "count",
        },
        "series": series_list,
    }
    return option


def _render_heatmap(chart: ChartV1, df: pl.DataFrame) -> dict[str, Any]:
    """heatmap 렌더러 — x(nominal) × y(nominal) × color(quantitative) 3-튜플."""
    enc = chart.encoding
    if enc.x is None or enc.y is None or enc.color is None:
        raise ValueError("heatmap 은 x, y, color encoding 모두 필요하다")
    if enc.color.type != "quantitative":
        raise ValueError("heatmap 의 color.type 은 quantitative 여야 한다")

    _ensure_columns(df, [enc.x.field, enc.y.field, enc.color.field])

    x_values = df[enc.x.field].unique(maintain_order=True).to_list()
    y_values = df[enc.y.field].unique(maintain_order=True).to_list()
    x_index = {v: i for i, v in enumerate(x_values)}
    y_index = {v: i for i, v in enumerate(y_values)}

    data_points: list[list[float | int]] = []
    color_values: list[float] = []
    for row in df.iter_rows(named=True):
        xi = x_index[row[enc.x.field]]
        yi = y_index[row[enc.y.field]]
        val = float(row[enc.color.field])
        data_points.append([xi, yi, val])
        color_values.append(val)

    option: dict[str, Any] = {
        "tooltip": {"trigger": "item"},
        "toolbox": {"feature": _TOOLBOX_FEATURE},
        "xAxis": {
            "type": "category",
            "name": enc.x.title or enc.x.field,
            "data": [str(v) for v in x_values],
        },
        "yAxis": {
            "type": "category",
            "name": enc.y.title or enc.y.field,
            "data": [str(v) for v in y_values],
        },
        "visualMap": {
            "min": min(color_values, default=0),
            "max": max(color_values, default=1),
            "calculable": True,
            "orient": "horizontal",
            "left": "center",
            "bottom": "5%",
        },
        "series": [
            {
                "name": enc.color.title or enc.color.field,
                "type": "heatmap",
                "data": data_points,
            }
        ],
    }
    return option


# ---------------------------------------------------------------------------
# 시리즈 빌더 (bar / line / scatter 공용)
# ---------------------------------------------------------------------------


def _build_series(
    df: pl.DataFrame,
    enc: Encoding,
    echarts_type: str,
) -> tuple[list[dict[str, Any]], list[str] | None, list[list[int]] | None]:
    """encoding 에 따라 시리즈 리스트와 (필요 시) 카테고리 축 라벨·행 인덱스 생성.

    color 가 있으면 그룹별로 시리즈를 분리한다. aggregate 가 있으면 groupby 집계.
    bar 차트는 x 축이 category 이면 카테고리 리스트도 반환.

    세 번째 반환값 ``row_ids`` 는 점이 원본 행과 1:1 대응하는 경우(비category 의
    pair data 경로)에만 시리즈별 원본 행 인덱스 배열로 채워진다. category 축
    (bar·nominal x)은 점이 행 집계 슬롯이라 None.
    """
    assert enc.x is not None and enc.y is not None

    needs_categories = enc.x.type == "nominal" or echarts_type == "bar"
    x_categories: list[str] | None = None

    # color 가 있으면 그룹별 시리즈
    if enc.color is not None:
        group_field = enc.color.field
        groups = df[group_field].unique(maintain_order=True).to_list()

        if needs_categories:
            x_categories = [
                str(v) for v in df[enc.x.field].unique(maintain_order=True).to_list()
            ]

        series_list: list[dict[str, Any]] = []
        row_ids_list: list[list[int]] | None = None if needs_categories else []
        for group_value in groups:
            subset = df.filter(pl.col(group_field) == group_value)
            subset = _maybe_aggregate(
                subset, enc, group_field=enc.x.field if needs_categories else None
            )
            series_list.append(
                {
                    "name": str(group_value),
                    "type": echarts_type,
                    "data": _rows_to_pairs(subset, enc, x_categories),
                    **({"symbolSize": 8} if echarts_type == "scatter" else {}),
                }
            )
            if row_ids_list is not None:
                row_ids_list.append(_row_ids_of(subset))
        return series_list, x_categories, row_ids_list

    # 단일 시리즈
    aggregated = _maybe_aggregate(
        df, enc, group_field=enc.x.field if needs_categories else None
    )
    if needs_categories:
        x_categories = [str(v) for v in aggregated[enc.x.field].to_list()]

    series_one = {
        "name": enc.y.title or enc.y.field,
        "type": echarts_type,
        "data": _rows_to_pairs(aggregated, enc, x_categories),
        **({"symbolSize": 8} if echarts_type == "scatter" else {}),
    }
    row_ids = None if needs_categories else [_row_ids_of(aggregated)]
    return [series_one], x_categories, row_ids


def _row_ids_of(df: pl.DataFrame) -> list[int]:
    """pair data 경로의 시리즈에 대응하는 원본 행 인덱스 리스트.

    _rows_to_pairs 의 비category 분기가 df 행을 순서대로 점으로 방출하므로,
    같은 순서의 _ROW_ID_COL 값이 곧 점별 원본 행 인덱스가 된다.
    """
    return [int(v) for v in df[_ROW_ID_COL].to_list()]


def _maybe_aggregate(
    df: pl.DataFrame,
    enc: Encoding,
    *,
    group_field: str | None,
) -> pl.DataFrame:
    """y.aggregate 가 있으면 group_field 로 묶어 집계한다."""
    assert enc.x is not None and enc.y is not None
    aggregate = enc.y.aggregate
    if aggregate is None or group_field is None:
        return df

    agg_expr = _aggregate_expr(enc.y.field, aggregate)
    grouped = df.group_by(group_field, maintain_order=True).agg(
        agg_expr.alias(enc.y.field)
    )
    return grouped


def _aggregate_expr(field: str, fn: str) -> pl.Expr:
    if fn == "count":
        return pl.col(field).count()
    if fn == "mean":
        return pl.col(field).mean()
    if fn == "sum":
        return pl.col(field).sum()
    if fn == "min":
        return pl.col(field).min()
    if fn == "max":
        return pl.col(field).max()
    raise ValueError(f"미지원 aggregate: {fn!r}")


def _rows_to_pairs(
    df: pl.DataFrame,
    enc: Encoding,
    x_categories: list[str] | None,
) -> list[Any]:
    """DataFrame 의 (x, y) 컬럼을 ECharts series.data 형태로 변환.

    카테고리 축이면 카테고리 인덱스 순서에 맞춘 y 값 리스트만 반환 (xAxis.data 가 라벨).
    수치/시간 축이면 [[x, y], ...] 페어 반환.
    """
    assert enc.x is not None and enc.y is not None

    if x_categories is not None:
        # 카테고리 축: x 값을 인덱스로 매핑해 누락된 자리를 None 으로 채움
        idx = {v: i for i, v in enumerate(x_categories)}
        out: list[float | None] = [None] * len(x_categories)
        for row in df.iter_rows(named=True):
            key = str(row[enc.x.field])
            if key in idx:
                out[idx[key]] = _to_jsonable(row[enc.y.field])
        return out

    return [
        [_to_jsonable(row[enc.x.field]), _to_jsonable(row[enc.y.field])]
        for row in df.iter_rows(named=True)
    ]


# ---------------------------------------------------------------------------
# 박스/히스토그램 유틸
# ---------------------------------------------------------------------------


def _box_stats(series: pl.Series) -> list[float]:
    """polars quantile 로 [min, Q1, median, Q3, max] 계산."""
    clean = series.drop_nulls()
    if clean.len() == 0:
        return [0.0, 0.0, 0.0, 0.0, 0.0]
    return [
        float(clean.min()),
        float(clean.quantile(0.25, interpolation="linear")),
        float(clean.quantile(0.5, interpolation="linear")),
        float(clean.quantile(0.75, interpolation="linear")),
        float(clean.max()),
    ]


def _equal_width_bins(series: pl.Series, bin_count: int) -> list[float]:
    lo = float(series.min())
    hi = float(series.max())
    if lo == hi:
        # 동일 값만 있으면 인위적인 폭 부여
        hi = lo + 1.0
    step = (hi - lo) / bin_count
    return [lo + step * i for i in range(bin_count + 1)]


def _bin_counts(series: pl.Series, bins: list[float]) -> list[int]:
    counts = [0] * (len(bins) - 1)
    for value in series.to_list():
        for i in range(len(bins) - 1):
            lower = bins[i]
            upper = bins[i + 1]
            inside_last = i == len(bins) - 2 and value == upper
            if (lower <= value < upper) or inside_last:
                counts[i] += 1
                break
    return counts


# ---------------------------------------------------------------------------
# 공용 헬퍼
# ---------------------------------------------------------------------------


def _axis_definition(
    channel: EncodingChannel,
    axis_type: str,
    categories: list[str] | None,
) -> dict[str, Any]:
    axis: dict[str, Any] = {
        "type": axis_type,
        "name": channel.title or channel.field,
    }
    if axis_type == "category" and categories is not None:
        axis["data"] = categories
    return axis


def _ensure_columns(df: pl.DataFrame, fields: list[str]) -> None:
    missing = [f for f in fields if f not in df.columns]
    if missing:
        raise ValueError(
            f"parquet 에 다음 컬럼이 없다: {missing!r}. 사용 가능 컬럼: {df.columns!r}"
        )


def _compose_group_label(row: dict[str, Any], fields: list[str]) -> str:
    return " / ".join(str(row[f]) for f in fields)


def _to_jsonable(value: Any) -> Any:
    """JSON 직렬화 가능 타입으로 변환. polars/numpy 스칼라 → Python primitive."""
    if value is None:
        return None
    if isinstance(value, (int, float, str, bool)):
        return value
    # numpy/polars 스칼라 처리
    try:
        return value.item()  # numpy / polars 스칼라
    except AttributeError:
        return str(value)  # datetime 등은 ISO 문자열


def _apply_legend_config(option: dict[str, Any], legend_cfg: dict) -> dict[str, Any]:
    """렌더된 option 에 레전드 오버라이드(순서·색상·Hide)를 적용한 새 dict 반환.

    - colors: 해당 name 의 모든 시리즈에 ``itemStyle.color`` 주입(line 은 lineStyle 도).
      overlay(opacity 0)에 색이 들어가도 무해하다.
    - order: 시리즈를 name 그룹 단위로 재정렬해 line+overlay 트윈의 인접을 보존한다.
    - hidden: ``legend.selected`` 에 ``{name: bool}`` 로 표시/숨김을 절대값으로 반영.

    legend/series 키가 없으면(heatmap 등) 안전하게 no-op.
    """
    series = option.get("series")
    if not isinstance(series, list) or not series:
        return option

    option = copy.deepcopy(option)
    series = option["series"]

    colors = legend_cfg.get("colors")
    if colors:
        for s in series:
            name = s.get("name")
            if name in colors:
                hex_color = colors[name]
                s.setdefault("itemStyle", {})["color"] = hex_color
                if s.get("type") == "line":
                    s.setdefault("lineStyle", {})["color"] = hex_color

    order = legend_cfg.get("order")
    if order:
        series = _reorder_series_by_name(series, order)
        option["series"] = series

    legend = option.get("legend")
    if isinstance(legend, dict):
        names = list(
            dict.fromkeys(s.get("name") for s in series if s.get("name") is not None)
        )
        legend["data"] = names
        hidden = legend_cfg.get("hidden")
        if hidden:
            hidden_set = set(hidden)
            legend["selected"] = {name: name not in hidden_set for name in names}

    return option


def _reorder_series_by_name(
    series: list[dict[str, Any]], order: list[str]
) -> list[dict[str, Any]]:
    """시리즈를 name 그룹 단위로 재정렬한다 (그룹 내부 순서·미지정 name 은 보존).

    같은 name 을 공유하는 line+overlay 트윈이 그룹으로 묶여 인접을 유지한다.
    order 에 없는 name 은 원래 순서대로 뒤에 붙인다.
    """
    by_name: dict[Any, list[dict[str, Any]]] = {}
    original_order: list[Any] = []
    for s in series:
        name = s.get("name")
        if name not in by_name:
            by_name[name] = []
            original_order.append(name)
        by_name[name].append(s)

    result: list[dict[str, Any]] = []
    for name in order:
        if name in by_name:
            result.extend(by_name.pop(name))
    for name in original_order:
        if name in by_name:
            result.extend(by_name.pop(name))
    return result


def _restore_mismatched_legend(option: dict[str, Any]) -> dict[str, Any]:
    """extra_option 병합으로 legend.data 가 실제 시리즈 이름과 어긋나면 보정한다.

    ECharts 레전드는 series.name 과 문자열이 정확히 일치하는 항목만 표시한다.
    LLM 이 extra_option.legend.data 에 임의 라벨(예: 컬럼 값 '5' 대신 'lambda_5')을
    넣으면 레전드가 통째로 사라지는데 이는 항상 의도 밖이다 — 실존 시리즈 이름과의
    교집합만 남기고, 하나도 안 남으면 시리즈 이름 전체로 복원한다. show 등 다른
    legend 키는 건드리지 않는다.

    Args:
        option: ``_deep_merge`` 가 반환한 병합 사본 (in-place 수정 안전).

    Returns:
        legend.data 가 보정된 option (보정 불필요 시 그대로).
    """
    legend = option.get("legend")
    series = option.get("series")
    if not isinstance(legend, dict) or not isinstance(series, list):
        return option
    data = legend.get("data")
    if not isinstance(data, list):
        return option
    valid_names = list(
        dict.fromkeys(
            s.get("name")
            for s in series
            if isinstance(s, dict) and s.get("name") is not None
        )
    )
    if not valid_names:
        return option
    matched = [name for name in data if name in valid_names]
    if matched == data:
        return option
    logger.warning(
        "extra_option.legend.data 가 시리즈 이름과 불일치해 보정함: %r -> %r",
        data,
        matched or valid_names,
    )
    legend["data"] = matched or valid_names
    return option


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """override 를 base 에 재귀 병합. list 는 override 가 교체."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
