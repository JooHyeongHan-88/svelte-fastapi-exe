"""대화 및 스트리밍 이벤트 데이터 계층.

provider/harness/route 사이를 흐르는 모든 메시지·이벤트는 이 모듈의 Pydantic 모델로 표현된다.
프론트엔드와의 SSE 직렬화 또한 StreamEvent.model_dump_json() 한 줄로 끝난다.
"""

from enum import Enum
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


# ---------------------------------------------------------------------------
# Agent planner / slot-filling state
# ---------------------------------------------------------------------------


class TodoStatus(str, Enum):
    """플래너 sub-task 의 단계. UI 진행 표시에도 그대로 사용한다."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TodoItem(BaseModel):
    """add_todo / complete_todo 로 LLM 이 직접 관리하는 단위."""

    task_id: Annotated[str, "단축 hex 또는 UUID — complete_todo 가 매칭에 사용"]
    description: Annotated[str, "사용자에게 보일 한국어 설명"]
    tool_name: Annotated[str | None, "이 step 에서 호출할 도구 이름 힌트"] = None
    status: TodoStatus = TodoStatus.PENDING
    result_summary: Annotated[str | None, "완료/실패 후 짧은 요약"] = None


class AgentState(BaseModel):
    """client_id 한 명당 영속되는 에이전트 진행 상태.

    AgentStateStore 가 디스크에 그대로 직렬화하므로, 새 필드를 추가할 때는
    이전 버전 JSON 도 model_validate 로 무사 통과되도록 default 를 둬야 한다.
    """

    todo_list: list[TodoItem] = Field(default_factory=list)
    # 슬롯 필링 대기 — 사용자가 답해야 하는 키 → 질문 문구.
    missing_slots: dict[str, str] = Field(default_factory=dict)
    # 슬롯이 채워지면 재호출할 보류 중 도구 호출.
    pending_tool: str | None = None
    pending_args: dict[str, Any] = Field(default_factory=dict)
    # 스킬 간 공유되는 임시 컨텍스트 (예: 직전 검색 결과 id).
    context_data: dict[str, Any] = Field(default_factory=dict)
    active_skills: list[str] = Field(default_factory=list)


class AskUserEvent(BaseModel):
    """슬롯 필링 가드가 도구 실행을 막고 사용자에게 되묻는 구조화 이벤트."""

    type: Literal["ask_user"] = "ask_user"
    question: Annotated[str, "사용자에게 보일 자연어 질문"]
    slot_key: Annotated[str, "응답을 매핑할 슬롯 키"]
    options: Annotated[list[str] | None, "JSON Schema enum 이 있을 때 UI 버튼 후보"] = (
        None
    )
    tool_name: Annotated[str | None, "어떤 도구 호출을 위한 질문인지"] = None


class TodoUpdateEvent(BaseModel):
    """플래너 상태 변화 알림 — 프론트가 진행 표시기를 업데이트."""

    type: Literal["todo_update"] = "todo_update"
    todos: list[TodoItem]


class SkillActiveEvent(BaseModel):
    """이번 턴에 매칭된 SKILL 목록 알림 — 프론트가 스킬 뱃지를 표시한다.

    하니스가 skill_registry.select() 직후, provider.astream 시작 전에 yield 한다.
    skills 가 비어 있으면 이 이벤트를 yield 하지 않으므로 프론트는 빈 목록을 처리할 필요 없다.
    """

    type: Literal["skill_active"] = "skill_active"
    skills: list[str]


class ReasoningEvent(BaseModel):
    """LLM 내부 추론 과정 텍스트 청크 — DeltaEvent 와 분리해 전달한다.

    OpenAI o-series 모델이 streaming 중 delta.reasoning_content 를 내려줄 때 생성된다.
    프론트는 접을 수 있는 '생각 중...' 블록으로 표시한다.
    """

    type: Literal["reasoning"] = "reasoning"
    content: Annotated[str, "이번 chunk 에 추가된 추론 텍스트 조각"]


# ---------------------------------------------------------------------------
# 계층형 멀티 에이전트 이벤트 — 오케스트레이터 ↔ 서브 에이전트 제어권 전환 시각화
# ---------------------------------------------------------------------------


class AgentSwitchEvent(BaseModel):
    """오케스트레이터가 서브 에이전트에게 제어권을 넘기는 순간 발송.

    프론트는 메시지 카드 상단에 'orchestrator → coding_agent' 형태의 chip 으로 표시한다.
    """

    type: Literal["agent:switch"] = "agent:switch"
    from_agent: Annotated[
        str, "직전 활성 에이전트 — 'orchestrator' 또는 상위 에이전트 이름"
    ]
    to_agent: Annotated[str, "새로 활성화될 에이전트 이름"]
    reason: Annotated[str, "위임 사유 — task 의 첫 80자 발췌"]


class AgentReturnEvent(BaseModel):
    """서브 에이전트가 작업을 마치고 요약본을 지닌 채 복귀할 때 발송.

    부모 _run_agent_turn 은 이 이벤트의 summary 를 캡처해 tool_result 로 변환한다.
    """

    type: Literal["agent:return"] = "agent:return"
    from_agent: Annotated[str, "복귀하는 에이전트 이름"]
    summary: Annotated[str, "Task Summary — tool_result 와 동일한 텍스트"]


class AgentProgressEvent(BaseModel):
    """서브 에이전트의 raw 이벤트(delta / tool_call / tool_result / reasoning)를 래핑.

    오케스트레이터 vs 서브 에이전트 이벤트를 wire 상에서 명확히 구분하기 위해 한 단계 감싼다.
    inner_payload 는 원본 이벤트의 type 을 제외한 model_dump 결과.
    프론트는 ev.type === 'agent:progress' 한 곳에서 inner_type 으로 재분기한다.
    """

    type: Literal["agent:progress"] = "agent:progress"
    agent_id: Annotated[str, "현재 제어권을 가진 서브 에이전트 이름"]
    inner_type: Annotated[
        str, "원본 이벤트 type — delta/tool_call/tool_result/reasoning"
    ]
    inner_payload: Annotated[
        dict[str, Any], "원본 이벤트의 type 을 제외한 model_dump 결과"
    ]


StreamEvent = Annotated[
    DeltaEvent
    | ToolCallEvent
    | ToolResultEvent
    | DoneEvent
    | ErrorEvent
    | AskUserEvent
    | TodoUpdateEvent
    | SkillActiveEvent
    | ReasoningEvent
    | AgentSwitchEvent
    | AgentReturnEvent
    | AgentProgressEvent,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# API request/response 모델
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: Annotated[str, "사용자가 입력한 자연어 메시지"]
    force_skills: Annotated[
        list[str] | None,
        "슬래시 커맨드로 강제 활성화할 skill 이름 목록 — trigger 매칭 우회",
    ] = None


class ConversationResponse(BaseModel):
    messages: list[Message]


class RestoreRequest(BaseModel):
    """프론트 localStorage 의 히스토리를 백엔드에 재주입할 때의 페이로드."""

    messages: Annotated[list[Message], "client 가 보존하던 전체 대화 히스토리"]
