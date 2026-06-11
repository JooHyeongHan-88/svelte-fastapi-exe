"""display_chart 의 spec → rendered 흐름 회귀 테스트.

검증 항목:
- charts.spec.json + 사이드카 parquet → charts.json 렌더 후 반환
- legacy 배열 포맷 (`.json` 직접 입력) 은 거부
- spec 검증 실패 / parquet 누락 시 친절한 에러
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 도구 등록 트리거.
import agent.tools.visualize as visualize_module  # noqa: E402, F401
from core import result_store  # noqa: E402
from tests._runner import run_tests  # noqa: E402


def _setup() -> Path:
    """세션 컨텍스트 설정 후 turn_slot 경로 반환."""
    result_store.set_session_context("displaychart1234", "디스플레이차트테스트")
    return result_store.turn_slot()


def _chart(**kwargs):
    return asyncio.run(visualize_module.display_chart(**kwargs))


def _write_spec(slot: Path, spec: dict, filename: str = "charts.spec.json") -> Path:
    path = slot / filename
    path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return path


def _write_parquet(slot: Path, filename: str, df: pl.DataFrame) -> None:
    df.write_parquet(slot / filename)


def _rel_source(slot: Path, filename: str) -> str:
    """slot 폴더의 파일을 'result/...' 형태로 표현."""
    from core.config import RESULT_DIR

    abs_path = slot / filename
    return "result/" + str(abs_path.relative_to(RESULT_DIR)).replace("\\", "/")


def _build_minimal_spec_and_data(slot: Path) -> Path:
    _write_parquet(
        slot,
        "stats.parquet",
        pl.DataFrame({"metric": ["a", "b", "c"], "value": [1.0, 2.0, 3.0]}),
    )
    return _write_spec(
        slot,
        {
            "version": "1",
            "charts": [
                {
                    "mark": "bar",
                    "title": "통계",
                    "data": {"source": "stats.parquet"},
                    "encoding": {
                        "x": {"field": "metric", "type": "nominal"},
                        "y": {"field": "value", "type": "quantitative"},
                    },
                }
            ],
        },
    )


def test_happy_path_writes_rendered_json() -> None:
    slot = _setup()
    spec_path = _build_minimal_spec_and_data(slot)
    src = _rel_source(slot, spec_path.name)

    result = _chart(source=src, title="요약")

    assert result.is_error is False, result.content
    assert result.data["kind"] == "chart"
    assert result.data["src"].endswith("/charts.json")
    assert result.data["spec"].endswith("/charts.spec.json")
    assert result.data["title"] == "요약"

    # spec 보존 + rendered 생성
    assert spec_path.exists()
    rendered_path = slot / "charts.json"
    assert rendered_path.exists()

    rendered = json.loads(rendered_path.read_text(encoding="utf-8"))
    assert isinstance(rendered, list)
    assert len(rendered) == 1
    assert rendered[0]["chart_type"] == "bar"


def test_legacy_json_filename_rejected() -> None:
    slot = _setup()
    # .json 만 있고 .spec.json 이 아니면 거부
    path = slot / "charts.json"
    path.write_text('[{"mark":"bar"}]', encoding="utf-8")

    from core.config import RESULT_DIR

    src = "result/" + str(path.relative_to(RESULT_DIR)).replace("\\", "/")
    result = _chart(source=src)

    assert result.is_error is True
    assert ".spec.json" in result.content


def test_spec_validation_error() -> None:
    slot = _setup()
    spec_path = _write_spec(
        slot,
        {"version": "1", "charts": []},  # min_length=1 위반
    )
    from core.config import RESULT_DIR

    src = "result/" + str(spec_path.relative_to(RESULT_DIR)).replace("\\", "/")
    result = _chart(source=src)

    assert result.is_error is True
    assert "ChartSpecV1" in result.content


def test_missing_parquet_returns_friendly_error() -> None:
    slot = _setup()
    spec_path = _write_spec(
        slot,
        {
            "version": "1",
            "charts": [
                {
                    "mark": "bar",
                    "data": {"source": "no_such.parquet"},
                    "encoding": {
                        "x": {"field": "x", "type": "nominal"},
                        "y": {"field": "y", "type": "quantitative"},
                    },
                }
            ],
        },
    )
    from core.config import RESULT_DIR

    src = "result/" + str(spec_path.relative_to(RESULT_DIR)).replace("\\", "/")
    result = _chart(source=src)

    assert result.is_error is True
    assert "no_such.parquet" in result.content


def test_invalid_path_prefix_rejected() -> None:
    _setup()
    result = _chart(source="workspace/foo.spec.json")
    assert result.is_error is True
    assert "result/" in result.content


def test_histogram_without_bin_auto_corrected() -> None:
    """x.bin 을 생략한 histogram spec 도 자동 보정되어 렌더된다.

    bin=True 는 histogram 의 무조건적 필수값 — LLM 이 스키마 세부를 몰라
    에러→재시도를 반복하던 회귀 케이스.
    """
    from agent.charts.chart_spec import ChartSpecV1

    raw_spec = {
        "version": "1",
        "charts": [
            {
                "mark": "histogram",
                "title": "분포",
                "data": {"source": "values.parquet"},
                "encoding": {"x": {"field": "v", "type": "quantitative"}},
            }
        ],
    }
    # 모델 레벨 — validator 가 bin 을 자동 보정.
    spec = ChartSpecV1.model_validate(raw_spec)
    assert spec.charts[0].encoding.x is not None
    assert spec.charts[0].encoding.x.bin is True

    # e2e — display_chart 를 통과해 실제 렌더까지 성공.
    slot = _setup()
    _write_parquet(
        slot,
        "values.parquet",
        pl.DataFrame({"v": [1.0, 2.0, 2.5, 3.0, 4.0, 4.5]}),
    )
    spec_path = _write_spec(slot, raw_spec, filename="hist.spec.json")
    result = _chart(source=_rel_source(slot, spec_path.name))
    assert result.is_error is False, result.content


def test_missing_parquet_error_lists_session_candidates() -> None:
    """data.source 미발견 에러에 세션 내 실존 parquet 후보가 함께 안내된다."""
    import uuid

    # 고유 cid 로 격리 — 디스크 스캔 fallback 이 이 세션의 parquet 만 잡도록.
    result_store.set_session_context(f"hint{uuid.uuid4().hex[:8]}", "힌트테스트")
    slot = result_store.turn_slot()
    _write_parquet(slot, "real_data.parquet", pl.DataFrame({"v": [1.0, 2.0]}))
    spec_path = _write_spec(
        slot,
        {
            "version": "1",
            "charts": [
                {
                    "mark": "bar",
                    "data": {"source": "wrong_name.parquet"},
                    "encoding": {
                        "x": {"field": "x", "type": "nominal"},
                        "y": {"field": "y", "type": "quantitative"},
                    },
                }
            ],
        },
        filename="hint.spec.json",
    )

    result = _chart(source=_rel_source(slot, spec_path.name))

    assert result.is_error is True
    assert "wrong_name.parquet" in result.content
    assert "세션에서 사용 가능한 parquet" in result.content
    assert "real_data.parquet" in result.content


def test_encoding_type_and_mark_aliases_coerced() -> None:
    """'normal'·'Histogram' 같은 근사 표기는 정식 값으로 정규화된다.

    실 LLM 회귀 케이스 — 사소한 표기 차이가 ValidationError → self-correct
    라운드트립으로 반복 예산을 태우던 시나리오.
    """
    from agent.charts.chart_spec import ChartSpecV1

    spec = ChartSpecV1.model_validate(
        {
            "version": "1",
            "charts": [
                {
                    "mark": "Histogram",
                    "data": {"source": "d.parquet"},
                    "encoding": {
                        "x": {"field": "value", "type": "Quantitative"},
                        "color": {"field": "lambda", "type": "normal"},
                        "y": {
                            "field": "value",
                            "type": "numeric",
                            "aggregate": "avg",
                        },
                    },
                }
            ],
        }
    )
    chart = spec.charts[0]
    assert chart.mark == "histogram"
    assert chart.encoding.x is not None and chart.encoding.x.type == "quantitative"
    assert chart.encoding.color is not None and chart.encoding.color.type == "nominal"
    assert chart.encoding.y is not None
    assert chart.encoding.y.type == "quantitative"
    assert chart.encoding.y.aggregate == "mean"


def test_unknown_encoding_type_still_rejected() -> None:
    """alias 매핑에 없는 진짜 오류 값은 여전히 검증 에러로 드러난다."""
    import pytest
    from pydantic import ValidationError

    from agent.charts.chart_spec import ChartSpecV1

    with pytest.raises(ValidationError):
        ChartSpecV1.model_validate(
            {
                "version": "1",
                "charts": [
                    {
                        "mark": "bar",
                        "data": {"source": "d.parquet"},
                        "encoding": {
                            "x": {"field": "a", "type": "banana"},
                            "y": {"field": "b", "type": "quantitative"},
                        },
                    }
                ],
            }
        )


def test_poisson_legend_scenario_end_to_end() -> None:
    """실 LLM 회귀 시나리오 — 'normal' 타입 + 어긋난 extra_option.legend.data 로도
    그룹 분리 히스토그램이 첫 호출에 렌더된다 (포아송 lambda 레전드 케이스)."""
    import uuid

    result_store.set_session_context(f"poisson{uuid.uuid4().hex[:8]}", "포아송테스트")
    slot = result_store.turn_slot()
    _write_parquet(
        slot,
        "poisson_long.parquet",
        pl.DataFrame(
            {
                "lambda": [5] * 4 + [8] * 4 + [10] * 4,
                "value": [3.0, 4.0, 5.0, 6.0, 6.0, 7.0, 8.0, 9.0, 8.0, 9.0, 11.0, 13.0],
            }
        ),
    )
    spec_path = _write_spec(
        slot,
        {
            "version": "1",
            "charts": [
                {
                    "mark": "histogram",
                    "title": "포아송 분포",
                    "data": {"source": "poisson_long.parquet"},
                    "encoding": {
                        "x": {"field": "value", "type": "quantitative", "bin": True},
                        "color": {"field": "lambda", "type": "normal"},
                    },
                    "extra_option": {
                        "tooltip": {"trigger": "item"},
                        "legend": {
                            "show": True,
                            "data": ["lambda_5", "lambda_8", "lambda_10"],
                        },
                    },
                }
            ],
        },
        filename="poisson.spec.json",
    )

    result = _chart(source=_rel_source(slot, spec_path.name))

    assert result.is_error is False, result.content
    rendered = json.loads((slot / "poisson.json").read_text(encoding="utf-8"))
    option = rendered[0]["option"]
    assert [s["name"] for s in option["series"]] == ["5", "8", "10"]
    assert option["legend"]["data"] == ["5", "8", "10"]


def test_rendered_is_overwritten_on_re_run() -> None:
    """동일 spec 으로 두 번 호출하면 rendered 가 deterministic 하게 재생성된다."""
    slot = _setup()
    spec_path = _build_minimal_spec_and_data(slot)
    from core.config import RESULT_DIR

    src = "result/" + str(spec_path.relative_to(RESULT_DIR)).replace("\\", "/")

    r1 = _chart(source=src)
    r2 = _chart(source=src)
    assert r1.is_error is False and r2.is_error is False

    rendered = json.loads((slot / "charts.json").read_text(encoding="utf-8"))
    assert len(rendered) == 1


if __name__ == "__main__":
    run_tests(globals())
