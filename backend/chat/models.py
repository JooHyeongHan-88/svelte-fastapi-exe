"""대화 및 스트리밍 이벤트 데이터 계층.

provider/harness/route 사이를 흐르는 모든 메시지·이벤트는 이 모듈의 Pydantic 모델로 표현된다.
프론트엔드와의 SSE 직렬화 또한 StreamEvent.model_dump_json() 한 줄로 끝난다.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]


class ToolCall(BaseModel):
    """LLM 이 요청한 도구 호출 한 건."""

    id: Annotated[str, "tool_call 식별자 — tool 응답을 매칭할 때 사용"]
    name: Annotated[str, "ToolRegistry 에 등록된 도구 이름"]
    arguments: Annotated[dict[str, Any], "도구에 전달할 인자 (JSON 객체)"] = Field(
        default_factory=dict
    )


class Message(BaseModel):
    """대화 히스토리의 단일 항목.

    role 에 따라 의미가 달라진다:
        - system/user/assistant: content 에 본문
        - assistant: tool_calls 가 있을 수 있음 (도구 호출 턴)
        - tool: tool_call_id 로 매칭되는 도구 실행 결과
    """

    role: Annotated[Role, "메시지 발신자 역할"]
    content: Annotated[str, "본문. tool_call 만 있는 턴이면 빈 문자열일 수 있음"] = ""
    tool_calls: Annotated[list[ToolCall] | None, "assistant 가 호출한 도구 목록"] = None
    tool_call_id: Annotated[str | None, "role=tool 일 때 어떤 호출에 대한 응답인지"] = (
        None
    )


class ToolSpec(BaseModel):
    """provider 에게 노출하는 도구 스펙 (OpenAI function-calling 호환 형태)."""

    name: Annotated[str, "도구 이름"]
    description: Annotated[str, "LLM 이 언제 사용할지 결정할 때 읽는 설명"]
    parameters: Annotated[dict[str, Any], "JSON Schema (object)"] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )


# ---------------------------------------------------------------------------
# Stream Events — provider → harness → route → frontend 흐름의 단위
# ---------------------------------------------------------------------------


class DeltaEvent(BaseModel):
    type: Literal["delta"] = "delta"
    content: Annotated[str, "이번 chunk 에 추가된 텍스트 조각"]


class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    call: ToolCall


class ToolResultEvent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    name: str
    result: Annotated[str, "도구 실행 결과 (직렬화된 문자열)"]


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


StreamEvent = Annotated[
    DeltaEvent | ToolCallEvent | ToolResultEvent | DoneEvent | ErrorEvent,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# API request/response 모델
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: Annotated[str, "사용자가 입력한 자연어 메시지"]


class ConversationResponse(BaseModel):
    messages: list[Message]


class RestoreRequest(BaseModel):
    """프론트 localStorage 의 히스토리를 백엔드에 재주입할 때의 페이로드."""

    messages: Annotated[list[Message], "client 가 보존하던 전체 대화 히스토리"]
