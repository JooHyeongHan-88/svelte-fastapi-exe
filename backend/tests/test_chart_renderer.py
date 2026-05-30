"""chart_renderer 의 mark × encoding 매트릭스 검증.

순수 pytest — FastAPI/harness 의존 없음. polars 만 사용.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from agent.runtime.chart_renderer import (
    render_spec_to_echarts,
    resolve_legend_row_ids,
)
from agent.runtime.chart_spec import ChartSpecV1


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    """parquet 파일을 임시 폴더에 만들어 base_dir 로 사용."""
    samples = pl.DataFrame(
        {
            "idx": [1, 2, 3, 4, 5],
            "value": [10.0, 12.0, 9.5, 15.0, 11.0],
            "anomaly_score": [0.1, 0.3, 0.05, 0.9, 0.2],
        }
    )
    samples.write_parquet(tmp_path / "samples.parquet")

    stats = pl.DataFrame(
        {
            "metric": ["count", "mean", "median", "stdev", "min", "max"],
            "value": [5.0, 11.5, 11.0, 2.1, 9.5, 15.0],
        }
    )
    stats.write_parquet(tmp_path / "stats.parquet")

    grouped = pl.DataFrame(
        {
            "group": ["A", "A", "B", "B", "C", "C"],
            "metric": ["m1", "m2", "m1", "m2", "m1", "m2"],
            "value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        }
    )
    grouped.write_parquet(tmp_path / "grouped.parquet")

    heat = pl.DataFrame(
        {
            "row": ["r1", "r1", "r2", "r2"],
            "col": ["c1", "c2", "c1", "c2"],
            "value": [0.1, 0.5, 0.7, 0.9],
        }
    )
    heat.write_parquet(tmp_path / "heat.parquet")

    return tmp_path


def _render(spec_dict: dict, base_dir: Path) -> list[dict]:
    spec = ChartSpecV1.model_validate(spec_dict)
    return render_spec_to_echarts(spec, base_dir)


def test_bar_nominal_x_quantitative_y(base_dir: Path) -> None:
    result = _render(
        {
            "version": "1",
            "charts": [
                {
                    "mark": "bar",
                    "title": "통계량",
                    "data": {"source": "stats.parquet"},
                    "encoding": {
                        "x": {"field": "metric", "type": "nominal"},
                        "y": {"field": "value", "type": "quantitative"},
                    },
                }
            ],
        },
        base_dir,
    )

    assert len(result) == 1
    item = result[0]
    assert item["chart_type"] == "bar"
    assert item["title"] == "통계량"
    option = item["option"]
    assert option["xAxis"]["type"] == "category"
    assert option["xAxis"]["data"] == ["count", "mean", "median", "stdev", "min", "max"]
    assert option["yAxis"]["type"] == "value"
    assert option["series"][0]["type"] == "bar"
    assert option["series"][0]["data"] == [5.0, 11.5, 11.0, 2.1, 9.5, 15.0]


def test_line_quantitative_x_y(base_dir: Path) -> None:
    result = _render(
        {
            "version": "1",
            "charts": [
                {
                    "mark": "line",
                    "data": {"source": "samples.parquet"},
                    "encoding": {
                        "x": {"field": "idx", "type": "quantitative"},
                        "y": {"field": "value", "type": "quantitative"},
                    },
                }
            ],
        },
        base_dir,
    )
    option = result[0]["option"]
    assert option["xAxis"]["type"] == "value"
    assert option["yAxis"]["type"] == "value"
    assert option["series"][0]["type"] == "line"
    # 페어 형태
    assert option["series"][0]["data"][0] == [1, 10.0]
    assert option["series"][0]["data"][-1] == [5, 11.0]


def test_scatter_two_quantitative(base_dir: Path) -> None:
    result = _render(
        {
            "version": "1",
            "charts": [
                {
                    "mark": "scatter",
                    "data": {"source": "samples.parquet"},
                    "encoding": {
                        "x": {"field": "value", "type": "quantitative"},
                        "y": {"field": "anomaly_score", "type": "quantitative"},
                    },
                }
            ],
        },
        base_dir,
    )
    option = result[0]["option"]
    assert option["series"][0]["type"] == "scatter"
    assert option["series"][0]["symbolSize"] == 8
    assert option["series"][0]["data"][0] == [10.0, 0.1]


def test_box_single_y(base_dir: Path) -> None:
    result = _render(
        {
            "version": "1",
            "charts": [
                {
                    "mark": "box",
                    "title": "분포",
                    "data": {"source": "samples.parquet"},
                    "encoding": {
                        "y": {"field": "value", "type": "quantitative"},
                    },
                }
            ],
        },
        base_dir,
    )
    option = result[0]["option"]
    assert option["series"][0]["type"] == "boxplot"
    # [min, Q1, median, Q3, max] 형식
    box_data = option["series"][0]["data"][0]
    assert len(box_data) == 5
    assert box_data[0] == 9.5  # min
    assert box_data[4] == 15.0  # max


def test_histogram_bin_quantitative(base_dir: Path) -> None:
    result = _render(
        {
            "version": "1",
            "charts": [
                {
                    "mark": "histogram",
                    "data": {"source": "samples.parquet"},
                    "encoding": {
                        "x": {"field": "value", "type": "quantitative", "bin": True},
                    },
                }
            ],
        },
        base_dir,
    )
    option = result[0]["option"]
    assert option["xAxis"]["type"] == "category"
    assert len(option["xAxis"]["data"]) == 10  # bin_count
    counts = option["series"][0]["data"]
    assert sum(counts) == 5  # 전체 샘플 수


def test_heatmap_three_channels(base_dir: Path) -> None:
    result = _render(
        {
            "version": "1",
            "charts": [
                {
                    "mark": "heatmap",
                    "data": {"source": "heat.parquet"},
                    "encoding": {
                        "x": {"field": "col", "type": "nominal"},
                        "y": {"field": "row", "type": "nominal"},
                        "color": {"field": "value", "type": "quantitative"},
                    },
                }
            ],
        },
        base_dir,
    )
    option = result[0]["option"]
    assert option["xAxis"]["data"] == ["c1", "c2"]
    assert option["yAxis"]["data"] == ["r1", "r2"]
    assert option["visualMap"]["min"] == 0.1
    assert option["visualMap"]["max"] == 0.9
    assert len(option["series"][0]["data"]) == 4


def test_color_channel_splits_series(base_dir: Path) -> None:
    result = _render(
        {
            "version": "1",
            "charts": [
                {
                    "mark": "bar",
                    "data": {"source": "grouped.parquet"},
                    "encoding": {
                        "x": {"field": "metric", "type": "nominal"},
                        "y": {"field": "value", "type": "quantitative"},
                        "color": {"field": "group", "type": "nominal"},
                    },
                }
            ],
        },
        base_dir,
    )
    option = result[0]["option"]
    # 그룹 A, B, C 각각 별도 시리즈
    assert len(option["series"]) == 3
    assert {s["name"] for s in option["series"]} == {"A", "B", "C"}


def test_extra_option_deep_merge(base_dir: Path) -> None:
    result = _render(
        {
            "version": "1",
            "charts": [
                {
                    "mark": "bar",
                    "data": {"source": "stats.parquet"},
                    "encoding": {
                        "x": {"field": "metric", "type": "nominal"},
                        "y": {"field": "value", "type": "quantitative"},
                    },
                    "extra_option": {"tooltip": {"formatter": "{b}: {c}"}},
                }
            ],
        },
        base_dir,
    )
    option = result[0]["option"]
    assert option["tooltip"]["formatter"] == "{b}: {c}"
    assert option["tooltip"]["trigger"] == "axis"  # 기존 값 보존


def test_missing_parquet_raises(base_dir: Path) -> None:
    with pytest.raises(FileNotFoundError, match="nonexistent"):
        _render(
            {
                "version": "1",
                "charts": [
                    {
                        "mark": "bar",
                        "data": {"source": "nonexistent.parquet"},
                        "encoding": {
                            "x": {"field": "x", "type": "nominal"},
                            "y": {"field": "y", "type": "quantitative"},
                        },
                    }
                ],
            },
            base_dir,
        )


def test_missing_column_raises(base_dir: Path) -> None:
    with pytest.raises(ValueError, match="컬럼"):
        _render(
            {
                "version": "1",
                "charts": [
                    {
                        "mark": "bar",
                        "data": {"source": "stats.parquet"},
                        "encoding": {
                            "x": {"field": "nope", "type": "nominal"},
                            "y": {"field": "value", "type": "quantitative"},
                        },
                    }
                ],
            },
            base_dir,
        )


def test_path_escape_blocked(base_dir: Path) -> None:
    with pytest.raises(ValueError, match="단순 파일명"):
        _render(
            {
                "version": "1",
                "charts": [
                    {
                        "mark": "bar",
                        "data": {"source": "../escape.parquet"},
                        "encoding": {
                            "x": {"field": "x", "type": "nominal"},
                            "y": {"field": "y", "type": "quantitative"},
                        },
                    }
                ],
            },
            base_dir,
        )


def test_pandas_written_parquet_loads(tmp_path: Path) -> None:
    """pandas 가 쓴 parquet 도 polars 로 읽혀야 한다 (호환성 보장)."""
    import pandas as pd

    pdf = pd.DataFrame({"metric": ["a", "b", "c"], "value": [1.0, 2.0, 3.0]})
    pdf.to_parquet(tmp_path / "from_pandas.parquet")

    result = _render(
        {
            "version": "1",
            "charts": [
                {
                    "mark": "bar",
                    "data": {"source": "from_pandas.parquet"},
                    "encoding": {
                        "x": {"field": "metric", "type": "nominal"},
                        "y": {"field": "value", "type": "quantitative"},
                    },
                }
            ],
        },
        tmp_path,
    )
    assert result[0]["option"]["series"][0]["data"] == [1.0, 2.0, 3.0]


# ---------------------------------------------------------------------------
# 인터랙티브 필터 — source / row_ids 제공 + exclude_by_chart 재집계
# ---------------------------------------------------------------------------

_SCATTER_SPEC = {
    "version": "1",
    "charts": [
        {
            "mark": "scatter",
            "data": {"source": "samples.parquet"},
            "encoding": {
                "x": {"field": "value", "type": "quantitative"},
                "y": {"field": "anomaly_score", "type": "quantitative"},
            },
        }
    ],
}


def test_render_exposes_source_and_row_ids(base_dir: Path) -> None:
    item = _render(_SCATTER_SPEC, base_dir)[0]
    # samples.parquet 5 행이 원본 순서대로 단일 시리즈에 매핑된다.
    assert item["source"] == "samples.parquet"
    assert item["row_ids"] == [[0, 1, 2, 3, 4]]
    assert len(item["option"]["series"][0]["data"]) == 5


def test_aggregated_charts_have_no_row_ids(base_dir: Path) -> None:
    # bar(category) / histogram / box / heatmap 은 점이 행 집계라 row_ids=None.
    bar = _render(
        {
            "version": "1",
            "charts": [
                {
                    "mark": "bar",
                    "data": {"source": "stats.parquet"},
                    "encoding": {
                        "x": {"field": "metric", "type": "nominal"},
                        "y": {"field": "value", "type": "quantitative"},
                    },
                }
            ],
        },
        base_dir,
    )[0]
    assert bar["row_ids"] is None

    hist = _render(
        {
            "version": "1",
            "charts": [
                {
                    "mark": "histogram",
                    "data": {"source": "samples.parquet"},
                    "encoding": {
                        "x": {"field": "value", "type": "quantitative", "bin": True},
                    },
                }
            ],
        },
        base_dir,
    )[0]
    assert hist["row_ids"] is None


def test_exclude_by_chart_drops_scatter_points(base_dir: Path) -> None:
    spec = ChartSpecV1.model_validate(_SCATTER_SPEC)
    # 행 3 = value 15.0, anomaly 0.9 (이상치) 제외.
    filtered = render_spec_to_echarts(spec, base_dir, exclude_by_chart={0: [3]})[0]
    data = filtered["option"]["series"][0]["data"]
    assert len(data) == 4
    assert [15.0, 0.9] not in data
    assert filtered["row_ids"] == [[0, 1, 2, 4]]


def test_exclude_by_chart_reaggregates_histogram(base_dir: Path) -> None:
    spec = ChartSpecV1.model_validate(
        {
            "version": "1",
            "charts": [
                {
                    "mark": "histogram",
                    "data": {"source": "samples.parquet"},
                    "encoding": {
                        "x": {"field": "value", "type": "quantitative", "bin": True},
                    },
                }
            ],
        }
    )
    full = render_spec_to_echarts(spec, base_dir)[0]
    assert sum(full["option"]["series"][0]["data"]) == 5
    # 행 3, 4 제외 → 집계 카운트가 3 으로 줄어든다 (재집계 확인).
    filtered = render_spec_to_echarts(spec, base_dir, exclude_by_chart={0: [3, 4]})[0]
    assert sum(filtered["option"]["series"][0]["data"]) == 3


def test_exclude_str_keyed_index_supported(base_dir: Path) -> None:
    # JSON 라운드트립으로 키가 str 이 되어도 동작해야 한다.
    spec = ChartSpecV1.model_validate(_SCATTER_SPEC)
    filtered = render_spec_to_echarts(spec, base_dir, exclude_by_chart={"0": [0, 1]})[0]
    assert filtered["row_ids"] == [[2, 3, 4]]


# ---------------------------------------------------------------------------
# line brush overlay — ECharts brush 가 line 점을 못 잡으므로 투명 scatter 트윈 추가
# ---------------------------------------------------------------------------

_LINE_SPEC = {
    "version": "1",
    "charts": [
        {
            "mark": "line",
            "data": {"source": "samples.parquet"},
            "encoding": {
                "x": {"field": "idx", "type": "quantitative"},
                "y": {"field": "value", "type": "quantitative"},
            },
        }
    ],
}


def test_line_gets_invisible_scatter_brush_overlay(base_dir: Path) -> None:
    item = _render(_LINE_SPEC, base_dir)[0]
    series = item["option"]["series"]
    # line 본체 + 투명 scatter overlay 2개.
    assert [s["type"] for s in series] == ["line", "scatter"]
    overlay = series[1]
    assert overlay["itemStyle"]["opacity"] == 0  # 보이지 않음
    assert overlay["data"] == series[0]["data"]  # 같은 좌표
    # 선택은 overlay 가 담당: line=None, overlay=원본 행 인덱스.
    assert item["row_ids"] == [None, [0, 1, 2, 3, 4]]
    # 레전드는 overlay 중복 없이 단일 항목 (title 없으면 field 명).
    assert item["option"]["legend"]["data"] == ["value"]


def test_line_overlay_respects_exclude_filter(base_dir: Path) -> None:
    spec = ChartSpecV1.model_validate(_LINE_SPEC)
    # 행 1, 3 제외 → line·overlay 모두 3 점으로 줄고 overlay row_ids 도 갱신.
    filtered = render_spec_to_echarts(spec, base_dir, exclude_by_chart={0: [1, 3]})[0]
    series = filtered["option"]["series"]
    assert len(series[0]["data"]) == 3
    assert len(series[1]["data"]) == 3
    assert filtered["row_ids"] == [None, [0, 2, 4]]


def test_line_color_groups_each_get_overlay(base_dir: Path) -> None:
    # color 그룹 line 은 그룹마다 line+overlay 쌍을 갖는다.
    item = _render(
        {
            "version": "1",
            "charts": [
                {
                    "mark": "line",
                    "data": {"source": "grouped.parquet"},
                    "encoding": {
                        "x": {"field": "value", "type": "quantitative"},
                        "y": {"field": "value", "type": "quantitative"},
                        "color": {"field": "group", "type": "nominal"},
                    },
                }
            ],
        },
        base_dir,
    )[0]
    types = [s["type"] for s in item["option"]["series"]]
    # A,B,C 각 그룹 → line, scatter 교대.
    assert types == ["line", "scatter", "line", "scatter", "line", "scatter"]
    # row_ids: line 항목은 None, overlay 항목만 행 인덱스.
    assert [r is None for r in item["row_ids"]] == [
        True,
        False,
        True,
        False,
        True,
        False,
    ]
    # 레전드는 그룹명만 (overlay 중복 제거).
    assert item["option"]["legend"]["data"] == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# ecdf — 정렬 후 누적분포 계단선 + brush overlay
# ---------------------------------------------------------------------------

_ECDF_SPEC = {
    "version": "1",
    "charts": [
        {
            "mark": "ecdf",
            "data": {"source": "samples.parquet"},
            "encoding": {
                "x": {"field": "value", "type": "quantitative"},
            },
        }
    ],
}


def test_ecdf_cumulative_step_line(base_dir: Path) -> None:
    item = _render(_ECDF_SPEC, base_dir)[0]
    assert item["chart_type"] == "ecdf"
    series = item["option"]["series"]
    # 계단선 본체 + 투명 scatter overlay.
    assert [s["type"] for s in series] == ["line", "scatter"]
    ecdf = series[0]
    assert ecdf["step"] == "end"
    assert ecdf["showSymbol"] is False
    # value [10,12,9.5,15,11] 오름차순 → [9.5,10,11,12,15], y=i/5.
    assert ecdf["data"] == [
        [9.5, 0.2],
        [10.0, 0.4],
        [11.0, 0.6],
        [12.0, 0.8],
        [15.0, 1.0],
    ]
    # y 축은 0~1 비율 고정.
    assert item["option"]["yAxis"]["min"] == 0
    assert item["option"]["yAxis"]["max"] == 1
    # 정렬 순서의 원본 행 인덱스가 overlay row_ids 로 노출 (선택→제외용).
    assert item["row_ids"] == [None, [2, 0, 4, 1, 3]]


def test_ecdf_reaggregates_on_exclude(base_dir: Path) -> None:
    spec = ChartSpecV1.model_validate(_ECDF_SPEC)
    # 최댓값 행 3(value 15) 제외 → n=4 로 줄고 누적 비율이 1/4 단위로 재계산.
    filtered = render_spec_to_echarts(spec, base_dir, exclude_by_chart={0: [3]})[0]
    ecdf = filtered["option"]["series"][0]
    assert ecdf["data"] == [
        [9.5, 0.25],
        [10.0, 0.5],
        [11.0, 0.75],
        [12.0, 1.0],
    ]
    assert filtered["row_ids"] == [None, [2, 0, 4, 1]]


def test_ecdf_color_groups_each_get_curve(base_dir: Path) -> None:
    item = _render(
        {
            "version": "1",
            "charts": [
                {
                    "mark": "ecdf",
                    "data": {"source": "grouped.parquet"},
                    "encoding": {
                        "x": {"field": "value", "type": "quantitative"},
                        "color": {"field": "group", "type": "nominal"},
                    },
                }
            ],
        },
        base_dir,
    )[0]
    # A,B,C 각 그룹마다 ecdf line + overlay scatter.
    assert [s["type"] for s in item["option"]["series"]] == [
        "line",
        "scatter",
        "line",
        "scatter",
        "line",
        "scatter",
    ]
    assert item["option"]["legend"]["data"] == ["A", "B", "C"]


def test_ecdf_requires_quantitative_x(base_dir: Path) -> None:
    with pytest.raises(ValueError, match="quantitative"):
        _render(
            {
                "version": "1",
                "charts": [
                    {
                        "mark": "ecdf",
                        "data": {"source": "stats.parquet"},
                        "encoding": {
                            "x": {"field": "metric", "type": "nominal"},
                        },
                    }
                ],
            },
            base_dir,
        )


# ---------------------------------------------------------------------------
# 레전드 컨트롤 (순서·색상·Hide) + 그룹→행 해석
# ---------------------------------------------------------------------------

# group A=rows0,1 / B=2,3 / C=4,5 인 grouped.parquet 의 ecdf — A/B/C 시리즈 + overlay.
_GROUPED_ECDF = {
    "version": "1",
    "charts": [
        {
            "mark": "ecdf",
            "data": {"source": "grouped.parquet"},
            "encoding": {
                "x": {"field": "value", "type": "quantitative"},
                "color": {"field": "group", "type": "nominal"},
            },
        }
    ],
}


def test_legend_order_reorders_series_keeping_overlay_adjacent(base_dir: Path) -> None:
    spec = ChartSpecV1.model_validate(_GROUPED_ECDF)
    item = render_spec_to_echarts(
        spec, base_dir, legend_by_chart={0: {"order": ["C", "A", "B"]}}
    )[0]
    names = [s["name"] for s in item["option"]["series"]]
    # line+overlay 트윈이 그룹으로 묶여 인접 유지 + 요청 순서대로 재배치.
    assert names == ["C", "C", "A", "A", "B", "B"]
    types = [s["type"] for s in item["option"]["series"]]
    assert types == ["line", "scatter", "line", "scatter", "line", "scatter"]
    assert item["option"]["legend"]["data"] == ["C", "A", "B"]


def test_legend_colors_inject_into_line_and_itemstyle(base_dir: Path) -> None:
    spec = ChartSpecV1.model_validate(_GROUPED_ECDF)
    item = render_spec_to_echarts(
        spec, base_dir, legend_by_chart={0: {"colors": {"A": "#ff0000"}}}
    )[0]
    a_line = next(
        s for s in item["option"]["series"] if s["name"] == "A" and s["type"] == "line"
    )
    assert a_line["itemStyle"]["color"] == "#ff0000"
    assert a_line["lineStyle"]["color"] == "#ff0000"


def test_legend_hidden_sets_legend_selected(base_dir: Path) -> None:
    spec = ChartSpecV1.model_validate(_GROUPED_ECDF)
    item = render_spec_to_echarts(
        spec, base_dir, legend_by_chart={0: {"hidden": ["B"]}}
    )[0]
    selected = item["option"]["legend"]["selected"]
    assert selected["A"] is True
    assert selected["B"] is False
    assert selected["C"] is True


def test_legend_config_noop_on_chart_without_legend(base_dir: Path) -> None:
    spec = ChartSpecV1.model_validate(
        {
            "version": "1",
            "charts": [
                {
                    "mark": "heatmap",
                    "data": {"source": "heat.parquet"},
                    "encoding": {
                        "x": {"field": "row", "type": "nominal"},
                        "y": {"field": "col", "type": "nominal"},
                        "color": {"field": "value", "type": "quantitative"},
                    },
                }
            ],
        }
    )
    # heatmap 은 legend 키가 없다 — 레전드 오버라이드가 와도 crash 없이 무시.
    item = render_spec_to_echarts(
        spec, base_dir, legend_by_chart={0: {"order": ["x"], "colors": {"x": "#000"}}}
    )[0]
    assert "legend" not in item["option"]
    assert item["option"]["series"][0]["type"] == "heatmap"


def test_resolve_legend_row_ids_returns_group_rows(base_dir: Path) -> None:
    spec = ChartSpecV1.model_validate(_GROUPED_ECDF)
    chart = spec.charts[0]
    assert sorted(resolve_legend_row_ids(chart, base_dir, ["A"])) == [0, 1]
    assert sorted(resolve_legend_row_ids(chart, base_dir, ["B", "C"])) == [2, 3, 4, 5]


def test_resolve_legend_row_ids_empty_without_color(base_dir: Path) -> None:
    spec = ChartSpecV1.model_validate(
        {
            "version": "1",
            "charts": [
                {
                    "mark": "line",
                    "data": {"source": "samples.parquet"},
                    "encoding": {
                        "x": {"field": "idx", "type": "quantitative"},
                        "y": {"field": "value", "type": "quantitative"},
                    },
                }
            ],
        }
    )
    assert resolve_legend_row_ids(spec.charts[0], base_dir, ["anything"]) == []
