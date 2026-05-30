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
