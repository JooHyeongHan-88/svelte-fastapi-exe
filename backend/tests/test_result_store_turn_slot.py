"""result_store.turn_slot — 같은 턴 내 동일 폴더 재사용 / 새 턴 시 새 폴더 할당."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import result_store  # noqa: E402
from tests._runner import run_tests  # noqa: E402


def _setup() -> None:
    """매 테스트 시작 시 contextvars 초기 상태를 보장한다."""
    result_store.set_session_context("test-client-id-abcdef", "테스트 세션")


def test_turn_slot_returns_same_path_within_turn() -> None:
    _setup()

    first = result_store.turn_slot()
    second = result_store.turn_slot()

    assert first == second, "같은 턴 내 turn_slot 호출은 동일 Path 를 반환해야 한다"
    assert first.exists(), "turn_slot 은 즉시 디스크에 폴더를 생성해야 한다"
    assert first.is_dir()


def test_set_session_context_resets_slot_cache() -> None:
    _setup()

    first = result_store.turn_slot()
    # 새 턴 진입 — 같은 client_id 라도 캐시는 리셋되어야 한다.
    # 시간이 흐르지 않으면 ts 폴더명이 같아 동일 Path 가 될 수도 있으므로 client_id 를 바꿔
    # session_dir 자체를 분리한다.
    result_store.set_session_context("test-client-id-xxxxxx", "다른 세션")
    second = result_store.turn_slot()

    assert first != second, (
        "set_session_context 이후 turn_slot 은 새 Path 를 반환해야 한다"
    )


def test_turn_slot_path_is_under_session_dir() -> None:
    _setup()

    slot = result_store.turn_slot()
    expected_session = result_store.session_dir()

    assert slot.parent == expected_session, (
        f"turn_slot Path 는 session_dir 직속이어야 한다: {slot} vs {expected_session}"
    )


if __name__ == "__main__":
    run_tests(globals())
