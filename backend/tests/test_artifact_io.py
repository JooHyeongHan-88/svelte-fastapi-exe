"""list_artifacts / load_artifact 도구 + 경로 해석 헬퍼 회귀 테스트.

RESULT_DIR 는 tmp_path 로 monkeypatch 해 실제 result/ 오염을 피한다
(test_chart_api.py 패턴 준용). 단, result_store 가 import 시점에 RESULT_DIR 을
상수로 캡처하므로, monkeypatch 는 모듈 속성을 직접 교체한다.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent.tools.artifact_io as artifact_io  # noqa: E402
from agent.runtime import namespace as ns_module  # noqa: E402
from core import result_store  # noqa: E402
from tests._runner import run_tests  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_result_dir():
    """RESULT_DIR 전역을 매 테스트 후 원복한다.

    _bind 가 result_store.RESULT_DIR 를 tmp 로 교체하므로, 복원하지 않으면
    이후 다른 테스트 파일(같은 프로세스)이 삭제된 tmp 경로를 가리켜 실패한다.
    standalone _runner 는 이 파일만 실행하므로 fixture 부재로도 누수가 무해하다.
    """
    original = result_store.RESULT_DIR
    yield
    result_store.RESULT_DIR = original


def _bind(tmp_root: Path, title: str = "분석세션") -> str:
    """RESULT_DIR 을 tmp 로 돌리고 새 세션 컨텍스트를 바인딩한다.

    artifact_io 가 from-import 한 iter_session_dirs/resolve_result_path 등은
    result_store 모듈 네임스페이스에서 실행되므로, 모듈 전역만 교체하면 된다.
    """
    result_store.RESULT_DIR = tmp_root
    cid = f"sess-{uuid.uuid4().hex[:12]}"
    ns_module._reset_for_tests()
    result_store.set_session_context(cid, title)
    return cid


def _make_slot(cid: str, title: str = "분석세션", ts: str = "20260101-120000") -> Path:
    """특정 타임스탬프 슬롯을 강제 생성한다 (정렬·다중 폴더 테스트용)."""
    slot = result_store.RESULT_DIR / result_store.session_dir_name(cid, title) / ts
    slot.mkdir(parents=True, exist_ok=True)
    return slot


# ---------------------------------------------------------------------------
# resolve_result_path
# ---------------------------------------------------------------------------


def test_resolve_result_path_happy() -> None:
    tmp = _fresh_tmp()
    cid = _bind(tmp)
    slot = _make_slot(cid)
    (slot / "data.parquet").write_bytes(b"x")
    rel = result_store.to_result_relative(slot / "data.parquet")

    resolved, err = result_store.resolve_result_path(rel)
    assert err is None, err
    assert resolved is not None and resolved.name == "data.parquet"


def test_resolve_result_path_rejects_traversal() -> None:
    tmp = _fresh_tmp()
    _bind(tmp)
    resolved, err = result_store.resolve_result_path("result/../secret.txt")
    assert resolved is None
    assert err is not None


def test_resolve_result_path_rejects_non_result_prefix() -> None:
    tmp = _fresh_tmp()
    _bind(tmp)
    resolved, err = result_store.resolve_result_path("workspace/data.parquet")
    assert resolved is None
    assert "result/" in (err or "")


def test_resolve_result_path_missing_file() -> None:
    tmp = _fresh_tmp()
    cid = _bind(tmp)
    _make_slot(cid)
    resolved, err = result_store.resolve_result_path(
        "result/분석세션-" + cid[:8] + "/20260101-120000/nope.parquet"
    )
    assert resolved is None
    assert "찾을 수 없습니다" in (err or "")


# ---------------------------------------------------------------------------
# iter_session_dirs — 세션 rename 으로 cid8 폴더 여러 개
# ---------------------------------------------------------------------------


def test_iter_session_dirs_collects_renamed_folders() -> None:
    tmp = _fresh_tmp()
    cid = _bind(tmp, title="원래제목")
    _make_slot(cid, title="원래제목")
    _make_slot(cid, title="바뀐제목")

    dirs = result_store.iter_session_dirs(cid)
    names = sorted(p.name for p in dirs)
    assert len(dirs) == 2, names
    assert all(n.endswith(f"-{cid[:8]}") for n in names)


# ---------------------------------------------------------------------------
# list_artifacts
# ---------------------------------------------------------------------------


def test_list_artifacts_empty() -> None:
    tmp = _fresh_tmp()
    _bind(tmp)
    result = asyncio.run(artifact_io.list_artifacts())
    assert result.is_error is False
    assert "없습니다" in result.content


def test_list_artifacts_sorted_and_excludes_derived() -> None:
    tmp = _fresh_tmp()
    cid = _bind(tmp)
    slot = _make_slot(cid)
    (slot / "report.md").write_text("# 보고서", encoding="utf-8")
    pl.DataFrame({"a": [1, 2, 3]}).write_parquet(slot / "data.parquet")
    # 파생물 — 목록에서 제외돼야 함.
    (slot / "charts.json").write_text("[]", encoding="utf-8")
    (slot / "charts.filter.json").write_text("{}", encoding="utf-8")

    result = asyncio.run(artifact_io.list_artifacts())
    assert result.is_error is False
    paths = [a["path"] for a in result.data["artifacts"]]
    assert any(p.endswith("/data.parquet") for p in paths)
    assert any(p.endswith("/report.md") for p in paths)
    assert not any("charts.json" in p for p in paths)
    assert not any("charts.filter.json" in p for p in paths)

    # parquet 메타 — rows/cols 채워짐.
    pq = next(a for a in result.data["artifacts"] if a["path"].endswith(".parquet"))
    assert pq["rows"] == 3 and pq["columns"] == 1


def test_list_artifacts_kind_filter() -> None:
    tmp = _fresh_tmp()
    cid = _bind(tmp)
    slot = _make_slot(cid)
    (slot / "a.md").write_text("x", encoding="utf-8")
    pl.DataFrame({"a": [1]}).write_parquet(slot / "b.parquet")

    result = asyncio.run(artifact_io.list_artifacts(kind="parquet"))
    paths = [a["path"] for a in result.data["artifacts"]]
    assert len(paths) == 1 and paths[0].endswith("b.parquet")


def test_list_artifacts_excludes_namespace_dir() -> None:
    tmp = _fresh_tmp()
    cid = _bind(tmp)
    session_dir = result_store.RESULT_DIR / result_store.session_dir_name(
        cid, "분석세션"
    )
    ns_dir = session_dir / "_namespace"
    ns_dir.mkdir(parents=True, exist_ok=True)
    (ns_dir / "df.pkl").write_bytes(b"x")
    # 실제 산출물도 하나.
    slot = _make_slot(cid)
    (slot / "real.txt").write_text("hi", encoding="utf-8")

    result = asyncio.run(artifact_io.list_artifacts())
    paths = [a["path"] for a in result.data["artifacts"]]
    assert any(p.endswith("real.txt") for p in paths)
    assert not any("_namespace" in p for p in paths)


# ---------------------------------------------------------------------------
# load_artifact
# ---------------------------------------------------------------------------


def test_load_artifact_parquet_to_namespace() -> None:
    tmp = _fresh_tmp()
    cid = _bind(tmp)
    slot = _make_slot(cid)
    pl.DataFrame({"a": [1, 2], "b": [3, 4]}).write_parquet(slot / "d.parquet")
    rel = result_store.to_result_relative(slot / "d.parquet")

    result = asyncio.run(artifact_io.load_artifact(path=rel, store_as="df"))
    assert result.is_error is False, result.content
    ns = ns_module.current_namespace()
    assert ns.has("df")
    loaded = ns.load("df")
    assert loaded.shape == (2, 2)


def test_load_artifact_parquet_requires_store_as() -> None:
    tmp = _fresh_tmp()
    cid = _bind(tmp)
    slot = _make_slot(cid)
    pl.DataFrame({"a": [1]}).write_parquet(slot / "d.parquet")
    rel = result_store.to_result_relative(slot / "d.parquet")

    result = asyncio.run(artifact_io.load_artifact(path=rel))
    assert result.is_error is True
    assert "store_as" in result.content


def test_load_artifact_json_preview_without_store() -> None:
    tmp = _fresh_tmp()
    cid = _bind(tmp)
    slot = _make_slot(cid)
    (slot / "spec.json").write_text('{"k": 42}', encoding="utf-8")
    rel = result_store.to_result_relative(slot / "spec.json")

    result = asyncio.run(artifact_io.load_artifact(path=rel))
    assert result.is_error is False
    assert "42" in result.content


def test_load_artifact_markdown_to_namespace() -> None:
    tmp = _fresh_tmp()
    cid = _bind(tmp)
    slot = _make_slot(cid)
    (slot / "r.md").write_text("# 제목\n본문", encoding="utf-8")
    rel = result_store.to_result_relative(slot / "r.md")

    result = asyncio.run(artifact_io.load_artifact(path=rel, store_as="report"))
    assert result.is_error is False
    ns = ns_module.current_namespace()
    assert ns.load("report").startswith("# 제목")


def test_load_artifact_missing_file_guides_to_list() -> None:
    tmp = _fresh_tmp()
    cid = _bind(tmp)
    _make_slot(cid)
    result = asyncio.run(
        artifact_io.load_artifact(
            path=f"result/분석세션-{cid[:8]}/20260101-120000/ghost.parquet",
            store_as="df",
        )
    )
    assert result.is_error is True
    assert "list_artifacts" in result.content


# ---------------------------------------------------------------------------
# tmp 디렉터리 헬퍼 — standalone runner 는 pytest fixture 가 없으므로 직접 생성
# ---------------------------------------------------------------------------

_TMP_ROOTS: list[Path] = []


def _fresh_tmp() -> Path:
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="artio-test-"))
    _TMP_ROOTS.append(root)
    return root


if __name__ == "__main__":
    run_tests(globals())
