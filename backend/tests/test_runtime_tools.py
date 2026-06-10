"""runtime baseline 도구들 — 등록 + 기본 실행 흐름 e2e."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent.tools  # noqa: F401, E402 — register_tool 부수효과 트리거
from agent.registries.tools import get_registered_tool  # noqa: E402
from agent.runtime import namespace  # noqa: E402
from agent.tools import runtime as runtime_tools  # noqa: E402
from core import result_store  # noqa: E402
from tests._runner import run_tests  # noqa: E402


def _setup() -> None:
    os.environ["APP_ALLOWED_LIBRARIES"] = "json,statistics"
    os.environ["APP_NAMESPACE_MEMORY_THRESHOLD"] = str(10 * 1024 * 1024)
    os.environ["APP_NAMESPACE_MAX_VARS"] = "20"


def _bind_session() -> str:
    cid = f"test-{uuid.uuid4().hex[:12]}"
    result_store.set_session_context(cid, "test-session")
    return cid


# 함수 직접 호출 — 데코레이터 등록을 거치지 않으므로 다른 테스트가 registry 를 reset
# 해도 영향받지 않는다. standalone runner / pytest 양쪽에서 동일하게 작동.
async def _call(tool_name: str, **kwargs):
    fn = getattr(runtime_tools, tool_name)
    return await fn(**kwargs)


def test_all_infrastructure_tools_registered() -> None:
    """registry 확인 — 다른 테스트가 _reset_registry_for_tests 를 호출하면
    standalone 모드에서만 신뢰 가능. pytest 모드에서는 skip 또는 무시.
    """
    _setup()
    # 일단 다시 import 해서 decorator 가 재적용되도록 보장 (테스트 순서 의존성 회피).
    import importlib

    from agent.registries.tools import _REGISTRY

    if not all(n in _REGISTRY for n in runtime_tools.INFRASTRUCTURE_TOOL_NAMES):
        importlib.reload(runtime_tools)

    for name in runtime_tools.INFRASTRUCTURE_TOOL_NAMES:
        rt = get_registered_tool(name)
        assert rt is not None, f"{name} 미등록"
        assert rt.sentinel is False, f"{name} 은 sentinel 이 아니어야 함"


def test_inspect_callable_happy_path() -> None:
    _setup()
    cid = _bind_session()
    try:
        result = asyncio.run(_call("inspect_callable", qualified_name="json.loads"))
        assert result.is_error is False
        assert "json.loads" in result.content
    finally:
        namespace.cleanup_namespace(cid)


def test_inspect_callable_unauthorized() -> None:
    _setup()
    cid = _bind_session()
    try:
        result = asyncio.run(_call("inspect_callable", qualified_name="os.system"))
        # 허용 외 — error 이지만 정확한 에러 형태는 docs 가 비어있는 케이스.
        # 우리 구현은 docs 가 비면 별도 메시지를 반환한다.
        assert result.is_error is True
    finally:
        namespace.cleanup_namespace(cid)


def test_list_module_members_happy_path() -> None:
    _setup()
    cid = _bind_session()
    try:
        result = asyncio.run(_call("list_module_members", module_path="statistics"))
        assert result.is_error is False
        assert "mean" in result.content
        assert "median" in result.content
    finally:
        namespace.cleanup_namespace(cid)


def test_call_function_stores_result() -> None:
    _setup()
    cid = _bind_session()
    try:
        # json.dumps({"a": 1}) — 결과 namespace 에 'doc' 으로 저장.
        result = asyncio.run(
            _call(
                "call_function",
                qualified_name="json.dumps",
                kwargs={"obj": {"a": 1, "b": 2}},
                store_as="doc",
            )
        )
        assert result.is_error is False, result.content
        ns = namespace.get_namespace(cid, "test-session")
        assert ns.has("doc")
        loaded = ns.load("doc")
        assert '"a": 1' in loaded
    finally:
        namespace.cleanup_namespace(cid)


def test_call_function_unauthorized_library() -> None:
    _setup()
    cid = _bind_session()
    try:
        result = asyncio.run(
            _call(
                "call_function",
                qualified_name="os.getcwd",
                kwargs={},
                store_as="cwd",
            )
        )
        assert result.is_error is True
        assert "허용" in result.content or "LibraryAccessError" in result.content
    finally:
        namespace.cleanup_namespace(cid)


def test_eval_expression_uses_namespace() -> None:
    _setup()
    cid = _bind_session()
    try:
        ns = namespace.get_namespace(cid, "test-session")
        ns.store("nums", [1, 2, 3, 4, 5])

        result = asyncio.run(
            _call("eval_expression", expression="sum(nums)", store_as="")
        )
        assert result.is_error is False
        assert "15" in result.content
    finally:
        namespace.cleanup_namespace(cid)


def test_eval_expression_store_as_chain() -> None:
    _setup()
    cid = _bind_session()
    try:
        ns = namespace.get_namespace(cid, "test-session")
        ns.store("x", 10)

        result = asyncio.run(
            _call("eval_expression", expression="x * 2", store_as="doubled")
        )
        assert result.is_error is False
        assert ns.load("doubled") == 20
    finally:
        namespace.cleanup_namespace(cid)


def test_eval_expression_blocks_disallowed_import() -> None:
    """os 는 stdlib safe-list 에서 의도적으로 제외 — ImportError 로 거부."""
    _setup()
    cid = _bind_session()
    try:
        result = asyncio.run(
            _call(
                "eval_expression",
                expression="__import__('os')",
                store_as="",
            )
        )
        assert result.is_error is True
        assert "ImportError" in result.content

    finally:
        namespace.cleanup_namespace(cid)


def test_eval_expression_allows_stdlib_import() -> None:
    """math 는 safe-list 에 있음 — __import__ 로 호출 가능."""
    _setup()
    cid = _bind_session()
    try:
        result = asyncio.run(
            _call(
                "eval_expression",
                expression="__import__('math').sqrt(16)",
                store_as="",
            )
        )
        assert result.is_error is False, result.content
        assert "4.0" in result.content
    finally:
        namespace.cleanup_namespace(cid)


def test_list_namespace_outputs() -> None:
    _setup()
    cid = _bind_session()
    try:
        ns = namespace.get_namespace(cid, "test-session")
        ns.store("v1", [1])
        ns.store("v2", {"a": 1})

        result = asyncio.run(_call("list_namespace"))
        assert "v1" in result.content
        assert "v2" in result.content
    finally:
        namespace.cleanup_namespace(cid)


def test_describe_variable_dict() -> None:
    _setup()
    cid = _bind_session()
    try:
        ns = namespace.get_namespace(cid, "test-session")
        ns.store("config", {"host": "localhost", "port": 8765})

        result = asyncio.run(_call("describe_variable", name="config"))
        assert result.is_error is False
        assert "dict" in result.content
        assert "host" in result.content or "port" in result.content
    finally:
        namespace.cleanup_namespace(cid)


def test_describe_variable_missing() -> None:
    _setup()
    cid = _bind_session()
    try:
        result = asyncio.run(_call("describe_variable", name="nonexistent"))
        assert result.is_error is True
    finally:
        namespace.cleanup_namespace(cid)


def test_delete_variable_removes() -> None:
    _setup()
    cid = _bind_session()
    try:
        ns = namespace.get_namespace(cid, "test-session")
        ns.store("temp", "data")

        result = asyncio.run(_call("delete_variable", name="temp"))
        assert result.is_error is False
        assert not ns.has("temp")
    finally:
        namespace.cleanup_namespace(cid)


def test_exec_code_assigns_new_namespace_var() -> None:
    _setup()
    cid = _bind_session()
    try:
        result = asyncio.run(_call("exec_code", code="x = 1 + 2\ny = x * 10"))
        assert result.is_error is False, result.content
        ns = namespace.get_namespace(cid, "test-session")
        assert ns.load("x") == 3
        assert ns.load("y") == 30
    finally:
        namespace.cleanup_namespace(cid)


def test_exec_code_captures_stdout() -> None:
    _setup()
    cid = _bind_session()
    try:
        result = asyncio.run(_call("exec_code", code="print('hello')\nprint('world')"))
        assert result.is_error is False
        assert "hello" in result.content
        assert "world" in result.content
    finally:
        namespace.cleanup_namespace(cid)


def test_exec_code_uses_existing_namespace_var() -> None:
    _setup()
    cid = _bind_session()
    try:
        ns = namespace.get_namespace(cid, "test-session")
        ns.store("nums", [1, 2, 3, 4, 5])

        result = asyncio.run(
            _call(
                "exec_code",
                code="total = sum(nums)\navg = total / len(nums)",
            )
        )
        assert result.is_error is False, result.content
        assert ns.load("total") == 15
        assert ns.load("avg") == 3.0
    finally:
        namespace.cleanup_namespace(cid)


def test_exec_code_import_stdlib_allowed() -> None:
    _setup()
    cid = _bind_session()
    try:
        result = asyncio.run(_call("exec_code", code="import math\nr = math.sqrt(81)"))
        assert result.is_error is False, result.content
        ns = namespace.get_namespace(cid, "test-session")
        assert ns.load("r") == 9.0
    finally:
        namespace.cleanup_namespace(cid)


def test_exec_code_import_disallowed_blocked() -> None:
    _setup()
    cid = _bind_session()
    try:
        result = asyncio.run(_call("exec_code", code="import socket"))
        assert result.is_error is True
        assert "ImportError" in result.content or "허용" in result.content
    finally:
        namespace.cleanup_namespace(cid)


def test_exec_code_modules_not_saved() -> None:
    """import 한 모듈 자체는 namespace 에 저장되지 않아야 함."""
    _setup()
    cid = _bind_session()
    try:
        result = asyncio.run(_call("exec_code", code="import math\nval = math.pi"))
        assert result.is_error is False
        ns = namespace.get_namespace(cid, "test-session")
        assert ns.has("val")
        assert not ns.has("math"), "import 한 모듈은 namespace 에 저장하지 말 것"
    finally:
        namespace.cleanup_namespace(cid)


def test_exec_code_syntax_error_returns_is_error() -> None:
    _setup()
    cid = _bind_session()
    try:
        result = asyncio.run(_call("exec_code", code="this is not valid python"))
        assert result.is_error is True
    finally:
        namespace.cleanup_namespace(cid)


def test_dollar_kwargs_ref_substitution() -> None:
    """call_function 의 kwargs 에 '$varname' 이 있으면 namespace 변수로 치환된다."""
    _setup()
    cid = _bind_session()
    try:
        ns = namespace.get_namespace(cid, "test-session")
        ns.store("payload", {"hello": "world"})

        # json.dumps(obj=$payload) — payload 의 dict 값이 실제 인자로 전달되어야 함.
        result = asyncio.run(
            _call(
                "call_function",
                qualified_name="json.dumps",
                kwargs={"obj": "$payload"},
                store_as="serialized",
            )
        )
        assert result.is_error is False, result.content
        loaded = ns.load("serialized")
        assert '"hello"' in loaded and '"world"' in loaded
    finally:
        namespace.cleanup_namespace(cid)


# ---------------------------------------------------------------------------
# Phase 5 — exec_code 의 artifact_dir() 헬퍼
# ---------------------------------------------------------------------------


def _with_tmp_result_dir(fn) -> None:
    """RESULT_DIR 을 임시 폴더로 두고 fn 을 실행한 뒤 원복·정리한다."""
    import shutil
    import tempfile

    original = result_store.RESULT_DIR
    tmp = Path(tempfile.mkdtemp(prefix="artdir-test-"))
    result_store.RESULT_DIR = tmp
    try:
        fn()
    finally:
        result_store.RESULT_DIR = original
        shutil.rmtree(tmp, ignore_errors=True)


def test_exec_code_artifact_dir_writes_file() -> None:
    _setup()

    def body() -> None:
        cid = _bind_session()
        try:
            # 같은 코루틴(=같은 contextvars 컨텍스트)에서 실행해 production 턴을 모사.
            async def scenario():
                code = (
                    "p = artifact_dir() / 'out.txt'\n"
                    "p.write_text('hello', encoding='utf-8')\n"
                    "saved = str(p)"
                )
                result = await _call("exec_code", code=code)
                return result, result_store.peek_turn_slot()

            result, slot = asyncio.run(scenario())
            assert result.is_error is False, result.content
            assert slot is not None
            assert (slot / "out.txt").read_text(encoding="utf-8") == "hello"
            # 헬퍼는 skipped 노이즈로 새지 않아야 한다.
            assert "artifact_dir" not in result.content
            assert "artifact_dir" not in result.data.get("skipped", [])
            # str 경로는 namespace 에 저장된다.
            ns = namespace.get_namespace(cid, "test-session")
            assert ns.has("saved")
        finally:
            namespace.cleanup_namespace(cid)

    _with_tmp_result_dir(body)


def test_exec_code_then_save_artifact_share_folder() -> None:
    _setup()

    def body() -> None:
        import agent.tools.artifact as artifact_module

        cid = _bind_session()
        try:
            # exec_code 와 save_artifact 를 한 코루틴에서 실행 — production 의 단일 턴과
            # 동일한 contextvars 컨텍스트라 adopt 된 슬롯이 후속 도구에 전파된다.
            async def scenario():
                exec_result = await _call(
                    "exec_code",
                    code="f = artifact_dir() / 'a.txt'\nf.write_text('x', encoding='utf-8')",
                )
                slot_after_exec = result_store.peek_turn_slot()
                save_result = await artifact_module.save_artifact(
                    filename="report.md", kind="markdown", content="# r"
                )
                return exec_result, slot_after_exec, save_result

            exec_result, slot_after_exec, save_result = asyncio.run(scenario())
            assert exec_result.is_error is False, exec_result.content
            assert slot_after_exec is not None
            assert save_result.is_error is False, save_result.content
            # 같은 턴의 save_artifact 가 exec 가 만든 슬롯에 파일을 썼는지 직접 확인 —
            # turn_slot 캐시가 adopt 된 슬롯을 그대로 재사용함을 증명한다.
            assert (slot_after_exec / "report.md").exists()
            assert (slot_after_exec / "a.txt").exists()
        finally:
            namespace.cleanup_namespace(cid)

    _with_tmp_result_dir(body)


if __name__ == "__main__":
    run_tests(globals())
