"""open_curation 도구 — 번들 작성·카드 칩·경로 가드 회귀 테스트.

번들 스펙(``<tool>.bundle.json``)과 마크다운 카드(``<tool>.curation.md``)가 현재 턴
슬롯에 쓰이고, 카드가 새 탭 ``?bundle=`` 링크를 담으며, markdown 칩 data 를 반환하는지
검증한다. 경로 가드(비-parquet·미존재·tool 이름)도 함께 본다.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import polars as pl  # noqa: E402

# 도구 등록 트리거 (데코레이터 부수효과).
import agent.tools.curation as curation_module  # noqa: E402
from agent.runtime import namespace as ns_module  # noqa: E402
from core import result_store  # noqa: E402
from tests._runner import run_tests  # noqa: E402

_MAPPING = {
    "select": "item_id",
    "sort": "rank",
    "x": "tkout_time",
    "y": "value",
    "legend": "category",
    "desc": "item_desc",
}


def _setup() -> None:
    """세션 컨텍스트를 새로 설정한다 (turn_slot 캐시 리셋 포함)."""
    ns_module._reset_for_tests()
    result_store.set_session_context("curationtest1234", "큐레이션도구테스트")


def _make_parquet(filename: str = "candidates.parquet") -> str:
    """현재 턴 슬롯에 소형 parquet 을 쓰고 'result/...' 상대 경로를 반환한다."""
    slot = result_store.turn_slot()
    target = slot / filename
    pl.DataFrame(
        {"item_id": ["A", "B"], "rank": [1, 2], "value": [10, 20]}
    ).write_parquet(target)
    return result_store.to_result_relative(target)


def _make_text(filename: str, text: str = "x") -> str:
    """현재 턴 슬롯에 텍스트 파일을 쓰고 'result/...' 상대 경로를 반환한다."""
    slot = result_store.turn_slot()
    target = slot / filename
    target.write_text(text, encoding="utf-8")
    return result_store.to_result_relative(target)


def _open(**kwargs):
    """open_curation 비동기 호출을 동기 실행한다."""
    return asyncio.run(curation_module.open_curation(**kwargs))


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_returns_markdown_chip() -> None:
    _setup()
    src = _make_parquet()
    result = _open(tool="evaluator", sources=[src], mapping=_MAPPING)

    assert result.is_error is False, result.content
    assert result.data is not None
    assert result.data["kind"] == "markdown"
    assert result.data["src"].startswith("/result/"), result.data["src"]
    assert result.data["src"].endswith("/evaluator.curation.md"), result.data["src"]


def test_card_has_bundle_link() -> None:
    _setup()
    src = _make_parquet()
    _open(tool="evaluator", sources=[src], mapping=_MAPPING, title="검토")

    card = result_store.turn_slot() / "evaluator.curation.md"
    text = card.read_text(encoding="utf-8")
    # 카드는 평범한 마크다운 링크 — 새 탭(target=_blank)은 프론트 markdown 렌더러
    # (lib/markdown.js 의 DOMPurify 훅)가 렌더 시점에 부여한다.
    assert "/ext/evaluator/?bundle=" in text
    # bundle 파라미터에 번들 경로가 URL 인코딩되어 들어간다 (slash → %2F).
    assert "evaluator.bundle.json" in text
    assert "%2F" in text
    # 제목이 카드 heading 에 반영.
    assert "# 검토" in text


def test_bundle_records_sources_and_mapping() -> None:
    _setup()
    src = _make_parquet()
    _open(tool="evaluator", sources=[src], mapping=_MAPPING)

    bundle = result_store.turn_slot() / "evaluator.bundle.json"
    assert bundle.exists()
    data = json.loads(bundle.read_text(encoding="utf-8"))
    assert data["tool"] == "evaluator"
    assert data["sources"] == [src]
    assert data["mapping"] == _MAPPING


def test_mapping_optional_defaults_to_empty() -> None:
    _setup()
    src = _make_parquet()
    result = _open(tool="evaluator", sources=[src])

    assert result.is_error is False, result.content
    bundle = result_store.turn_slot() / "evaluator.bundle.json"
    data = json.loads(bundle.read_text(encoding="utf-8"))
    assert data["mapping"] == {}


def test_bundle_records_mark_when_given() -> None:
    # 기본 차트 종류(mark)를 주면 번들에 그대로 통과 기록된다(확장이 해석).
    _setup()
    src = _make_parquet()
    result = _open(tool="evaluator", sources=[src], mapping=_MAPPING, mark="bar")

    assert result.is_error is False, result.content
    bundle = result_store.turn_slot() / "evaluator.bundle.json"
    data = json.loads(bundle.read_text(encoding="utf-8"))
    assert data["mark"] == "bar"


def test_mark_omitted_when_empty() -> None:
    # mark 를 안 주면 번들에 mark 키 자체가 없다(프론트가 기본값 적용).
    _setup()
    src = _make_parquet()
    _open(tool="evaluator", sources=[src], mapping=_MAPPING)

    bundle = result_store.turn_slot() / "evaluator.bundle.json"
    data = json.loads(bundle.read_text(encoding="utf-8"))
    assert "mark" not in data


def test_multiple_sources_all_recorded() -> None:
    _setup()
    src1 = _make_parquet("candidates.parquet")
    src2 = _make_parquet("more.parquet")
    result = _open(tool="evaluator", sources=[src1, src2])

    assert result.is_error is False, result.content
    assert "소스 2개" in result.content
    bundle = result_store.turn_slot() / "evaluator.bundle.json"
    data = json.loads(bundle.read_text(encoding="utf-8"))
    assert data["sources"] == [src1, src2]


# ---------------------------------------------------------------------------
# 경로·인자 가드
# ---------------------------------------------------------------------------


def test_rejects_empty_sources() -> None:
    _setup()
    result = _open(tool="evaluator", sources=[])
    assert result.is_error is True
    assert "sources" in result.content


def test_rejects_non_parquet_source() -> None:
    _setup()
    bad = _make_text("note.md", "# not parquet")
    result = _open(tool="evaluator", sources=[bad])
    assert result.is_error is True
    assert "parquet" in result.content


def test_rejects_missing_file() -> None:
    _setup()
    result = _open(
        tool="evaluator",
        sources=["result/큐레이션도구테스트-curation/20000101-000000/ghost.parquet"],
    )
    assert result.is_error is True


def test_rejects_bad_tool_name() -> None:
    _setup()
    src = _make_parquet()
    for bad in ("Evil", "../x", "ext/evaluator", "tool name"):
        result = _open(tool=bad, sources=[src])
        assert result.is_error is True, f"{bad!r} 가 거부되지 않음"
        assert "tool" in result.content


def test_accepts_list_valued_legend_mapping() -> None:
    # 다중 컬럼 legend 는 list[str] 값으로 허용되고 번들에 그대로 기록된다.
    _setup()
    src = _make_parquet()
    mapping = {"select": "item_id", "legend": ["category", "region"]}
    result = _open(tool="evaluator", sources=[src], mapping=mapping)

    assert result.is_error is False, result.content
    bundle = result_store.turn_slot() / "evaluator.bundle.json"
    data = json.loads(bundle.read_text(encoding="utf-8"))
    assert data["mapping"]["legend"] == ["category", "region"]


def test_rejects_non_string_mapping() -> None:
    _setup()
    src = _make_parquet()
    result = _open(tool="evaluator", sources=[src], mapping={"select": 123})
    assert result.is_error is True
    assert "mapping" in result.content


def test_rejects_non_string_list_mapping() -> None:
    # legend 가 리스트라도 원소가 문자열이 아니면 거부한다.
    _setup()
    src = _make_parquet()
    result = _open(tool="evaluator", sources=[src], mapping={"legend": [1, 2]})
    assert result.is_error is True
    assert "mapping" in result.content


if __name__ == "__main__":
    run_tests(globals())
