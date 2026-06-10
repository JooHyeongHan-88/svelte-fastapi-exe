"""세션 manifest(_artifacts.jsonl) + '# Session Artifacts' 프롬프트 섹션 회귀 테스트.

RESULT_DIR 는 tmp 로 교체하고 매 테스트 후 원복한다 (test_artifact_io.py 패턴).
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import uuid
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent.tools.artifact as artifact_module  # noqa: E402
from agent import harness  # noqa: E402
from agent.runtime import namespace as ns_module  # noqa: E402
from core import result_store  # noqa: E402
from tests._runner import run_tests  # noqa: E402

_TMP_ROOTS: list[Path] = []


@pytest.fixture(autouse=True)
def _restore_result_dir():
    original = result_store.RESULT_DIR
    yield
    result_store.RESULT_DIR = original


def _fresh_tmp() -> Path:
    root = Path(tempfile.mkdtemp(prefix="manifest-test-"))
    _TMP_ROOTS.append(root)
    return root


def _bind(title: str = "분석세션") -> str:
    result_store.RESULT_DIR = _fresh_tmp()
    cid = f"sess-{uuid.uuid4().hex[:12]}"
    ns_module._reset_for_tests()
    result_store.set_session_context(cid, title)
    return cid


def _save(**kwargs):
    return asyncio.run(artifact_module.save_artifact(**kwargs))


# ---------------------------------------------------------------------------
# append / read 라운드트립
# ---------------------------------------------------------------------------


def test_save_artifact_records_manifest_with_description() -> None:
    _bind()
    result = _save(
        filename="report.md",
        kind="markdown",
        content="# 보고서",
        description="2026 Q1 요약 보고서",
    )
    assert result.is_error is False, result.content

    entries = result_store.read_manifest_entries(
        result_store.current_client_id(), limit=10
    )
    assert len(entries) == 1
    assert entries[0]["description"] == "2026 Q1 요약 보고서"
    assert entries[0]["path"].endswith("report.md")
    assert entries[0]["kind"] == "markdown"


def test_manifest_records_parquet_shape() -> None:
    cid = _bind()
    ns = ns_module.current_namespace()
    ns.store("df", pl.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]}))
    result = _save(
        filename="d.parquet", kind="parquet", source="$df", description="원본"
    )
    assert result.is_error is False, result.content

    entries = result_store.read_manifest_entries(cid, limit=10)
    assert entries[0]["rows"] == 3
    assert entries[0]["columns"] == 2


def test_read_manifest_skips_corrupt_lines() -> None:
    cid = _bind()
    manifest = result_store.session_dir() / "_artifacts.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        '{"ts": "20260101-100000", "path": "result/a/b/x.md", "kind": "markdown"}\n'
        "이건 깨진 줄\n"
        '{"ts": "20260101-110000", "path": "result/a/b/y.md", "kind": "markdown"}\n',
        encoding="utf-8",
    )

    entries = result_store.read_manifest_entries(cid, limit=10)
    assert len(entries) == 2
    # 최신순 (ts 내림차순).
    assert entries[0]["path"].endswith("y.md")


def test_read_manifest_merges_renamed_folders() -> None:
    cid = _bind(title="원래제목")
    # 첫 제목으로 저장.
    _save(filename="a.md", kind="markdown", content="x", description="첫번째")
    # 세션 rename — 같은 cid, 새 제목으로 컨텍스트 재설정 후 저장.
    result_store.set_session_context(cid, "바뀐제목")
    _save(filename="b.md", kind="markdown", content="y", description="두번째")

    entries = result_store.read_manifest_entries(cid, limit=10)
    descs = {e["description"] for e in entries}
    assert descs == {"첫번째", "두번째"}


def test_read_manifest_scan_fallback_without_manifest() -> None:
    cid = _bind()
    # manifest 없이 디스크에만 파일 생성.
    slot = (
        result_store.RESULT_DIR
        / result_store.session_dir_name(cid, "분석세션")
        / "20260101-120000"
    )
    slot.mkdir(parents=True, exist_ok=True)
    (slot / "orphan.md").write_text("hi", encoding="utf-8")

    entries = result_store.read_manifest_entries(cid, limit=10)
    assert len(entries) == 1
    assert entries[0]["path"].endswith("orphan.md")


# ---------------------------------------------------------------------------
# _render_session_artifacts_section
# ---------------------------------------------------------------------------


def test_render_section_empty_session() -> None:
    _bind()
    assert harness._render_session_artifacts_section() == ""


def test_render_section_lists_artifacts() -> None:
    _bind()
    _save(filename="report.md", kind="markdown", content="# r", description="요약")
    section = harness._render_session_artifacts_section()
    assert "# Session Artifacts" in section
    assert "report.md" in section
    assert "요약" in section
    assert "load_artifact" in section


def test_render_section_truncates_description() -> None:
    _bind()
    long_desc = "가" * 200
    _save(filename="r.md", kind="markdown", content="x", description=long_desc)
    section = harness._render_session_artifacts_section()
    # 80자로 절단됐는지 — 200자 전체가 들어가면 안 됨.
    assert long_desc not in section
    assert "가" * 80 in section


if __name__ == "__main__":
    run_tests(globals())
