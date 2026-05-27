"""모듈/함수 dotted-path 해석 + 라이브러리 화이트리스트.

설계:
    - ``APP_ALLOWED_LIBRARIES`` (.env CSV) 로 허용 패키지 루트를 등록한다.
    - ``resolve('sensordx.utils.load_df')`` → 실제 객체 반환.
    - 화이트리스트 외 모듈에 접근하려 하면 :class:`LibraryAccessError` 로 거부 —
      inspect/call/eval 도구 모두 이 함수를 거치므로 단일 보안 경계가 된다.

ALLOWED_ROOTS 는 환경변수에서 매 호출마다 다시 읽는다 (테스트 친화). 운영
환경에서는 환경변수가 변하지 않으므로 오버헤드는 무시 가능.
"""

from __future__ import annotations

import importlib
import os
from typing import Any


class LibraryAccessError(PermissionError):
    """화이트리스트 외 모듈에 접근하려 할 때 발생."""


def allowed_roots() -> frozenset[str]:
    """현재 허용된 라이브러리 루트 패키지 이름 집합.

    환경변수 ``APP_ALLOWED_LIBRARIES`` 에서 콤마로 구분된 패키지 이름을 읽는다.
    """
    raw = os.environ.get("APP_ALLOWED_LIBRARIES", "")
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def is_allowed(qualified_name: str) -> bool:
    """resolve 를 실제 호출하지 않고 화이트리스트만 검사한다."""
    if not qualified_name or not qualified_name.strip():
        return False
    root = qualified_name.split(".", 1)[0]
    return root in allowed_roots()


def resolve(qualified_name: str) -> Any:
    """dotted-path 를 실제 객체로 해석한다.

    Args:
        qualified_name: 'pkg.mod.attr' 형태. 첫 컴포넌트는 ALLOWED_ROOTS 에 있어야 한다.

    Returns:
        해당 객체 (모듈/함수/클래스 등).

    Raises:
        ValueError: 빈 입력.
        LibraryAccessError: 화이트리스트 외 모듈.
        ModuleNotFoundError / AttributeError: 경로가 존재하지 않을 때.
    """
    if not qualified_name or not qualified_name.strip():
        raise ValueError("qualified_name 이 비어 있습니다.")

    parts = qualified_name.split(".")
    root = parts[0]
    roots = allowed_roots()
    if root not in roots:
        raise LibraryAccessError(
            f"'{root}' 은 허용 목록(APP_ALLOWED_LIBRARIES)에 없습니다. "
            f"현재 허용: {sorted(roots) or '(없음)'}"
        )

    # 'sensordx.utils.load_df': sensordx.utils 는 모듈, load_df 는 그 안의 함수.
    # getattr 가 실패하면 (서브패키지일 가능성) import_module 로 한 번 더 시도.
    obj: Any = importlib.import_module(root)
    for i, part in enumerate(parts[1:], start=1):
        try:
            obj = getattr(obj, part)
        except AttributeError as exc:
            module_path = ".".join(parts[: i + 1])
            try:
                obj = importlib.import_module(module_path)
            except ModuleNotFoundError:
                raise AttributeError(
                    f"'{qualified_name}' 의 '{part}' 부분을 해석할 수 없습니다."
                ) from exc
    return obj
