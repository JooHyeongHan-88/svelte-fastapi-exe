"""라이브러리 런타임 baseline 도구 모음.

이 모듈은 외부 Python 라이브러리(``APP_ALLOWED_LIBRARIES`` 에 등록된 패키지)를
Agent 가 동적으로 호출할 수 있도록 다음 도구를 제공한다:

* ``inspect_callable``: 함수/클래스 시그니처·docstring 조회
* ``list_module_members``: 모듈 public 멤버 목록
* ``call_function``: 라이브러리 함수 실행 → namespace 저장
* ``eval_expression``: namespace 변수에 대한 짧은 식 평가
* ``exec_code``: 다중 statement Python 코드 실행 (import/할당/제어흐름)
* ``list_namespace``: 현재 세션의 모든 변수 요약
* ``describe_variable``: 특정 변수의 타입·크기·요약
* ``delete_variable``: 변수 제거 (memory + disk)

설계 핵심:
    - ``client_id`` 는 contextvars 로 자동 주입 (LLM 인자에 노출하지 않음).
    - ``call_function`` 의 kwargs 값에 ``"$var"`` 형태 문자열이 있고
      namespace 에 같은 이름 변수가 있으면 자동으로 값으로 치환된다 — 객체
      체이닝(DataFrame → 다음 함수 인자) 시 LLM 이 raw 값을 다시 직렬화할
      필요 없게 한다.
    - 라이브러리 화이트리스트는 ``agent.runtime.resolver`` 가 일괄 적용.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from pathlib import Path
from typing import Annotated, Any

from agent.models import ToolResult
from agent.registries.tools import register_tool
from agent.runtime import evaluator, introspect, namespace, resolver
from core.result_store import (
    adopt_turn_slot,
    artifact_slot,
    current_client_id,
    current_session_title,
    peek_turn_slot,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 상수 — infrastructure tool 이름 모음. harness 가 자동 주입 시 참조한다.
# ---------------------------------------------------------------------------

INSPECT_CALLABLE = "inspect_callable"
LIST_MODULE_MEMBERS = "list_module_members"
CALL_FUNCTION = "call_function"
EVAL_EXPRESSION = "eval_expression"
EXEC_CODE = "exec_code"
LIST_NAMESPACE = "list_namespace"
DESCRIBE_VARIABLE = "describe_variable"
DELETE_VARIABLE = "delete_variable"

INFRASTRUCTURE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        INSPECT_CALLABLE,
        LIST_MODULE_MEMBERS,
        CALL_FUNCTION,
        EVAL_EXPRESSION,
        EXEC_CODE,
        LIST_NAMESPACE,
        DESCRIBE_VARIABLE,
        DELETE_VARIABLE,
    }
)

# exec_code 가 scope 에 주입하는 헬퍼 이름 — namespace 저장 루프에서 silent skip 한다
# (skipped 리스트에 넣으면 매 호출 노이즈, 저장하면 namespace 오염). 예약어로 취급.
_INJECTED_HELPER_NAMES: frozenset[str] = frozenset({"artifact_dir"})


class _ArtifactDirProvider:
    """exec_code 에 주입하는 ``artifact_dir()`` 헬퍼 — 현재 턴 산출물 슬롯을 반환한다.

    ``loop.run_in_executor`` 는 contextvars 를 전파하지 않으므로, 생성 시점(메인
    코루틴)에 client_id/session_title/기존 슬롯을 미리 캡처한다. 워커 스레드에서
    호출돼도 캡처값으로 ``artifact_slot()`` 을 만들 수 있다. 슬롯은 첫 호출에서만
    lazy 생성되므로, artifact_dir() 를 부르지 않은 턴은 빈 폴더를 남기지 않는다.
    """

    def __init__(self) -> None:
        self._client_id = current_client_id()
        self._session_title = current_session_title()
        # 같은 턴에 prior save_artifact 가 이미 슬롯을 만들었으면 그것을 재사용한다.
        self._existing = peek_turn_slot()
        self.created: Path | None = None

    def __call__(self) -> Path:
        if self._existing is not None:
            return self._existing
        if self.created is not None:
            return self.created
        self.created = artifact_slot(self._client_id, self._session_title)
        return self.created


# ---------------------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------------------


def _resolve_kwargs_refs(
    kwargs: dict[str, Any], ns: namespace.SessionNamespace
) -> dict[str, Any]:
    """kwargs 값 중 ``"$varname"`` 형태가 namespace 에 있으면 실제 값으로 치환한다.

    LLM 이 객체(DataFrame 등)를 다음 함수 인자로 넘기는 표준 관용구.
    충돌은 namespace 에 같은 이름이 등록된 경우에만 발생하므로 사실상 안전.
    """
    resolved: dict[str, Any] = {}
    for key, value in kwargs.items():
        if isinstance(value, str) and value.startswith("$") and len(value) > 1:
            ref = value[1:]
            if ns.has(ref):
                resolved[key] = ns.load(ref)
                continue
        resolved[key] = value
    return resolved


def _format_variable_summary(value: Any, *, max_rows: int = 5) -> str:
    """``describe_variable`` 출력 — 타입별 상세 요약."""
    # pandas DataFrame
    try:
        import pandas as pd

        if isinstance(value, pd.DataFrame):
            shape = value.shape
            dtypes = value.dtypes.to_dict()
            dtype_str = ", ".join(f"{k}={v}" for k, v in list(dtypes.items())[:20])
            try:
                head_str = value.head(max_rows).to_string(max_cols=20)
            except Exception as exc:  # noqa: BLE001
                head_str = f"(head 실패: {exc})"
            return (
                f"DataFrame shape={shape}\n"
                f"dtypes: {dtype_str}\n"
                f"head({max_rows}):\n{head_str}"
            )
        if isinstance(value, pd.Series):
            return (
                f"Series len={len(value)}, dtype={value.dtype}\n"
                f"head({max_rows}):\n{value.head(max_rows).to_string()}"
            )
    except ImportError:
        pass

    # numpy ndarray
    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            return (
                f"ndarray shape={value.shape}, dtype={value.dtype}\n"
                f"min={value.min() if value.size else 'n/a'}, "
                f"max={value.max() if value.size else 'n/a'}\n"
                f"first elements: {value.flatten()[:10]}"
            )
    except ImportError:
        pass

    # list / tuple
    if isinstance(value, (list, tuple)):
        type_name = type(value).__name__
        return (
            f"{type_name} len={len(value)}\n"
            f"first {min(max_rows, len(value))}: {value[:max_rows]!r}"
        )

    # dict
    if isinstance(value, dict):
        keys_preview = list(value.keys())[:10]
        return f"dict len={len(value)}\nkeys preview: {keys_preview!r}"

    # 그 외 — repr 길이 제한.
    r = repr(value)
    if len(r) > 1500:
        r = r[:1497] + "..."
    return f"{type(value).__name__}: {r}"


# ---------------------------------------------------------------------------
# 도구 — 조회
# ---------------------------------------------------------------------------


@register_tool(
    description=(
        "허용된 라이브러리의 함수/클래스/모듈 시그니처와 docstring 을 조회한다. "
        "When to use: 함수를 처음 호출하기 전 인자/반환값을 확인해야 할 때. "
        "When NOT to use: 이미 시스템 프롬프트의 'Available Library APIs' 섹션에 "
        "충분한 정보가 있을 때 — 중복 호출은 컨텍스트만 낭비한다. "
        "Returns: 시그니처 + docstring 텍스트."
    ),
    timeout_seconds=5,
)
async def inspect_callable(
    qualified_name: Annotated[
        str,
        "조회할 dotted path (허용 라이브러리에 속해야 함). 형식: '<pkg>.<module>.<name>'. "
        "system prompt 의 'Available Library APIs' 섹션에 나온 실제 이름을 사용하세요.",
    ],
) -> ToolResult:
    """단일 객체의 시그니처/docstring 텍스트를 반환한다."""
    try:
        docs = introspect.collect_api_docs([qualified_name])
    except Exception as exc:  # noqa: BLE001
        return ToolResult(content=f"[inspect_callable 오류] {exc}", is_error=True)

    if not docs:
        return ToolResult(
            content=(
                f"'{qualified_name}' 을 찾을 수 없습니다. "
                "APP_ALLOWED_LIBRARIES 에 속한 dotted path 인지 확인하세요."
            ),
            is_error=True,
        )

    return ToolResult(content=introspect.render_api_docs_section(docs))


@register_tool(
    description=(
        "허용된 라이브러리 모듈의 public 함수/클래스 목록을 조회한다. "
        "When to use: 모듈에 어떤 API 들이 있는지 모를 때 한 번 호출해 탐색. "
        "When NOT to use: 이미 특정 API 를 알고 있을 때(바로 inspect_callable 또는 "
        "call_function 으로 진행). "
        "Returns: 각 멤버의 이름·종류·1줄 docstring."
    ),
    timeout_seconds=5,
)
async def list_module_members(
    module_path: Annotated[
        str,
        "조회할 모듈 dotted path (허용 라이브러리에 속해야 함). "
        "임의의 이름을 추측하지 말고 system prompt 의 'Available Library APIs' "
        "섹션 또는 APP_ALLOWED_LIBRARIES 에 실제 노출된 모듈만 사용하세요.",
    ],
) -> ToolResult:
    """모듈 멤버 목록을 가볍게 펼친 형태로 반환한다."""
    try:
        obj = resolver.resolve(module_path)
    except (resolver.LibraryAccessError, ModuleNotFoundError, AttributeError) as exc:
        return ToolResult(content=f"[list_module_members 오류] {exc}", is_error=True)

    if not inspect.ismodule(obj):
        return ToolResult(
            content=(
                f"'{module_path}' 은 모듈이 아닙니다 ({type(obj).__name__}). "
                "함수/클래스 단일 조회는 inspect_callable 을 사용하세요."
            ),
            is_error=True,
        )

    lines: list[str] = [f"module {module_path} 의 public 멤버:"]
    count = 0
    for name, member in sorted(inspect.getmembers(obj)):
        if name.startswith("_"):
            continue
        # 같은 모듈에서 정의된 것만.
        try:
            member_module = inspect.getmodule(member)
            if member_module is not None and member_module is not obj:
                continue
        except Exception:
            pass

        if inspect.isfunction(member) or inspect.isbuiltin(member):
            kind = "function"
        elif inspect.isclass(member):
            kind = "class"
        elif inspect.ismodule(member):
            kind = "module"
        else:
            continue  # 상수/변수 스킵.

        doc = inspect.getdoc(member) or ""
        first = doc.splitlines()[0] if doc else ""
        lines.append(f"- {name} [{kind}] — {first}".rstrip(" —"))
        count += 1

    if count == 0:
        lines.append("(public 함수·클래스 없음)")

    return ToolResult(content="\n".join(lines))


# ---------------------------------------------------------------------------
# 도구 — 실행 / 평가
# ---------------------------------------------------------------------------


@register_tool(
    description=(
        "허용된 라이브러리의 함수를 실행하고 결과를 세션 namespace 에 저장한다. "
        "When to use: 라이브러리 API 로 작업을 수행하고 그 결과를 후속 단계에서 "
        "재사용할 때. "
        "Expected chaining: call_function(store_as='df') → "
        "eval_expression('df.max()') 또는 describe_variable(name='df'). "
        "kwargs 값에 '$varname' 문자열이 있고 namespace 에 같은 이름 변수가 있으면 "
        "자동으로 그 값으로 치환된다 (DataFrame 등 객체 체이닝용). "
        "store_as 는 Python identifier 형식이어야 한다."
    ),
    slot_prompts={
        "qualified_name": (
            "어떤 함수를 호출할지 dotted path 로 알려주세요 "
            "(허용 라이브러리의 실제 함수 이름)."
        ),
        "kwargs": "함수에 전달할 키워드 인자를 JSON 객체로 알려주세요.",
        "store_as": "결과를 저장할 변수 이름을 정해 주세요 (예: 'df').",
    },
    timeout_seconds=60,
)
async def call_function(
    qualified_name: Annotated[
        str,
        "실행할 함수의 dotted path (허용 라이브러리의 실제 함수). "
        "'Available Library APIs' 섹션에 나온 이름을 사용하고 임의로 추측하지 마세요.",
    ],
    kwargs: Annotated[
        dict[str, Any],
        ("함수에 전달할 키워드 인자 (JSON). '$varname' 으로 namespace 변수 참조 가능."),
    ],
    store_as: Annotated[
        str,
        "결과를 저장할 namespace 변수 이름 (Python identifier).",
    ],
) -> ToolResult:
    """라이브러리 함수를 실행하고 결과를 namespace 에 저장한다."""
    try:
        func = resolver.resolve(qualified_name)
    except (resolver.LibraryAccessError, ModuleNotFoundError, AttributeError) as exc:
        return ToolResult(content=f"[call_function 오류] {exc}", is_error=True)

    if not callable(func):
        return ToolResult(
            content=(
                f"[call_function 오류] '{qualified_name}' 은 호출 가능하지 않습니다 "
                f"({type(func).__name__})."
            ),
            is_error=True,
        )

    try:
        ns = namespace.current_namespace()
    except RuntimeError as exc:
        return ToolResult(content=f"[call_function 오류] {exc}", is_error=True)

    try:
        resolved_kwargs = _resolve_kwargs_refs(kwargs, ns)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            content=f"[call_function 오류] kwargs 해석 실패: {exc}", is_error=True
        )

    try:
        if inspect.iscoroutinefunction(func):
            result = await func(**resolved_kwargs)
        else:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: func(**resolved_kwargs))
    except Exception as exc:  # noqa: BLE001 — 라이브러리 내부 어떤 예외든 포착
        return ToolResult(
            content=(
                f"[call_function 실행 오류] {qualified_name}: "
                f"{type(exc).__name__}: {exc}"
            ),
            is_error=True,
        )

    try:
        ref = ns.store(store_as, result)
    except ValueError as exc:
        return ToolResult(content=f"[call_function 오류] {exc}", is_error=True)

    size_kb = ref.size_bytes / 1024
    size_str = f"{size_kb:.1f}KB" if size_kb < 1024 else f"{size_kb / 1024:.2f}MB"
    summary = (
        f"{store_as} = {ref.type_name} ({size_str}, tier={ref.tier})\n"
        f"preview: {ref.preview}\n"
        f"다음 단계: eval_expression / describe_variable 에서 "
        f"'{store_as}' 로 참조 가능."
    )
    return ToolResult(
        content=summary,
        data={
            "name": ref.name,
            "type_name": ref.type_name,
            "size_bytes": ref.size_bytes,
            "tier": ref.tier,
            "preview": ref.preview,
        },
    )


@register_tool(
    description=(
        "현재 세션 namespace 에 저장된 변수를 사용한 짧은 Python 식을 평가한다. "
        "When to use: 변수에 메서드 호출·연산을 적용해 작은 결과를 얻을 때. "
        "예: 'df.max()', 'df[\"temp\"].mean()', 'len(rows)'. "
        "When NOT to use: import 필요, 새 라이브러리 함수 호출"
        "(call_function 사용), 큰 객체 생성. "
        "Restrictions: import/open/exec/파일IO/네트워크는 차단됨. "
        "store_as 주어지면 결과를 namespace 에 저장한다."
    ),
    slot_prompts={
        "expression": "평가할 Python 식을 알려주세요 (예: df.max()).",
    },
    timeout_seconds=10,
)
async def eval_expression(
    expression: Annotated[
        str, "평가할 Python 식. assignment / statement 는 금지 (eval 의 제약)."
    ],
    store_as: Annotated[
        str,
        "결과를 저장할 namespace 변수 이름. 빈 문자열이면 저장하지 않고 결과만 반환.",
    ] = "",
) -> ToolResult:
    """namespace 변수에 대해 안전 builtins 환경에서 expression 을 평가한다."""
    try:
        ns = namespace.current_namespace()
    except RuntimeError as exc:
        return ToolResult(content=f"[eval_expression 오류] {exc}", is_error=True)

    # namespace 변수를 local scope 로 노출.
    # memory tier 는 그대로, disk tier 는 로드.
    local_scope: dict[str, Any] = {}
    for ref in ns.list_refs():
        try:
            local_scope[ref.name] = ns.load(ref.name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("namespace 변수 '%s' 로드 실패: %s", ref.name, exc)

    try:
        result = evaluator.safe_eval(expression, local_scope)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            content=(
                f"[eval_expression 오류] {type(exc).__name__}: {exc}. "
                "namespace 변수 이름을 list_namespace 로 확인하거나 식을 단순화하세요."
            ),
            is_error=True,
        )

    if store_as:
        try:
            ref = ns.store(store_as, result)
            summary = f"{store_as} = {ref.type_name}\npreview: {ref.preview}"
            return ToolResult(
                content=summary,
                data={
                    "name": ref.name,
                    "type_name": ref.type_name,
                    "tier": ref.tier,
                    "preview": ref.preview,
                },
            )
        except ValueError as exc:
            return ToolResult(content=f"[eval_expression 오류] {exc}", is_error=True)

    # 저장 안 함 — 결과 repr 만 반환.
    try:
        r = repr(result)
    except Exception as exc:  # noqa: BLE001
        r = f"<repr 실패: {exc}>"
    if len(r) > 1500:
        r = r[:1497] + "..."
    return ToolResult(content=r, data={"type_name": type(result).__name__})


# ---------------------------------------------------------------------------
# 도구 — exec_code (다중 statement Python 실행)
# ---------------------------------------------------------------------------


@register_tool(
    description=(
        "다중 statement Python 코드를 namespace 환경에서 실행한다. "
        "When to use: import + 변수 할당 + for 루프 + 함수 정의 등을 한 번에 "
        "수행해야 할 때 (eval_expression 은 식 한 줄만 가능). "
        '예: \'import pandas as pd\\ndf = pd.read_csv("a.csv")\\n'
        "stats = df.describe()'. "
        "Restrictions: exec/eval/compile 차단. import 는 stdlib 안전 모듈 + "
        "APP_ALLOWED_LIBRARIES 만 허용. "
        "Returns: stdout 출력 + 새로 추가/변경된 namespace 변수 요약. "
        "기존 namespace 변수는 자동으로 동일 이름의 local 변수로 노출된다. "
        "Helper: artifact_dir() 를 호출하면 이번 턴 산출물 폴더(pathlib.Path)를 반환한다 — "
        "라이브러리가 파일을 직접 써야 할 때 사용하라. 'result/...' 를 open() 으로 직접 열지 말 것 "
        "(frozen EXE CWD 함정). 산출 경로를 후속 단계에 넘기려면 str 로 변수에 담아라: "
        "out = str(artifact_dir() / 'model.pkl'). 'artifact_dir' 은 예약어라 재할당해도 "
        "namespace 에 저장되지 않는다."
    ),
    slot_prompts={
        "code": "실행할 Python 코드를 알려주세요 (multi-line 가능).",
    },
    timeout_seconds=60,
)
async def exec_code(
    code: Annotated[
        str,
        "실행할 Python 코드. import / 할당 / 제어흐름 / 함수·클래스 정의 모두 가능.",
    ],
) -> ToolResult:
    """다중 statement 코드를 실행하고, 새로 생긴/바뀐 변수를 namespace 에 저장."""
    try:
        ns = namespace.current_namespace()
    except RuntimeError as exc:
        return ToolResult(content=f"[exec_code 오류] {exc}", is_error=True)

    # 기존 namespace 변수를 local scope 에 펼친다. id 를 함께 기록해 변경 감지.
    local_scope: dict[str, Any] = {}
    pre_ids: dict[str, int] = {}
    for ref in ns.list_refs():
        try:
            val = ns.load(ref.name)
            local_scope[ref.name] = val
            pre_ids[ref.name] = id(val)
        except Exception as exc:  # noqa: BLE001
            logger.warning("namespace 변수 '%s' 로드 실패: %s", ref.name, exc)

    # artifact_dir() 헬퍼 주입 — spade 등이 산출물을 직접 디스크에 쓸 경로.
    # contextvars 가 executor 로 전파되지 않으므로 provider 가 지금 값을 캡처한다.
    artifact_dir_provider = _ArtifactDirProvider()
    local_scope["artifact_dir"] = artifact_dir_provider

    # 블로킹 exec 를 executor 로 — 큰 라이브러리 import 가 event loop 를 잡지 않게.
    try:
        loop = asyncio.get_running_loop()
        stdout_text = await loop.run_in_executor(
            None, evaluator.safe_exec, code, local_scope
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            content=f"[exec_code 오류] {type(exc).__name__}: {exc}",
            is_error=True,
        )

    # 스레드에서 새 슬롯을 만들었으면 메인 턴 캐시에 역동기화 — 같은 턴의 후속
    # save_artifact 가 동일 폴더를 공유하게 한다.
    if artifact_dir_provider.created is not None:
        current_slot = peek_turn_slot()
        if current_slot is None:
            adopt_turn_slot(artifact_dir_provider.created)
        elif current_slot != artifact_dir_provider.created:
            # 병렬 서브에이전트가 각자 슬롯을 만들면 한쪽 adopt 가 스킵돼 같은 턴
            # 산출물이 폴더 2곳에 분산된다. manifest 경로는 정확하므로 기능 고장은
            # 아니지만, 진단을 위해 흔적을 남긴다.
            logger.warning(
                "turn_slot 분산 감지: 캐시=%s, exec_code 생성=%s",
                current_slot,
                artifact_dir_provider.created,
            )

    # 신규 또는 reference 가 바뀐 변수만 namespace 에 저장.
    # 모듈/함수/클래스는 직렬화 비용 대비 가치가 낮아 제외.
    saved: list[namespace.VariableRef] = []
    skipped: list[str] = []
    for key, value in list(local_scope.items()):
        if key.startswith("_"):
            continue
        if key in _INJECTED_HELPER_NAMES:
            continue  # 주입 헬퍼(artifact_dir) — 저장도 노이즈도 없이 조용히 건너뛴다.
        if inspect.ismodule(value):
            continue
        if inspect.isfunction(value) or inspect.isclass(value):
            # exec 안에서 정의된 함수/클래스는 local_scope 를 closure 로 잡아
            # pickle 직렬화가 깨진다. 일단 skip.
            skipped.append(f"{key} ({type(value).__name__})")
            continue
        if key in pre_ids and id(value) == pre_ids[key]:
            continue  # 변경 없음
        try:
            ref = ns.store(key, value)
            saved.append(ref)
        except Exception as exc:  # noqa: BLE001
            logger.warning("namespace 변수 '%s' 저장 실패: %s", key, exc)
            skipped.append(f"{key} (저장 실패: {exc})")

    parts: list[str] = []
    if stdout_text:
        s = stdout_text.rstrip("\n")
        if len(s) > 4000:
            s = s[:4000] + "\n... (truncated)"
        parts.append(f"[stdout]\n{s}")
    if saved:
        parts.append(f"[저장된 변수 {len(saved)}개]")
        for r in saved:
            size_kb = r.size_bytes / 1024
            size_str = (
                f"{size_kb:.1f}KB" if size_kb < 1024 else f"{size_kb / 1024:.2f}MB"
            )
            parts.append(f"- {r.name} = {r.type_name} ({size_str}, tier={r.tier})")
    if skipped:
        parts.append(f"[skipped {len(skipped)}개 — 모듈/함수/클래스/직렬화 실패]")
        for s in skipped[:10]:
            parts.append(f"- {s}")
    if not parts:
        parts.append("(stdout / 신규 변수 없음)")

    return ToolResult(
        content="\n".join(parts),
        data={
            "stdout": stdout_text,
            "saved": [r.name for r in saved],
            "skipped": skipped,
        },
    )


# ---------------------------------------------------------------------------
# 도구 — namespace 관리
# ---------------------------------------------------------------------------


@register_tool(
    description=(
        "현재 세션 namespace 의 모든 변수를 한 줄씩 요약 반환한다. "
        "When to use: 어떤 변수가 저장되어 있는지 확인하거나, 다음 단계에서 어떤 "
        "이름으로 참조해야 할지 잊었을 때. "
        "Returns: 이름 / 타입 / 크기 / tier / preview 한 줄씩."
    ),
    timeout_seconds=5,
)
async def list_namespace() -> ToolResult:
    """세션 namespace 의 변수 전체 목록."""
    try:
        ns = namespace.current_namespace()
    except RuntimeError as exc:
        return ToolResult(content=f"[list_namespace 오류] {exc}", is_error=True)

    return ToolResult(
        content=ns.summarize(),
        data={"variables": [r.__dict__ for r in ns.list_refs()]},
    )


@register_tool(
    description=(
        "namespace 변수 한 건의 타입별 상세 요약. "
        "DataFrame: head + dtypes, ndarray: shape + min/max, "
        "list/dict: 길이 + 미리보기. "
        "When to use: 변수 데이터 형태 확인이 필요할 때. "
        "When NOT to use: 이름만 필요시(list_namespace 사용)."
    ),
    slot_prompts={
        "name": "어떤 변수의 상세 요약을 볼지 이름을 알려주세요.",
    },
    timeout_seconds=10,
)
async def describe_variable(
    name: Annotated[str, "namespace 변수 이름."],
) -> ToolResult:
    """변수 한 건의 타입별 상세 요약 반환."""
    try:
        ns = namespace.current_namespace()
    except RuntimeError as exc:
        return ToolResult(content=f"[describe_variable 오류] {exc}", is_error=True)

    try:
        value = ns.load(name)
    except KeyError as exc:
        return ToolResult(content=f"[describe_variable 오류] {exc}", is_error=True)
    except FileNotFoundError as exc:
        return ToolResult(content=f"[describe_variable 오류] {exc}", is_error=True)

    ref = ns.get_ref(name)
    body = _format_variable_summary(value)
    header = f"{name} ({ref.type_name}, {ref.size_bytes} bytes, tier={ref.tier})"
    return ToolResult(content=f"{header}\n{body}")


@register_tool(
    description=(
        "namespace 변수 한 건을 영구 삭제한다 (memory + disk). "
        "When to use: 큰 변수를 명시적으로 정리할 때. "
        "When NOT to use: 세션 종료 시(자동 cleanup)."
    ),
    slot_prompts={
        "name": "삭제할 변수 이름을 알려주세요.",
    },
    timeout_seconds=5,
)
async def delete_variable(
    name: Annotated[str, "namespace 변수 이름."],
) -> ToolResult:
    """변수 삭제 결과 반환."""
    try:
        ns = namespace.current_namespace()
    except RuntimeError as exc:
        return ToolResult(content=f"[delete_variable 오류] {exc}", is_error=True)

    removed = ns.delete(name)
    if not removed:
        return ToolResult(
            content=f"namespace 에 '{name}' 변수가 없었습니다.", is_error=True
        )
    return ToolResult(content=f"변수 '{name}' 삭제됨.")
