"""Tool 데코레이터 기반 등록 시스템 + 런타임 레지스트리.

설계 원칙:
    - "파이썬 async 함수 1개 = Tool 1개". 클래스 boilerplate 제거.
    - 함수 시그니처(`Annotated[T, "설명"]`)에서 JSON Schema 와 Pydantic
      validator 를 동적 생성 — 새 API 등록 비용을 최소화한다.
    - PLANNER / SUB_AGENT 같은 sentinel 도구는 `sentinel=True` 로 표시 →
      harness 가 tool_call 단계에서 가로채므로 실제 fn 은 호출되지 않는다.
    - 기존 호출자(`harness.py`)가 사용하는 `ToolRegistry` 인터페이스
      (`.get / .names / .specs`) 는 그대로 유지 — 내부 구현만 데코레이터로 전환.

사용 예:
    @register_tool(
        description="매출 데이터 조회",
        slot_prompts={"date_from": "조회 시작일(YYYY-MM-DD)을 알려주세요"},
        timeout_seconds=10,
    )
    async def fetch_sales(
        date_from: Annotated[date, "조회 시작일"],
        date_to: Annotated[date, "조회 종료일"],
    ) -> ToolResult:
        rows = await db.fetch_sales(date_from, date_to)
        return ToolResult(content=f"{len(rows)} rows", data={"rows": rows})
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from pydantic import BaseModel, Field, TypeAdapter, create_model

from agent.config import TOOL_DEFAULT_TIMEOUT
from agent.models import ToolResult, ToolSpec

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 상수 — sentinel 도구 이름. harness 가 분기 키로 사용한다.
# 단일 진실 공급원: 데코레이터 호출 시 이 상수와 정확히 일치해야 한다.
# ---------------------------------------------------------------------------

PLANNER_ADD_TODO = "add_todo"
PLANNER_COMPLETE_TODO = "complete_todo"
SUB_AGENT_DISPATCH = "call_sub_agent"
COMPLETE_SUB_AGENT = "complete_subagent"
ASK_USER = "ask_user"
ACTIVATE_SKILL = "activate_skill"


# ---------------------------------------------------------------------------
# 핵심 타입
# ---------------------------------------------------------------------------

ToolFn = Callable[..., Awaitable["ToolResult | str"]]


@dataclass
class RegisteredTool:
    """런타임 도구 메타 + 실행 함수.

    `input_model` / `input_adapter` 는 데코레이터 호출 시 1회 생성되어 매 turn
    재사용된다. `sentinel=True` 인 경우 `fn` 은 placeholder 이며 harness 가
    tool_call 분기에서 가로채므로 `_execute_tool` 까지 도달하지 않아야 한다.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    slot_prompts: dict[str, str]
    timeout_seconds: float
    input_model: type[BaseModel]
    input_adapter: TypeAdapter
    fn: ToolFn
    sentinel: bool = False
    properties: dict[str, dict[str, Any]] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)


# 모듈 전역 — 데코레이터가 자기등록하는 단일 저장소.
_REGISTRY: dict[str, RegisteredTool] = {}


# ---------------------------------------------------------------------------
# 데코레이터
# ---------------------------------------------------------------------------


def register_tool(
    *,
    name: str | None = None,
    description: str | None = None,
    slot_prompts: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
    sentinel: bool = False,
) -> Callable[[ToolFn], ToolFn]:
    """async 함수를 Tool 로 등록하는 데코레이터.

    Args:
        name: 도구 이름. 미지정 시 함수 이름 사용.
        description: LLM 에 노출할 설명. 미지정 시 docstring 첫 줄 사용.
        slot_prompts: 필수 인자 누락 시 사용자에게 보일 친근한 질문 문구.
        timeout_seconds: 실행 timeout. 미지정 시 TOOL_DEFAULT_TIMEOUT.
        sentinel: True 면 harness 가 tool_call 분기에서 가로채는 도구
            (PLANNER / SUB_AGENT). fn 본문은 호출되지 않아야 한다.

    Returns:
        원본 함수 그대로 (등록만 부수효과). 테스트에서 직접 호출 가능.
    """

    def decorator(fn: ToolFn) -> ToolFn:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"@register_tool: {fn.__name__} 은 async 함수여야 합니다")

        tool_name = name or fn.__name__
        tool_desc = description or _extract_first_docstring_line(fn)
        if not tool_desc:
            raise ValueError(
                f"@register_tool({tool_name}): description 또는 docstring 필요"
            )

        input_model = _build_input_model(tool_name, fn)
        schema = input_model.model_json_schema()
        # JSON Schema 의 $defs / additionalProperties 등은 OpenAI 가 무시하지만
        # parameters 본체는 그대로 통과시킨다.
        parameters = {
            "type": "object",
            "properties": schema.get("properties", {}),
            "required": schema.get("required", []),
        }

        rt = RegisteredTool(
            name=tool_name,
            description=tool_desc,
            parameters=parameters,
            slot_prompts=slot_prompts or {},
            timeout_seconds=(
                timeout_seconds if timeout_seconds is not None else TOOL_DEFAULT_TIMEOUT
            ),
            input_model=input_model,
            input_adapter=TypeAdapter(input_model),
            fn=fn,
            sentinel=sentinel,
            properties=parameters["properties"],
            required=parameters["required"],
        )

        if tool_name in _REGISTRY:
            logger.warning("tool '%s' 가 중복 등록됨 — 마지막 정의가 우선", tool_name)
        _REGISTRY[tool_name] = rt
        return fn

    return decorator


