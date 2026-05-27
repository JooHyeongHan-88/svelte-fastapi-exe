"""runtime.introspect — ApiDoc 추출, 캐싱, 모듈 펼침."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.runtime import introspect  # noqa: E402
from tests._runner import run_tests  # noqa: E402


def _setup() -> None:
    os.environ["APP_ALLOWED_LIBRARIES"] = "json,statistics"
    introspect.clear_cache()


def test_collect_single_function() -> None:
    _setup()
    docs = introspect.collect_api_docs(["json.loads"])
    assert len(docs) == 1
    doc = docs[0]
    assert doc.qualified_name == "json.loads"
    assert doc.kind == "function"
    assert doc.signature, "signature 비어있으면 안 됨"
    assert "JSON" in doc.docstring or "json" in doc.docstring.lower()


def test_collect_class() -> None:
    _setup()
    docs = introspect.collect_api_docs(["json.JSONDecoder"])
    assert len(docs) == 1
    assert docs[0].kind == "class"


def test_collect_module_expands_members() -> None:
    _setup()
    docs = introspect.collect_api_docs(["statistics"])
    # statistics 모듈은 mean/median/stdev 등을 정의한다.
    names = {d.qualified_name for d in docs}
    assert "statistics.mean" in names, f"statistics.mean 펼침 누락: {names}"
    assert "statistics.median" in names
    # 모든 펼친 결과는 function 또는 class.
    assert all(d.kind in ("function", "class") for d in docs)


def test_collect_skips_unauthorized() -> None:
    _setup()
    # os 는 허용 외 — 조용히 skip 되어야 한다.
    docs = introspect.collect_api_docs(["os.system", "json.loads"])
    names = {d.qualified_name for d in docs}
    assert "json.loads" in names
    assert "os.system" not in names


def test_collect_empty_refs() -> None:
    _setup()
    assert introspect.collect_api_docs([]) == []


def test_render_section_includes_signatures() -> None:
    _setup()
    docs = introspect.collect_api_docs(["json.loads"])
    rendered = introspect.render_api_docs_section(docs)
    assert "# Available Library APIs" in rendered
    assert "json.loads" in rendered
    # signature 안에 's' 인자 (json.loads 의 첫 인자) 가 있어야 함.
    assert "(" in rendered and ")" in rendered


def test_render_empty_returns_empty() -> None:
    _setup()
    assert introspect.render_api_docs_section([]) == ""


def test_cache_hit_returns_same_object() -> None:
    """같은 ref 를 두 번 collect 하면 캐시된 동일 객체 리스트를 반환해야 한다."""
    _setup()
    docs1 = introspect.collect_api_docs(["json.loads"])
    docs2 = introspect.collect_api_docs(["json.loads"])
    # 캐시 hit 이면 동일 ApiDoc 인스턴스 (list 는 새로 만들 수 있지만 내용 동일).
    assert docs1[0].qualified_name == docs2[0].qualified_name
    assert docs1[0].signature == docs2[0].signature


if __name__ == "__main__":
    run_tests(globals())
