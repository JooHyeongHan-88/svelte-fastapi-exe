"""chart_filter_store — undo/redo 스택 전이 + scope=all 전파 검증."""

from __future__ import annotations

from pathlib import Path


from agent.runtime import chart_filter_store as fs


# ---------------------------------------------------------------------------
# 기본 스택 전이
# ---------------------------------------------------------------------------


def test_initial_state_is_empty_and_no_undo_redo() -> None:
    state = fs.FilterState()
    assert state.current() == {}
    assert not state.can_undo
    assert not state.can_redo


def test_apply_exclude_pushes_new_state(tmp_path: Path) -> None:
    state = fs.FilterState()
    sources = ["data.parquet"]
    state = fs.apply_exclude(state, 0, [3, 7], "single", sources)

    assert state.can_undo
    assert not state.can_redo
    assert state.current() == {"0": [3, 7]}


def test_apply_exclude_merges_with_existing(tmp_path: Path) -> None:
    sources = ["data.parquet"]
    state = fs.FilterState()
    state = fs.apply_exclude(state, 0, [3], "single", sources)
    state = fs.apply_exclude(state, 0, [7], "single", sources)

    # 두 번째 push 는 [3]에 [7]을 추가한 절대 상태.
    assert state.current() == {"0": [3, 7]}
    assert len(state.stack) == 3  # 초기 + 2 push


def test_undo_moves_cursor_back() -> None:
    sources = ["data.parquet"]
    state = fs.FilterState()
    state = fs.apply_exclude(state, 0, [1], "single", sources)
    state = fs.undo(state)

    assert state.current() == {}
    assert not state.can_undo
    assert state.can_redo


def test_redo_moves_cursor_forward() -> None:
    sources = ["data.parquet"]
    state = fs.FilterState()
    state = fs.apply_exclude(state, 0, [1], "single", sources)
    state = fs.undo(state)
    state = fs.redo(state)

    assert state.current() == {"0": [1]}
    assert state.can_undo
    assert not state.can_redo


def test_undo_at_bottom_is_noop() -> None:
    state = fs.FilterState()
    state = fs.undo(state)
    assert not state.can_undo


def test_redo_at_top_is_noop() -> None:
    sources = ["data.parquet"]
    state = fs.FilterState()
    state = fs.apply_exclude(state, 0, [1], "single", sources)
    state = fs.redo(state)
    assert state.current() == {"0": [1]}


def test_new_exclude_trims_redo_tail() -> None:
    sources = ["data.parquet"]
    state = fs.FilterState()
    state = fs.apply_exclude(state, 0, [1], "single", sources)
    state = fs.apply_exclude(state, 0, [2], "single", sources)
    # undo 2단계 → redo tail [1→{0:[1]}, 2→{0:[1,2]}] 생성
    state = fs.undo(state)
    state = fs.undo(state)
    assert state.current() == {}

    # 새 push → redo tail 제거
    state = fs.apply_exclude(state, 0, [9], "single", sources)
    assert not state.can_redo
    assert state.current() == {"0": [9]}


def test_reset_pushes_empty_state() -> None:
    sources = ["data.parquet"]
    state = fs.FilterState()
    state = fs.apply_exclude(state, 0, [1, 2], "single", sources)
    state = fs.reset(state)

    assert state.current() == {}
    assert state.can_undo  # 이전 필터 상태로 undo 가능


def test_reset_then_undo_restores_filter() -> None:
    sources = ["data.parquet"]
    state = fs.FilterState()
    state = fs.apply_exclude(state, 0, [5], "single", sources)
    state = fs.reset(state)
    state = fs.undo(state)

    assert state.current() == {"0": [5]}


# ---------------------------------------------------------------------------
# scope=all 전파
# ---------------------------------------------------------------------------


def test_scope_all_propagates_to_same_source_charts() -> None:
    # 차트 0, 2 는 같은 data.parquet / 차트 1 은 stats.parquet
    sources = ["data.parquet", "stats.parquet", "data.parquet"]
    state = fs.FilterState()
    state = fs.apply_exclude(state, 0, [10, 11], "all", sources)

    exc = state.current()
    # 0 과 2 는 같은 source → 같은 행 제외
    assert exc.get("0") == [10, 11]
    assert exc.get("2") == [10, 11]
    # 1 은 다른 source → 영향 없음
    assert "1" not in exc


def test_scope_single_only_affects_target_chart() -> None:
    sources = ["data.parquet", "data.parquet"]
    state = fs.FilterState()
    state = fs.apply_exclude(state, 0, [5], "single", sources)

    exc = state.current()
    assert exc.get("0") == [5]
    assert "1" not in exc


# ---------------------------------------------------------------------------
# 디스크 라운드트립
# ---------------------------------------------------------------------------


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    sources = ["data.parquet", "stats.parquet"]
    state = fs.FilterState()
    state = fs.apply_exclude(state, 0, [3, 7], "single", sources)
    state = fs.apply_exclude(state, 1, [1], "single", sources)
    state = fs.undo(state)  # cursor=1

    fs.save(tmp_path, state)
    loaded = fs.load(tmp_path)

    assert loaded.cursor == state.cursor
    assert loaded.current() == state.current()
    assert loaded.can_undo == state.can_undo
    assert loaded.can_redo == state.can_redo


def test_load_missing_file_returns_initial_state(tmp_path: Path) -> None:
    state = fs.load(tmp_path)
    assert state.current() == {}
    assert not state.can_undo


def test_load_corrupted_file_returns_initial_state(tmp_path: Path) -> None:
    (tmp_path / "charts.filter.json").write_text("not json!!", encoding="utf-8")
    state = fs.load(tmp_path)
    assert state.current() == {}


def test_str_keyed_exclude_normalizes_on_load(tmp_path: Path) -> None:
    # JSON 은 키가 항상 str — 로드 시 정규화 확인.
    import json

    raw = {
        "version": 1,
        "cursor": 1,
        "stack": [
            {"exclude": {}},
            {"exclude": {"0": [2, 4]}},
        ],
    }
    (tmp_path / "charts.filter.json").write_text(json.dumps(raw), encoding="utf-8")
    state = fs.load(tmp_path)
    assert state.current() == {"0": [2, 4]}
