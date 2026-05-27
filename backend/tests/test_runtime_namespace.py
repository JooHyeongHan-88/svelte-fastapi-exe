"""runtime.namespace — memory/disk tier, LRU, isolation, cleanup."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.runtime import namespace  # noqa: E402
from core import result_store  # noqa: E402
from tests._runner import run_tests  # noqa: E402


def _new_client_id() -> str:
    """테스트 격리를 위한 unique client_id."""
    return f"test-{uuid.uuid4().hex[:12]}"


def _setup_threshold(
    memory_threshold: int = 10 * 1024 * 1024, max_vars: int = 20
) -> None:
    os.environ["APP_NAMESPACE_MEMORY_THRESHOLD"] = str(memory_threshold)
    os.environ["APP_NAMESPACE_MAX_VARS"] = str(max_vars)


def test_store_small_object_goes_to_memory() -> None:
    _setup_threshold()
    cid = _new_client_id()
    try:
        ns = namespace.get_namespace(cid, "test-session")
        ref = ns.store("x", [1, 2, 3])

        assert ref.tier == "memory"
        assert ref.name == "x"
        assert ref.type_name == "list"
        assert ns.load("x") == [1, 2, 3]
    finally:
        namespace.cleanup_namespace(cid)


def test_store_large_object_spills_to_disk() -> None:
    _setup_threshold(memory_threshold=50)  # 50 bytes — 어떤 list 든 초과.
    cid = _new_client_id()
    try:
        ns = namespace.get_namespace(cid, "test-session")
        big_obj = list(range(100))
        ref = ns.store("big", big_obj)

        assert ref.tier == "disk", f"50 byte 임계 초과 객체는 disk tier 여야 함: {ref}"
        # disk 에서 다시 로드 가능해야 한다.
        loaded = ns.load("big")
        assert loaded == big_obj
    finally:
        namespace.cleanup_namespace(cid)


def test_overwrite_clears_old_disk_file() -> None:
    _setup_threshold(memory_threshold=50)
    cid = _new_client_id()
    try:
        ns = namespace.get_namespace(cid, "test-session")
        ns.store("x", list(range(100)))
        old_path = ns._entries["x"].disk_path
        assert old_path is not None and old_path.exists()

        # 같은 이름에 작은 값 덮어쓰기 → memory tier, 이전 disk 파일은 삭제되어야 함.
        ns.store("x", "small")
        assert not old_path.exists(), "덮어쓰기 시 이전 disk 파일이 정리되어야 함"
        assert ns._entries["x"].tier == "memory"
    finally:
        namespace.cleanup_namespace(cid)


def test_lru_removes_oldest_when_max_exceeded() -> None:
    """max_vars 초과 시 가장 오래된 변수가 완전 제거된다 (memory + disk)."""
    _setup_threshold(memory_threshold=1024 * 1024, max_vars=3)
    cid = _new_client_id()
    try:
        ns = namespace.get_namespace(cid, "test-session")
        ns.store("a", "small_a")
        ns.store("b", "small_b")
        ns.store("c", "small_c")

        # 4번째: max=3 초과로 가장 오래된 'a' 가 제거된다.
        ns.store("d", "small_d")

        names = {r.name for r in ns.list_refs()}
        assert names == {"b", "c", "d"}, (
            f"가장 오래된 'a' 가 LRU 제거되어야 함. 현재: {names}"
        )
    finally:
        namespace.cleanup_namespace(cid)


def test_lru_load_refreshes_recency() -> None:
    """load() 호출이 LRU 순서를 갱신하여 그 변수는 다음 eviction 대상이 아니어야 한다."""
    _setup_threshold(memory_threshold=1024 * 1024, max_vars=3)
    cid = _new_client_id()
    try:
        ns = namespace.get_namespace(cid, "test-session")
        ns.store("a", "val_a")
        ns.store("b", "val_b")
        ns.store("c", "val_c")

        # 'a' 를 load 하여 다시 최근으로 만듦.
        ns.load("a")

        # 4번째 추가 시 'a' 가 아닌 'b' (다음으로 오래됨) 가 제거되어야 함.
        ns.store("d", "val_d")

        names = {r.name for r in ns.list_refs()}
        assert names == {"a", "c", "d"}, (
            f"load() 가 LRU 순서를 갱신해 'a' 보존, 'b' 제거되어야 함. 현재: {names}"
        )
    finally:
        namespace.cleanup_namespace(cid)


def test_delete_removes_variable() -> None:
    _setup_threshold()
    cid = _new_client_id()
    try:
        ns = namespace.get_namespace(cid, "test-session")
        ns.store("x", [1, 2, 3])
        assert ns.has("x")

        removed = ns.delete("x")
        assert removed is True
        assert not ns.has("x")

        # 다시 delete 는 False.
        assert ns.delete("x") is False
    finally:
        namespace.cleanup_namespace(cid)


def test_cleanup_removes_disk_files() -> None:
    _setup_threshold(memory_threshold=50)
    cid = _new_client_id()
    ns = namespace.get_namespace(cid, "test-session")
    ns.store("big", list(range(100)))
    disk_path = ns._entries["big"].disk_path
    assert disk_path is not None and disk_path.exists()

    namespace.cleanup_namespace(cid)
    assert not disk_path.exists(), "cleanup 후 disk 파일은 제거되어야 함"


def test_session_isolation() -> None:
    """두 client_id 의 namespace 가 서로 격리되어야 한다."""
    _setup_threshold()
    cid_a = _new_client_id()
    cid_b = _new_client_id()
    try:
        ns_a = namespace.get_namespace(cid_a, "session-a")
        ns_b = namespace.get_namespace(cid_b, "session-b")

        ns_a.store("x", "from_a")
        ns_b.store("x", "from_b")

        assert ns_a.load("x") == "from_a"
        assert ns_b.load("x") == "from_b"
        # ns_a 에는 ns_b 의 변수가 보이지 않아야 한다.
        assert {r.name for r in ns_a.list_refs()} == {"x"}
    finally:
        namespace.cleanup_namespace(cid_a)
        namespace.cleanup_namespace(cid_b)


def test_invalid_variable_name_rejected() -> None:
    _setup_threshold()
    cid = _new_client_id()
    try:
        ns = namespace.get_namespace(cid, "test-session")
        raised = False
        try:
            ns.store("123invalid", "x")
        except ValueError:
            raised = True
        assert raised, "Python identifier 가 아니면 ValueError"

        raised2 = False
        try:
            ns.store("with space", "x")
        except ValueError:
            raised2 = True
        assert raised2
    finally:
        namespace.cleanup_namespace(cid)


def test_summarize_format() -> None:
    _setup_threshold()
    cid = _new_client_id()
    try:
        ns = namespace.get_namespace(cid, "test-session")
        assert "비어있음" in ns.summarize()
        ns.store("x", [1, 2])
        out = ns.summarize()
        assert "x" in out
        assert "list" in out
        assert "tier=memory" in out
    finally:
        namespace.cleanup_namespace(cid)


def test_current_namespace_uses_contextvars() -> None:
    """harness 가 set_session_context 호출 후 current_namespace 가 작동해야 한다."""
    _setup_threshold()
    cid = _new_client_id()
    try:
        result_store.set_session_context(cid, "ctx-test")
        ns = namespace.current_namespace()
        ns.store("hello", "world")

        # 같은 cid 로 get_namespace 는 동일 인스턴스 반환해야 한다.
        ns2 = namespace.get_namespace(cid, "ctx-test")
        assert ns2.load("hello") == "world"
    finally:
        namespace.cleanup_namespace(cid)


def test_current_namespace_without_context_raises() -> None:
    """context 없이 호출하면 RuntimeError."""
    result_store.set_session_context("", "")
    raised = False
    try:
        namespace.current_namespace()
    except RuntimeError:
        raised = True
    assert raised


if __name__ == "__main__":
    run_tests(globals())
