"""api_refs → ApiDoc 추출.

SKILL/AGENT 의 ``api_refs`` Front Matter 에 적힌 dotted-path 를
시그니처·docstring 으로 변환해 system prompt 에 주입한다.

캐시 정책:
    - dev: 모듈 ``__file__`` mtime 변경 시 무효화 (핫리로드).
    - frozen: 한 번 로드되면 영구 캐시 (재시작 전까지 변하지 않음).

모듈 와일드카드(``api_refs: ["sensordx"]``) 는 public 멤버를 펼치되 상한
:data:`_MAX_MEMBERS_PER_MODULE` 개로 잘라 system prompt 폭증을 방지한다.
"""

from __future__ import annotations

import inspect
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.runtime import resolver

logger = logging.getLogger(__name__)

# 한 모듈에서 펼칠 수 있는 최대 멤버 수. 초과 시 상위만 노출하고 로그.
_MAX_MEMBERS_PER_MODULE: int = 30

# 한 docstring 의 최대 라인 수 (system prompt 비용 절감).
_DEFAULT_DOC_MAX_LINES: int = 30
_MODULE_MEMBER_DOC_MAX_LINES: int = 10


@dataclass
class ApiDoc:
    """단일 API 의 문서 — system prompt 주입용 표현."""

    qualified_name: str
    kind: str  # "function" | "class" | "module" | "method" | "value"
    signature: str
    docstring: str


# 캐시: ref → (mtime, ApiDoc 목록)
_doc_cache: dict[str, tuple[float, list[ApiDoc]]] = {}


def collect_api_docs(refs: list[str]) -> list[ApiDoc]:
    """ref 목록을 평면 ApiDoc 리스트로 변환한다.

    해석 실패 / 권한 없음 등은 경고 로그만 남기고 해당 ref 만 skip 한다 —
    SKILL 활성화 자체를 막지 않는다.
    """
    if not refs:
        return []

    is_frozen = getattr(sys, "frozen", False)
    out: list[ApiDoc] = []

    for ref in refs:
        try:
            docs = _get_cached(ref, is_frozen=is_frozen)
            out.extend(docs)
        except resolver.LibraryAccessError as exc:
            logger.warning("api_refs '%s' 접근 거부: %s", ref, exc)
        except (ModuleNotFoundError, AttributeError, ImportError) as exc:
            logger.warning("api_refs '%s' 해석 실패: %s", ref, exc)
        except Exception as exc:  # noqa: BLE001 — 외부 라이브러리 import 오류 다양
            logger.warning("api_refs '%s' 처리 중 예외: %s", ref, exc)

    return out


def render_api_docs_section(docs: list[ApiDoc]) -> str:
    """ApiDoc 리스트를 system prompt 마크다운 섹션으로 렌더링한다."""
    if not docs:
        return ""

    lines: list[str] = [
        "# Available Library APIs",
        "",
        (
            "아래 API 는 백엔드 서버 환경에 설치되어 있으며, "
            "`call_function(qualified_name, kwargs, store_as)` 도구로 실행할 수 있다. "
            "필요하면 `inspect_callable` 로 추가 정보를 조회해도 된다. "
            "결과 객체는 namespace 에 저장되어 이후 "
            "`eval_expression` / `describe_variable` 로 재사용할 수 있다."
        ),
        "",
    ]

    for d in docs:
        header = f"## `{d.qualified_name}` [{d.kind}]"
        if d.signature:
            header += f"{d.signature}"
        lines.append(header)
        if d.docstring:
            lines.append("")
            lines.append(d.docstring)
        lines.append("")

    return "\n".join(lines)


def clear_cache() -> None:
    """테스트용 캐시 클리어."""
    _doc_cache.clear()


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _get_cached(ref: str, *, is_frozen: bool) -> list[ApiDoc]:
    cached = _doc_cache.get(ref)

    if is_frozen and cached is not None:
        return cached[1]

    if cached is not None and not is_frozen:
        current_mtime = _peek_module_mtime(ref)
        if current_mtime > 0 and cached[0] == current_mtime:
            return cached[1]

    docs, mtime = _resolve_to_docs(ref)
    if not docs:
        return docs
    _doc_cache[ref] = (mtime, docs)
    return docs


def _resolve_to_docs(qualified_name: str) -> tuple[list[ApiDoc], float]:
    """resolver 로 객체를 가져와 ApiDoc 리스트로 변환. mtime 도 함께 반환."""
    obj = resolver.resolve(qualified_name)
    mtime = _module_mtime_of(obj)
    kind = _kind_of(obj)

    if kind != "module":
        doc = ApiDoc(
            qualified_name=qualified_name,
            kind=kind,
            signature=_safe_signature(obj),
            docstring=_safe_docstring(obj, max_lines=_DEFAULT_DOC_MAX_LINES),
        )
        return [doc], mtime

    # 모듈 — public 멤버 펼침.
    docs: list[ApiDoc] = []
    for name, member in sorted(inspect.getmembers(obj)):
        if name.startswith("_"):
            continue
        member_kind = _kind_of(member)
        if member_kind == "value":
            continue  # 상수/변수는 노출하지 않음.

        # re-export 제외 — 같은 모듈에서 정의된 것만.
        try:
            member_module = inspect.getmodule(member)
            if member_module is not None and member_module is not obj:
                continue
        except Exception:
            pass

        docs.append(
            ApiDoc(
                qualified_name=f"{qualified_name}.{name}",
                kind=member_kind,
                signature=_safe_signature(member),
                docstring=_safe_docstring(
                    member, max_lines=_MODULE_MEMBER_DOC_MAX_LINES
                ),
            )
        )
        if len(docs) >= _MAX_MEMBERS_PER_MODULE:
            logger.info(
                "module '%s' 의 멤버가 %d개를 초과 — 상위만 노출",
                qualified_name,
                _MAX_MEMBERS_PER_MODULE,
            )
            break

    return docs, mtime


def _kind_of(obj: Any) -> str:
    if inspect.ismodule(obj):
        return "module"
    if inspect.isclass(obj):
        return "class"
    if (
        inspect.iscoroutinefunction(obj)
        or inspect.isasyncgenfunction(obj)
        or inspect.isfunction(obj)
        or inspect.isbuiltin(obj)
    ):
        return "function"
    if inspect.ismethod(obj):
        return "method"
    return "value"


def _safe_signature(obj: Any) -> str:
    try:
        return str(inspect.signature(obj))
    except (ValueError, TypeError):
        return ""


def _safe_docstring(obj: Any, *, max_lines: int) -> str:
    doc = inspect.getdoc(obj) or ""
    if not doc:
        return ""
    lines = doc.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["...(truncated)"]
    return "\n".join(lines)


def _module_mtime_of(obj: Any) -> float:
    try:
        module = inspect.getmodule(obj)
        if module is None:
            return 0.0
        file = getattr(module, "__file__", None)
        if not file:
            return 0.0
        return Path(file).stat().st_mtime
    except (OSError, AttributeError):
        return 0.0


def _peek_module_mtime(ref: str) -> float:
    """ref 의 최상위 모듈 mtime 만 빠르게 읽는다 (캐시 검증용).

    이미 ``sys.modules`` 에 로드된 모듈만 검사 — fully resolve 비용을 피한다.
    """
    parts = ref.split(".")
    for i in range(len(parts), 0, -1):
        mod_path = ".".join(parts[:i])
        mod = sys.modules.get(mod_path)
        if mod is None:
            continue
        file = getattr(mod, "__file__", None)
        if not file:
            continue
        try:
            return Path(file).stat().st_mtime
        except OSError:
            return 0.0
    return 0.0
