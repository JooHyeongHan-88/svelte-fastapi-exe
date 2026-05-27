"""runtime.resolver — ALLOWED_LIBRARIES 화이트리스트 + dotted-path 해석."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.runtime import resolver  # noqa: E402
from tests._runner import run_tests  # noqa: E402


def _setup() -> None:
    os.environ["APP_ALLOWED_LIBRARIES"] = "json,statistics"


def test_allowed_roots_reads_env() -> None:
    _setup()
    roots = resolver.allowed_roots()
    assert roots == frozenset({"json", "statistics"}), (
        f"환경변수가 frozenset 으로 파싱되어야 함: {roots}"
    )


def test_allowed_roots_empty_when_unset() -> None:
    os.environ.pop("APP_ALLOWED_LIBRARIES", None)
    assert resolver.allowed_roots() == frozenset()


def test_allowed_roots_strips_whitespace() -> None:
    os.environ["APP_ALLOWED_LIBRARIES"] = "  json , statistics  ,, "
    assert resolver.allowed_roots() == frozenset({"json", "statistics"})


def test_is_allowed_simple_cases() -> None:
    _setup()
    assert resolver.is_allowed("json.loads") is True
    assert resolver.is_allowed("statistics") is True
    assert resolver.is_allowed("os.system") is False
    assert resolver.is_allowed("") is False


def test_resolve_function_in_module() -> None:
    _setup()
    obj = resolver.resolve("json.loads")
    assert callable(obj)
    assert obj.__name__ == "loads"


def test_resolve_module() -> None:
    _setup()
    obj = resolver.resolve("json")
    import json as json_module

    assert obj is json_module


def test_resolve_submodule() -> None:
    _setup()
    # statistics 는 단일 모듈이라 submodule 케이스 — json.decoder 가 적합.
    obj = resolver.resolve("json.decoder")
    import json.decoder as decoder_module

    assert obj is decoder_module


def test_resolve_rejects_unlisted_root() -> None:
    _setup()
    raised = False
    try:
        resolver.resolve("os.system")
    except resolver.LibraryAccessError as exc:
        raised = True
        assert "허용 목록" in str(exc) or "APP_ALLOWED_LIBRARIES" in str(exc)
    assert raised, "화이트리스트 외 모듈은 LibraryAccessError 로 거부되어야 함"


def test_resolve_attribute_error_for_missing() -> None:
    _setup()
    raised = False
    try:
        resolver.resolve("json.nonexistent_function_xyz")
    except AttributeError:
        raised = True
    assert raised, "존재하지 않는 attr 는 AttributeError 여야 함"


def test_resolve_empty_input_raises() -> None:
    _setup()
    raised = False
    try:
        resolver.resolve("")
    except ValueError:
        raised = True
    assert raised


if __name__ == "__main__":
    run_tests(globals())
