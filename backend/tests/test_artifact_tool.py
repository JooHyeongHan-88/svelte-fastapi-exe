"""save_artifact 도구 — 검증·저장·turn_slot 재사용 회귀 테스트."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 도구 등록을 트리거 (데코레이터 부수효과).
import agent.tools.artifact as artifact_module  # noqa: E402, F401
from core import result_store  # noqa: E402
from tests._runner import run_tests  # noqa: E402


def _setup() -> None:
    """매 테스트 시작 시 세션 컨텍스트를 새로 설정한다."""
    # uuid 처럼 보이도록 16자 hex 사용 — session_dir_name 이 처음 8자를 prefix 로 쓴다.
    result_store.set_session_context("artifacttest1234", "산출물도구테스트")


def _save(filename: str, content: str, kind: str = "markdown"):
    """save_artifact 비동기 호출을 동기적으로 실행한다."""
    return asyncio.run(
        artifact_module.save_artifact(filename=filename, content=content, kind=kind)
    )


def test_happy_path_markdown_writes_file_and_returns_path() -> None:
    _setup()
    result = _save("report.md", "# 제목\n\n본문입니다.", "markdown")

    assert result.is_error is False
    assert result.data is not None
    assert result.data["kind"] == "markdown"
    assert result.data["filename"] == "report.md"
    assert result.data["path"].startswith("result/"), result.data["path"]
    assert result.data["path"].endswith("/report.md"), result.data["path"]

    # 디스크에 실제로 기록됐는지 확인.
    abs_path = (result_store.turn_slot() / "report.md").resolve()
    assert abs_path.exists()
    assert abs_path.read_text(encoding="utf-8") == "# 제목\n\n본문입니다."


def test_rejects_path_separator_in_filename() -> None:
    _setup()
    for bad in ("sub/dir.md", "sub\\dir.md", "../escape.md"):
        result = _save(bad, "x", "markdown")
        assert result.is_error is True, f"{bad!r} 가 거부되지 않음"
        assert "filename" in result.content or "경로" in result.content


def test_rejects_absolute_path() -> None:
    _setup()
    # Windows 절대경로.
    result = _save("C:\\evil.md", "x", "markdown")
    assert result.is_error is True


def test_rejects_kind_extension_mismatch() -> None:
    _setup()
    result = _save("data.json", "# md content", kind="markdown")
    assert result.is_error is True
    assert "확장자" in result.content


def test_rejects_invalid_json_for_json_kind() -> None:
    _setup()
    result = _save("data.json", "{invalid json", kind="json")
    assert result.is_error is True
    assert "JSON" in result.content


def test_accepts_valid_json_for_json_kind() -> None:
    _setup()
    payload = {"x": 1, "y": [1, 2, 3]}
    result = _save("data.json", json.dumps(payload), kind="json")
    assert result.is_error is False
    assert result.data["kind"] == "json"


def test_turn_slot_reused_across_multiple_saves() -> None:
    _setup()
    first = _save("a.md", "AAA", "markdown")
    second = _save("b.md", "BBB", "markdown")

    # data.path 의 디렉터리(부모) 부분이 동일해야 한다.
    parent_a = first.data["path"].rsplit("/", 1)[0]
    parent_b = second.data["path"].rsplit("/", 1)[0]
    assert parent_a == parent_b, (
        f"같은 턴의 두 save_artifact 는 동일 ts 폴더를 공유해야 한다: {parent_a} vs {parent_b}"
    )


def test_rejects_empty_filename() -> None:
    _setup()
    result = _save("", "x", "markdown")
    assert result.is_error is True
    assert "filename" in result.content


def test_markdown_response_includes_display_hint() -> None:
    _setup()
    result = _save("hint.md", "# hi", "markdown")
    assert result.is_error is False
    assert "display_markdown" in result.content


if __name__ == "__main__":
    run_tests(globals())
