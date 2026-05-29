"""runtime.evaluator — safe_eval / safe_exec 동작 검증.

신뢰된 단일 사용자 데스크탑 앱 가정. exec/eval/compile 만 차단하고
나머지 builtin 은 노출. import 는 stdlib 안전 목록 + APP_ALLOWED_LIBRARIES.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.runtime import evaluator  # noqa: E402
from tests._runner import run_tests  # noqa: E402


# ---------------------------------------------------------------------------
# safe_eval — 식 평가
# ---------------------------------------------------------------------------


def test_arithmetic_allowed() -> None:
    assert evaluator.safe_eval("1 + 2 * 3", {}) == 7


def test_namespace_vars_visible() -> None:
    assert evaluator.safe_eval("x + y", {"x": 10, "y": 5}) == 15


def test_builtin_len_allowed() -> None:
    assert evaluator.safe_eval("len([1,2,3])", {}) == 3


def test_builtin_sum_max_min_allowed() -> None:
    assert evaluator.safe_eval("sum([1,2,3])", {}) == 6
    assert evaluator.safe_eval("max([1,2,3])", {}) == 3
    assert evaluator.safe_eval("min([1,2,3])", {}) == 1


def test_open_now_callable() -> None:
    """신뢰 환경에서 open 은 데이터 파일 읽기에 자주 필요 — 노출되어 있어야 함."""
    assert evaluator.safe_eval("callable(open)", {}) is True


def test_print_now_callable() -> None:
    """exec 안에서 print 가 동작하려면 builtins 에 있어야 함."""
    assert evaluator.safe_eval("callable(print)", {}) is True


def test_getattr_hasattr_callable() -> None:
    """데이터 객체 introspection 에 필요한 reflection builtin 들이 노출."""
    assert evaluator.safe_eval("hasattr('abc', 'upper')", {}) is True
    assert evaluator.safe_eval("getattr('abc', 'upper')()", {}) == "ABC"
    assert evaluator.safe_eval("callable(len)", {}) is True


def test_exec_blocked() -> None:
    """exec 은 재귀 코드 인젝션 위험 — 명시적으로 차단."""
    raised = False
    try:
        evaluator.safe_eval("exec('print(1)')", {})
    except NameError:
        raised = True
    assert raised, "exec 은 차단되어야 함"


def test_eval_blocked() -> None:
    raised = False
    try:
        evaluator.safe_eval("eval('1+1')", {})
    except NameError:
        raised = True
    assert raised, "eval 은 차단되어야 함"


def test_compile_blocked() -> None:
    raised = False
    try:
        evaluator.safe_eval("compile('x=1', '', 'exec')", {})
    except NameError:
        raised = True
    assert raised, "compile 은 차단되어야 함"


def test_assignment_rejected_as_syntax() -> None:
    raised = False
    try:
        evaluator.safe_eval("x = 5", {})
    except SyntaxError:
        raised = True
    assert raised, "assignment 는 eval 의 SyntaxError 여야 함"


def test_method_call_on_namespace_var() -> None:
    result = evaluator.safe_eval("data.upper()", {"data": "hello"})
    assert result == "HELLO"


# ---------------------------------------------------------------------------
# _safe_import — import 후킹
# ---------------------------------------------------------------------------


def test_safe_import_allows_stdlib_math() -> None:
    """math 는 stdlib safe-list 에 있어 항상 import 가능."""
    mod = evaluator._safe_import("math")
    assert mod.pi > 3.14


def test_safe_import_allows_stdlib_json() -> None:
    mod = evaluator._safe_import("json")
    assert mod.dumps({"a": 1}) == '{"a": 1}'


def test_safe_import_blocks_os_by_default() -> None:
    """os 는 stdlib safe-list 에 의도적으로 제외 — system 류 위험 방지."""
    raised = False
    try:
        evaluator._safe_import("os")
    except ImportError:
        raised = True
    assert raised, "os 는 import 차단되어야 함"


def test_safe_import_blocks_subprocess() -> None:
    raised = False
    try:
        evaluator._safe_import("subprocess")
    except ImportError:
        raised = True
    assert raised


def test_safe_import_allows_via_allowed_libraries() -> None:
    """APP_ALLOWED_LIBRARIES 에 등록된 패키지는 import 허용."""
    prev = os.environ.get("APP_ALLOWED_LIBRARIES", "")
    os.environ["APP_ALLOWED_LIBRARIES"] = "statistics_ext_test,json"
    try:
        # json 은 어차피 safe-list 에 있지만 외부 lib 처럼 동작하는지 확인.
        mod = evaluator._safe_import("json")
        assert mod is not None
    finally:
        os.environ["APP_ALLOWED_LIBRARIES"] = prev


def test_safe_import_blocks_relative_import() -> None:
    raised = False
    try:
        evaluator._safe_import("foo", level=1)
    except ImportError:
        raised = True
    assert raised


# ---------------------------------------------------------------------------
# safe_eval + import — eval 안에서 __import__ 사용
# ---------------------------------------------------------------------------


def test_eval_import_stdlib_via_dunder() -> None:
    """eval 안에서 __import__('math') 는 stdlib safe-list 에 있어 통과."""
    result = evaluator.safe_eval("__import__('math').sqrt(16)", {})
    assert result == 4.0


def test_eval_import_blocked_for_disallowed() -> None:
    """eval 안에서 __import__('socket') 등은 ImportError."""
    raised = False
    try:
        evaluator.safe_eval("__import__('socket')", {})
    except ImportError:
        raised = True
    assert raised


# ---------------------------------------------------------------------------
# safe_exec — 다중 statement
# ---------------------------------------------------------------------------


def test_exec_simple_assignment() -> None:
    ns: dict = {}
    evaluator.safe_exec("x = 1 + 2", ns)
    assert ns["x"] == 3


def test_exec_multi_statement() -> None:
    ns: dict = {"data": [1, 2, 3, 4]}
    evaluator.safe_exec(
        "total = sum(data)\ncount = len(data)\nmean = total / count",
        ns,
    )
    assert ns["total"] == 10
    assert ns["count"] == 4
    assert ns["mean"] == 2.5


def test_exec_captures_stdout() -> None:
    out = evaluator.safe_exec("print('hello'); print('world')", {})
    assert "hello" in out
    assert "world" in out


def test_exec_for_loop() -> None:
    ns: dict = {}
    evaluator.safe_exec(
        "result = []\nfor i in range(5):\n    result.append(i * 2)",
        ns,
    )
    assert ns["result"] == [0, 2, 4, 6, 8]


def test_exec_import_stdlib_works() -> None:
    ns: dict = {}
    evaluator.safe_exec(
        "import math\nr = math.sqrt(25)",
        ns,
    )
    assert ns["r"] == 5.0


def test_exec_import_disallowed_blocked() -> None:
    raised = False
    try:
        evaluator.safe_exec("import socket", {})
    except ImportError:
        raised = True
    assert raised


def test_exec_class_definition() -> None:
    """클래스 정의가 동작하려면 __build_class__ 가 노출되어야 함."""
    ns: dict = {}
    evaluator.safe_exec(
        "class Point:\n"
        "    def __init__(self, x, y):\n"
        "        self.x = x\n"
        "        self.y = y\n"
        "p = Point(3, 4)\n"
        "coord = (p.x, p.y)",
        ns,
    )
    assert ns["coord"] == (3, 4)


def test_exec_function_definition() -> None:
    ns: dict = {}
    evaluator.safe_exec(
        "def double(x):\n    return x * 2\n\nresult = double(21)",
        ns,
    )
    assert ns["result"] == 42


def test_exec_exec_inside_blocked() -> None:
    """safe_exec 안에서 다시 exec() 호출은 차단."""
    raised = False
    try:
        evaluator.safe_exec("exec('x = 1')", {})
    except NameError:
        raised = True
    assert raised


# ---------------------------------------------------------------------------
# safe_exec / safe_eval — nested 스코프(genexpr/def)에서 top-level 변수 참조
# globals/locals 분리 시 NameError 가 나던 회귀 방지.
# ---------------------------------------------------------------------------


def test_exec_generator_expression_sees_top_level_var() -> None:
    # 분산/표준편차 계산의 정석: sum((x-mean)**2 for x in values)
    ns: dict = {}
    evaluator.safe_exec(
        "values = [1.0, 2.0, 3.0, 4.0]\n"
        "mean = sum(values) / len(values)\n"
        "variance = sum((x - mean) ** 2 for x in values) / len(values)",
        ns,
    )
    assert ns["mean"] == 2.5
    assert ns["variance"] == 1.25


def test_exec_nested_def_sees_top_level_var() -> None:
    ns: dict = {}
    evaluator.safe_exec(
        "values = [1.0, 2.0, 3.0, 4.0]\n"
        "mean = sum(values) / len(values)\n"
        "def variance():\n"
        "    return sum((x - mean) ** 2 for x in values) / len(values)\n"
        "var = variance()",
        ns,
    )
    assert ns["var"] == 1.25


def test_exec_does_not_leak_builtins_into_namespace() -> None:
    # __builtins__ 주입 후 원상복구되어 namespace 에 남지 않아야 한다.
    ns: dict = {}
    evaluator.safe_exec("x = 1", ns)
    assert "__builtins__" not in ns
    assert ns["x"] == 1


def test_eval_generator_expression_sees_namespace_var() -> None:
    result = evaluator.safe_eval(
        "sum((x - mean) ** 2 for x in values)",
        {"values": [1.0, 2.0, 3.0, 4.0], "mean": 2.5},
    )
    assert result == 5.0


if __name__ == "__main__":
    run_tests(globals())
