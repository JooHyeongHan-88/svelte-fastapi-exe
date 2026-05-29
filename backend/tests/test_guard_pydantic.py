"""Pydantic 기반 슬롯 가드 — 오류 책임자별 분기 검증.

핵심 계약: type=="missing"(값 부재)는 MissingSlot→AskUser, 그 외 형식/타입/enum
위반(값은 줬으나 모양이 틀림)은 invalid_message→LLM self-correct 로 분리된다.
"""

import sys
from pathlib import Path
from typing import Annotated, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import date  # noqa: E402

from agent.guard import validate_tool_args  # noqa: E402
from agent.models import ToolResult  # noqa: E402
from agent.registries.tools import (  # noqa: E402
    _reset_registry_for_tests,
    get_registered_tool,
    register_tool,
)
from tests._runner import run_tests  # noqa: E402


def _setup_demo() -> None:
    _reset_registry_for_tests()

    @register_tool(
        description="검색",
        slot_prompts={"date_from": "시작일을 YYYY-MM-DD 로 알려주세요"},
    )
    async def demo(
        date_from: Annotated[date, "시작일"],
        date_to: Annotated[date, "종료일"],
        format: Annotated[Literal["표", "차트", "요약"], "형식"],
    ) -> ToolResult:
        return ToolResult(content="ok")


def test_none_tool_passes() -> None:
    _setup_demo()
    result = validate_tool_args({}, None)
    assert result.ok is True
    assert result.missing == []


def test_all_required_missing() -> None:
    _setup_demo()
    tool = get_registered_tool("demo")
    result = validate_tool_args({}, tool)
    assert result.ok is False
    keys = {m.key for m in result.missing}
    assert keys == {"date_from", "date_to", "format"}


def test_slot_prompt_override_used() -> None:
    _setup_demo()
    tool = get_registered_tool("demo")
    result = validate_tool_args({}, tool)
    by_key = {m.key: m for m in result.missing}
    # date_from 은 override 있어야 함
    assert by_key["date_from"].question == "시작일을 YYYY-MM-DD 로 알려주세요"
    # date_to 는 override 없으면 description 기반 자동 메시지
    assert "종료일" in by_key["date_to"].question


def test_literal_enum_options_returned() -> None:
    _setup_demo()
    tool = get_registered_tool("demo")
    result = validate_tool_args(
        {"date_from": "2025-01-01", "date_to": "2025-01-02"}, tool
    )
    assert result.ok is False
    by_key = {m.key: m for m in result.missing}
    assert "format" in by_key
    assert by_key["format"].options is not None
    assert set(by_key["format"].options) == {"표", "차트", "요약"}


def test_invalid_date_format_goes_to_llm_not_user() -> None:
    # date_from="오늘" 은 값은 줬으나 형식이 틀림 → 사용자 질문이 아니라 LLM self-correct.
    _setup_demo()
    tool = get_registered_tool("demo")
    result = validate_tool_args(
        {"date_from": "오늘", "date_to": "2025-01-02", "format": "표"}, tool
    )
    assert result.ok is False
    assert result.invalid_message is not None
    assert "date_from" in result.invalid_message
    # 형식 오류는 missing(사용자 질문) 으로 분류되지 않는다.
    assert all(m.key != "date_from" for m in result.missing)


def test_invalid_literal_goes_to_llm_not_user() -> None:
    # 잘못된 enum 값(csv)을 LLM 이 골랐음 → 사용자에게 묻지 말고 LLM 이 고치게 한다.
    _setup_demo()
    tool = get_registered_tool("demo")
    result = validate_tool_args(
        {"date_from": "2025-01-01", "date_to": "2025-01-02", "format": "csv"}, tool
    )
    assert result.ok is False
    assert result.invalid_message is not None
    assert "format" in result.invalid_message
    assert all(m.key != "format" for m in result.missing)


def test_pure_missing_has_no_invalid_message() -> None:
    # 값 자체가 부재한 경우만 사용자 질문 — invalid_message 는 비어야 한다.
    _setup_demo()
    tool = get_registered_tool("demo")
    result = validate_tool_args({}, tool)
    assert result.ok is False
    assert result.invalid_message is None
    assert {m.key for m in result.missing} == {"date_from", "date_to", "format"}


def test_mixed_missing_and_invalid_uses_llm_path() -> None:
    # format 누락(missing) + date_from 형식오류(invalid) 동시 → invalid_message 경로,
    # 누락 항목까지 한 번에 안내해 LLM 이 완전한 호출로 교정하게 한다.
    _setup_demo()
    tool = get_registered_tool("demo")
    result = validate_tool_args({"date_from": "오늘", "date_to": "2025-01-02"}, tool)
    assert result.ok is False
    assert result.invalid_message is not None
    assert "date_from" in result.invalid_message
    assert "format" in result.invalid_message


def test_all_valid_passes() -> None:
    _setup_demo()
    tool = get_registered_tool("demo")
    result = validate_tool_args(
        {"date_from": "2025-01-01", "date_to": "2025-01-02", "format": "표"}, tool
    )
    assert result.ok is True
    assert result.missing == []


def test_one_error_per_key_only() -> None:
    """같은 키에 여러 에러가 나도 MissingSlot 은 1회만 생성."""
    _setup_demo()
    tool = get_registered_tool("demo")
    # 빈 값 → missing 만 1건 — 중복 발생할 수 있는 케이스 확인
    result = validate_tool_args({"date_from": "", "date_to": "2025-01-02"}, tool)
    by_key = {m.key: m for m in result.missing}
    # 키별 1건만
    assert len(result.missing) == len(by_key)


if __name__ == "__main__":
    run_tests(globals())