# ---------------------------------------------------------------------------
# 기존 인터페이스 호환 wrapper — harness.py 는 변경 없이 동작
# ---------------------------------------------------------------------------


class ToolRegistry:
    """모듈 전역 `_REGISTRY` 의 thin read 인터페이스.

    기존 코드(harness)가 `registry.get / names / specs` 를 호출하던 형태를
    그대로 유지하기 위함. 새 코드는 `get_registered_tool(name)` 함수를 직접
    써도 무방하다.
    """

    def get(self, name: str) -> RegisteredTool | None:
        return _REGISTRY.get(name)

    def names(self) -> set[str]:
        return set(_REGISTRY.keys())

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(name=t.name, description=t.description, parameters=t.parameters)
            for t in _REGISTRY.values()
        ]


registry = ToolRegistry()


def get_registered_tool(name: str) -> RegisteredTool | None:
    """모듈 전역 레지스트리에서 도구 조회 — 테스트/디버그 용."""
    return _REGISTRY.get(name)


def all_registered_tools() -> list[RegisteredTool]:
    """등록된 모든 도구 — 테스트/디버그 용."""
    return list(_REGISTRY.values())


def _reset_registry_for_tests() -> None:
    """테스트에서 모듈 전역 상태를 초기화하기 위한 헬퍼.

    프로덕션 코드는 호출하지 않는다.
    """
    _REGISTRY.clear()


# ---------------------------------------------------------------------------
# 내부 헬퍼 — Pydantic 동적 모델 생성
# ---------------------------------------------------------------------------


def _build_input_model(tool_name: str, fn: ToolFn) -> type[BaseModel]:
    """함수 시그니처에서 입력 검증용 Pydantic 모델을 1회 생성한다.

    `Annotated[T, "설명"]` 의 두 번째 인자(첫 str)는 Field.description 으로
    승격해 JSON Schema 의 properties.<key>.description 에 들어간다 — LLM 이
    각 슬롯의 의미를 이해하는 핵심 단서.
    """
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn, include_extras=True)
    except (NameError, TypeError) as exc:
        raise TypeError(
            f"@register_tool({tool_name}): 타입 힌트 해석 실패 — {exc}"
        ) from exc

    field_defs: dict[str, tuple[Any, Any]] = {}
    for param_name, param in sig.parameters.items():
        if param_name == "self":
            continue
        annot = hints.get(param_name, str)
        actual_type, description = _split_annotated(annot)
        default = param.default

        if default is inspect.Parameter.empty:
            field_defs[param_name] = (
                actual_type,
                Field(..., description=description) if description else Field(...),
            )
        else:
            field_defs[param_name] = (
                actual_type,
                Field(default, description=description)
                if description
                else Field(default),
            )

    return create_model(f"{tool_name.title().replace('_', '')}Input", **field_defs)


def _split_annotated(annot: Any) -> tuple[Any, str | None]:
    """`Annotated[T, "설명", ...]` 에서 (T, 설명문자열|None) 추출."""
    if get_origin(annot) is Annotated:
        args = get_args(annot)
        actual_type = args[0]
        description = next((a for a in args[1:] if isinstance(a, str)), None)
        return actual_type, description
    return annot, None


def _extract_first_docstring_line(fn: ToolFn) -> str:
    """함수 docstring 의 첫 비어있지 않은 줄을 반환 (description fallback)."""
    doc = inspect.getdoc(fn) or ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""
