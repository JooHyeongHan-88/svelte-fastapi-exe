"""eval_expression / exec_code 의 builtins 환경.

설계 원칙: 단일 사용자 로컬 .exe 앱이라는 위협 모델에 맞춘 균형 잡힌 가드.

    - 데이터 분석에 필요한 거의 모든 builtin (open, print, hasattr, getattr,
      callable, vars, dir, ... 포함) 노출.
    - ``import`` 는 stdlib 안전 목록 + ``APP_ALLOWED_LIBRARIES`` 만 허용.
    - ``exec`` / ``eval`` / ``compile`` 만 차단 (재귀적 코드 인젝션 방지).
    - 다중 statement 실행은 :func:`safe_exec` 으로 별도 제공.

이것은 진정한 sandbox 가 아니라 LLM 실수·runaway execution 방지 가드다.
적대적 외부 사용자를 가정하지 않는다 (단일 사용자 로컬 데스크탑 앱).
"""

from __future__ import annotations

import builtins
import contextlib
import io
import logging
from typing import Any

from agent.runtime import resolver

logger = logging.getLogger(__name__)


# 코드 인젝션 가능성이 있는 builtin — 명시적으로 차단.
_BLOCKED_BUILTIN_NAMES: frozenset[str] = frozenset(
    {
        "exec",
        "eval",
        "compile",
    }
)


# stdlib 중 import 항상 허용 — 데이터 분석/유틸리티에 자주 쓰이는 모듈.
# os / sys / subprocess / socket / shutil 등 시스템 조작·외부 통신 모듈은
# 의도적으로 제외 (LLM runaway 방지). 필요하면 .env 의 APP_ALLOWED_LIBRARIES
# 에 추가하면 동일 경로로 허용된다.
_STDLIB_ALWAYS_ALLOWED: frozenset[str] = frozenset(
    {
        # 수치/통계
        "math",
        "statistics",
        "decimal",
        "fractions",
        "random",
        "cmath",
        # 데이터 컨테이너 / 알고리즘
        "collections",
        "itertools",
        "functools",
        "operator",
        "heapq",
        "bisect",
        "array",
        # 직렬화
        "json",
        "csv",
        "base64",
        # 시간
        "datetime",
        "time",
        "calendar",
        "zoneinfo",
        # 경로/IO
        "pathlib",
        "io",
        "tempfile",
        # 텍스트
        "re",
        "string",
        "textwrap",
        "unicodedata",
        "difflib",
        # 타입/구조
        "typing",
        "dataclasses",
        "enum",
        # 기타 유틸리티
        "uuid",
        "hashlib",
        "copy",
        "pprint",
        "warnings",
    }
)


def _safe_import(
    name: str,
    globals_: dict[str, Any] | None = None,
    locals_: dict[str, Any] | None = None,
    fromlist: tuple[str, ...] = (),
    level: int = 0,
) -> Any:
    """import 후킹 — stdlib safe-list + ``APP_ALLOWED_LIBRARIES`` 만 통과.

    Args:
        name: import 대상 모듈 dotted-path (예: 'pandas.core.api').
        globals_: 호출 frame 의 globals (Python 이 자동 주입).
        locals_: 호출 frame 의 locals.
        fromlist: ``from X import (...)`` 의 우측 이름들.
        level: 상대 import 레벨 (양수면 상대 import → 차단).

    Returns:
        실제 import 된 모듈 객체.

    Raises:
        ImportError: 허용 목록에 없는 패키지 또는 상대 import.
    """
    if level != 0:
        raise ImportError("상대 import 는 허용되지 않습니다.")

    root = name.split(".")[0]
    if root in _STDLIB_ALWAYS_ALLOWED or root in resolver.allowed_roots():
        return builtins.__import__(name, globals_, locals_, fromlist, level)

    raise ImportError(
        f"'{name}' 패키지는 import 허용 목록에 없습니다. "
        f"외부 라이브러리는 .env 의 APP_ALLOWED_LIBRARIES 에, "
        f"표준 라이브러리는 evaluator._STDLIB_ALWAYS_ALLOWED 에 추가하세요."
    )


def _build_safe_builtins() -> dict[str, Any]:
    """차단 목록 외 모든 public builtin 노출. ``__import__`` 만 후킹으로 교체.

    클래스 정의에 필요한 ``__build_class__``, name 표시용 ``__name__`` 등 일부
    dunder 는 exec 안에서 정상 동작을 위해 명시적으로 포함한다.
    """
    result: dict[str, Any] = {}
    for name in dir(builtins):
        if name.startswith("_"):
            continue
        if name in _BLOCKED_BUILTIN_NAMES:
            continue
        result[name] = getattr(builtins, name)

    # exec() 안에서 'class Foo: ...' 정의가 동작하려면 __build_class__ 필요.
    result["__build_class__"] = builtins.__build_class__
    result["__import__"] = _safe_import
    result["__name__"] = "__sandbox__"

    return result


SAFE_BUILTINS: dict[str, Any] = _build_safe_builtins()


def safe_eval(expression: str, namespace: dict[str, Any]) -> Any:
    """제한된 builtins 환경에서 expression 한 줄을 평가한다.

    Args:
        expression: 평가할 Python 식. assignment / statement 는 :class:`SyntaxError`.
        namespace: 평가 환경에 노출할 변수 dict (local scope 로 사용).

    Returns:
        평가 결과.

    Raises:
        SyntaxError: assignment 등 statement 가 들어왔을 때.
        NameError: 정의되지 않은 이름.
        ImportError: import 허용 목록 외 패키지.
        그 외 평가 중 발생한 예외 (TypeError, ValueError 등) 그대로 전파.
    """
    return eval(  # noqa: S307 — 의도된 safe-eval, builtins 제한됨
        expression,
        {"__builtins__": SAFE_BUILTINS},
        namespace,
    )


def safe_exec(code: str, namespace: dict[str, Any]) -> str:
    """다중 statement Python 코드를 실행하고 stdout 을 캡쳐해 반환한다.

    ``import`` / 변수 할당 / for 루프 / if / 함수/클래스 정의 모두 가능.
    실행 결과로 추가/수정된 변수는 ``namespace`` dict 에 그대로 남으므로
    호출자가 직접 조회해 후처리한다.

    Args:
        code: 실행할 Python 코드 (multi-line, multi-statement OK).
        namespace: 실행 환경의 local scope. 실행 후 새 변수가 추가될 수 있다.

    Returns:
        실행 중 print() 등으로 stdout 에 출력된 텍스트 (없으면 빈 문자열).

    Raises:
        SyntaxError: 코드 파싱 실패.
        ImportError: 허용 외 패키지 import 시도.
        그 외 실행 중 예외 (NameError, AttributeError 등) 그대로 전파.
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(  # noqa: S102 — 의도된 safe-exec, builtins 제한됨
            code,
            {"__builtins__": SAFE_BUILTINS},
            namespace,
        )
    return buf.getvalue()
