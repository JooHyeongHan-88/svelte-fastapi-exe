"""슬롯 필링 가드 — 도구 호출 직전 필수 인자 누락 검증.

LLM 이 환각으로 만들어낸 호출이 실제 도구 실행 함수에 닿기 전에 가로채고,
사용자에게 되묻기 위한 missing 목록을 돌려준다. JSON Schema `required`
를 기준으로 하며, 각 슬롯의 질문 문구는 도구의 `slot_prompts` 매핑에서 끌어 온다.
"""

from typing import Annotated, Any

from pydantic import BaseModel, Field


class MissingSlot(BaseModel):
    key: Annotated[str, "tool.parameters.properties 의 키"]
    question: Annotated[str, "사용자에게 보일 자연어 질문"]
    options: Annotated[list[str] | None, "JSON Schema enum 이 있을 때 UI 보기"] = None


class SlotCheckResult(BaseModel):
    ok: bool
    missing: list[MissingSlot] = Field(default_factory=list)


def check_required_slots(
    call_arguments: dict[str, Any], tool: Any | None
) -> SlotCheckResult:
    """tool 의 JSON Schema `required` + slot_prompts 를 결합해 누락 키를 찾는다.

    tool 이 None (등록되지 않은 도구) 이면 가드는 통과시키고 실행 단계에서
    표준 "[error] unknown tool" 응답으로 흘려 보낸다 — 가드의 책임이 아님.
    """
    if tool is None:
        return SlotCheckResult(ok=True)

    schema: dict = getattr(tool, "parameters", {}) or {}
    required: list[str] = schema.get("required", []) or []
    properties: dict = schema.get("properties", {}) or {}
    slot_prompts: dict[str, str] = getattr(tool, "slot_prompts", {}) or {}

    missing: list[MissingSlot] = []
    for key in required:
        value = call_arguments.get(key)
        if _is_empty(value):
            prop = properties.get(key, {})
            default_q = prop.get("description") or key
            missing.append(
                MissingSlot(
                    key=key,
                    question=slot_prompts.get(key, f"'{default_q}' 값을 알려 주세요."),
                    options=prop.get("enum"),
                )
            )

    return SlotCheckResult(ok=not missing, missing=missing)


def _is_empty(value: Any) -> bool:
    """슬롯 값이 "비어 있다" 의 정의 — None/공백 문자열/빈 컬렉션을 누락으로 본다."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, list | dict) and not value:
        return True
    return False
