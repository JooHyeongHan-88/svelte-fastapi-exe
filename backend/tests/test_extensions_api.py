"""확장 enumeration — list_available_extensions() + /api/extensions 회귀 테스트.

UI(``frontend/dist``)가 있는 확장만 목록에 오르고, 선택적 ``extension.json`` 매니페스트로
표시 이름이 꾸며지며, 매니페스트가 없으면 폴더명으로 폴백하는지 검증한다.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import extensions_loader  # noqa: E402
from core.extensions_loader import list_available_extensions  # noqa: E402
from tests._runner import run_tests  # noqa: E402


def _make_extension(
    root: Path, tool: str, *, with_dist: bool, manifest: str | None
) -> None:
    """temp 확장 트리를 만든다 — dist(선택)와 manifest(선택)."""
    tool_dir = root / "extensions" / tool
    if with_dist:
        dist = tool_dir / "frontend" / "dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    else:
        tool_dir.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (tool_dir / "extension.json").write_text(manifest, encoding="utf-8")


def _with_temp_extensions(builder) -> list[dict[str, str]]:
    """temp 디렉터리를 확장 루트로 가장하고 enumeration 을 실행한다."""
    original = extensions_loader._project_root
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        builder(root)
        extensions_loader._project_root = lambda: root
        try:
            return list_available_extensions()
        finally:
            extensions_loader._project_root = original


# ---------------------------------------------------------------------------
# 실제 레포 — evaluator 매니페스트
# ---------------------------------------------------------------------------


def test_real_repo_lists_evaluator_with_manifest_name() -> None:
    # 레포의 evaluator 는 dist + extension.json 이 있으므로 매니페스트 이름으로 노출.
    exts = list_available_extensions()
    by_tool = {e["tool"]: e for e in exts}
    assert "evaluator" in by_tool, [e["tool"] for e in exts]
    assert by_tool["evaluator"]["name"] == "Evaluator"
    assert by_tool["evaluator"]["description"]


# ---------------------------------------------------------------------------
# temp 트리 — 폴백·제외 규칙
# ---------------------------------------------------------------------------


def test_fallback_to_folder_name_when_no_manifest() -> None:
    def build(root: Path) -> None:
        _make_extension(root, "foo", with_dist=True, manifest=None)

    exts = _with_temp_extensions(build)
    by_tool = {e["tool"]: e for e in exts}
    assert "foo" in by_tool
    assert by_tool["foo"]["name"] == "foo"
    assert by_tool["foo"]["description"] == ""


def test_excludes_extension_without_dist() -> None:
    def build(root: Path) -> None:
        _make_extension(root, "noui", with_dist=False, manifest='{"name": "NoUI"}')

    exts = _with_temp_extensions(build)
    assert all(e["tool"] != "noui" for e in exts)


def test_manifest_overrides_name_and_description() -> None:
    def build(root: Path) -> None:
        _make_extension(
            root,
            "bar",
            with_dist=True,
            manifest='{"name": "Bar Tool", "description": "설명", "icon": "x"}',
        )

    exts = _with_temp_extensions(build)
    bar = next(e for e in exts if e["tool"] == "bar")
    assert bar["name"] == "Bar Tool"
    assert bar["description"] == "설명"
    assert bar["icon"] == "x"


def test_corrupt_manifest_falls_back_gracefully() -> None:
    def build(root: Path) -> None:
        _make_extension(root, "broken", with_dist=True, manifest="{not json")

    exts = _with_temp_extensions(build)
    broken = next(e for e in exts if e["tool"] == "broken")
    assert broken["name"] == "broken"


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


def test_endpoint_returns_list() -> None:
    from api.extensions import get_extensions

    result = asyncio.run(get_extensions())
    assert isinstance(result, list)
    assert any(e["tool"] == "evaluator" for e in result)


if __name__ == "__main__":
    run_tests(globals())
