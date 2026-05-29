"""슬롯 필링 가드 — Pydantic 시그니처 기반 도구 인자 검증.

LLM 이 환각/오해로 만들어낸 호출이 도구 함수에 닿기 전에 가로챈다. 핵심은
**오류의 책임자를 구분**해 처리 경로를 나누는 것이다:

    1. `missing` (값 자체가 제공되지 않음) → **사용자** 가 채워야 할 슬롯.
       AskUserEvent 로 사용자에게 되묻는다.
    2. 그 외 형식/타입/enum 위반 (값은 줬는데 모양이 틀림) → **LLM** 의 실수.
       사용자에게 묻지 않고 도구 에러(invalid_message)로 LLM 에 회신해
       같은 루프 안에서 self-correct 하도록 유도한다.

과거에는 둘을 모두 AskUserEvent 로 보내, LLM 이 dict 를 문자열 자리에 넣는 등
형식만 틀린 경우에도 "저장할 본문 텍스트를 주세요" 같은 질문이 사용자에게
노출돼 혼란을 줬다. 형식 오류는 사용자가 답할 수 있는 종류가 아니므로 LLM 에게
돌려보내는 것이 옳다.

Pydantic ValidationError 변환 규칙:
    - type=="missing"          → MissingSlot (slot_prompts override 우선)
    - 그 외 (literal/타입/날짜) → invalid_message 한 줄 (스키마 기대값 포함)

missing 과 형식오류가 **동시에** 있으면, LLM 이 호출 전체를 잘못 구성한 것으로
보고 invalid_message 경로(누락 항목까지 한 번에 안내)로 보낸다.
"""

from typing import Annotated, Any

from pydantic import BaseModel, Field, ValidationError

from agent.registries.tools import RegisteredTool


class MissingSlot(BaseModel):
    key: Annotated[str, "도구 파라미터 키"]
    question: Annotated[str, "사용자에게 보일 자연어 질문"]
    options: Annotated[list[str] | None, "JSON Schema enum 이 있을 때 UI 보기"] = None


class SlotCheckResult(BaseModel):
    ok: bool
    # type=="missing" 슬롯 — 사용자에게 AskUser 로 되물을 대상.
    missing: list[MissingSlot] = Field(default_factory=list)
    # 형식/타입 오류 — LLM 에 도구 에러로 회신해 self-correct 유도. 있으면 우선한다.
    invalid_message: str | None = None


def validate_tool_args(
    call_arguments: dict[str, Any], tool: RegisteredTool | None
) -> SlotCheckResult:
    """도구의 Pydantic 입력 모델로 인자를 검증한다.

    Args:
        call_arguments: LLM 이 보낸 raw arguments dict.
        tool: ToolRegistry 에서 조회한 RegisteredTool. None 이면 가드 통과
            (실행 단계에서 "unknown tool" 응답으로 흐름).

    Returns:
        SlotCheckResult —
            - ok=True: 그대로 실행.
            - invalid_message 존재: LLM 형식 오류 → 도구 에러로 회신(사용자 미개입).
            - missing 존재(invalid_message 없음): 사용자에게 AskUser.
    """
    if tool is None:
        return SlotCheckResult(ok=True)

    try:
        tool.input_adapter.validate_python(call_arguments or {})
    except ValidationError as exc:
        missing, invalid_message = _split_errors(exc, tool)
        if invalid_message:
            # 형식 오류가 하나라도 있으면 LLM self-correct 경로 (누락도 함께 안내).
            return SlotCheckResult(
                ok=False, missing=missing, invalid_message=invalid_message
            )
        if missing:
            return SlotCheckResult(ok=False, missing=missing)
        # 알 수 없는 에러여도 통과시키면 fn 에서 다시 터질 것 — 안전을 위해 통과 시킴.
        return SlotCheckResult(ok=True)

    return SlotCheckResult(ok=True)


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _split_errors(
    exc: ValidationError, tool: RegisteredTool
) -> tuple[list[MissingSlot], str | None]:
    """ValidationError 를 (missing 슬롯, invalid_message) 두 갈래로 분리한다.

    - type=="missing" → MissingSlot (사용자에게 물을 대상).
    - 그 외           → invalid_message 한 줄 (LLM 이 고칠 형식 오류).

    형식 오류가 하나라도 있으면 invalid_message 에 누락 항목까지 함께 적어,
    LLM 이 호출 전체를 한 번에 교정하도록 한다.

    동일 키에 여러 에러가 있으면 첫 번째만 채택한다.
    """
    seen: set[str] = set()
    missing: list[MissingSlot] = []
    lines: list[str] = []
    has_invalid = False

    for err in exc.errors():
        loc = err.get("loc") or ()
        if not loc:
            continue
        key = str(loc[0])
        if key in seen:
            continue
        seen.add(key)

        if err.get("type", "") == "missing":
            missing.append(
                MissingSlot(
                    key=key,
                    question=_question_for(key, err, tool),
                    options=_enum_options(key, tool),
                )
            )
            label = tool.properties.get(key, {}).get("description") or key
            lines.append(f"- {key}: 필수 값이 누락되었습니다 (기대: {label}).")
        else:
            has_invalid = True
            lines.append(_invalid_hint(key, err, tool))

    invalid_message: str | None = None
    if has_invalid:
        invalid_message = (
            "도구 인자가 스키마와 맞지 않습니다. 아래를 고쳐 같은 도구를 다시 "
            "호출하세요 (사용자에게 다시 묻지 말 것):\n" + "\n".join(lines)
        )

    return missing, invalid_message


def _invalid_hint(key: str, err: dict[str, Any], tool: RegisteredTool) -> str:
    """형식/타입 오류 한 건을 LLM 이 읽을 교정 힌트 한 줄로 변환한다."""
    prop = tool.properties.get(key, {})
    label = prop.get("description") or key
    msg = err.get("msg") or "형식이 올바르지 않습니다"
    return f"- {key}: {msg} (기대: {label})"


def _question_for(key: str, err: dict[str, Any], tool: RegisteredTool) -> str:
    """slot_prompts override 우선, 없으면 에러 type 별 친근한 한국어 메시지 생성."""
    override = tool.slot_prompts.get(key)
    if override:
        return override

    err_type = err.get("type", "")
    prop = tool.properties.get(key, {})
    label = prop.get("description") or key

    if err_type == "missing":
        return f"'{label}' 값을 알려 주세요."
    if err_type == "literal_error":
        ctx = err.get("ctx") or {}
        expected = ctx.get("expected")
        if expected:
            return f"'{label}' 은 다음 중 하나여야 합니다: {expected}"
        return f"'{label}' 값이 허용 범위를 벗어났습니다. 다시 알려 주세요."
    if err_type.startswith("date") or err_type.startswith("datetime"):
        return f"'{label}' 을 YYYY-MM-DD 형식으로 알려 주세요."
    if err_type.startswith("int") or err_type.startswith("float"):
        return f"'{label}' 을 숫자로 알려 주세요."
    if err_type.startswith("bool"):
        return f"'{label}' 을 예/아니오로 알려 주세요."

    return f"'{label}' 값이 올바르지 않습니다. 다시 알려 주세요."


def _enum_options(key: str, tool: RegisteredTool) -> list[str] | None:
    """JSON Schema 의 enum 정의에서 UI 버튼 후보를 추출 (Literal 타입 등).

    Pydantic 이 Literal 을 enum 으로 변환하는 경로와, 직접 enum 을 둔 경로 둘 다 커버.
    """
    prop = tool.properties.get(key, {})
    enum = prop.get("enum")
    if isinstance(enum, list) and enum:
        return [str(v) for v in enum]
    return None
