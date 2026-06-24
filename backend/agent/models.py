"""대화 및 스트리밍 이벤트 데이터 계층.

provider/harness/route 사이를 흐르는 모든 메시지·이벤트는 이 모듈의 Pydantic 모델로 표현된다.
프론트엔드와의 SSE 직렬화 또한 StreamEvent.model_dump_json() 한 줄로 끝난다.
"""

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]

# provider 가 tool_call 인자 JSON 파싱에 실패했을 때(스트리밍 잘림·이스케이프 깨짐 등)
# 빈 dict 대신 원본 문자열을 이 키에 담아 ToolCall.arguments 로 전달한다. harness 가
# 이를 감지해 "missing 슬롯" 으로 오인하지 않고 LLM 에 재전송을 요구한다 (사용자 미개입).
MALFORMED_TOOL_ARGS_KEY = "__malformed_arguments__"


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


class ToolResult(BaseModel):
    """Tool 실행 결과 구조화 응답.

    LLM 에는 `content` 만 tool message 로 전달하고, 프론트엔드에는 `data` 까지
    노출해 expandable JSON inspector 같은 UX 가 가능하다. tool 함수는 편의를 위해
    `str` 만 반환해도 되며 harness 가 자동으로 `ToolResult(content=...)` 로 감싼다.
    """

    content: Annotated[str, "LLM tool message 본문 — 자연어 한 줄 요약 권장"]
    data: Annotated[dict[str, Any] | None, "프론트 노출용 구조화 데이터"] = None
    is_error: Annotated[
        bool, "guard / timeout / 도구 내부 실패 여부 — 프론트가 빨간색 표시 등에 사용"
    ] = False


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
    result: Annotated[str, "LLM 컨텍스트와 동일한 텍스트 (ToolResult.content)"]
    data: Annotated[dict[str, Any] | None, "구조화 데이터 — inspector UI 용"] = None
    is_error: Annotated[bool, "실행 실패/timeout/guard 차단 여부"] = False


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    # provider 가 스트림을 끝낸 사유(stop/length/tool_calls 등). 디버그 트레이스가
    # "왜 멈췄나"(예: length 잘림)를 보기 위한 선택 필드 — 기존 소비자는 무시한다.
    finish_reason: Annotated[str | None, "스트림 종료 사유 (디버그용)"] = None


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
    is_fallback: bool = False
    # fallback 이면서 모든 todo 가 terminal 상태(completed/failed/skipped)인 경우.
    # 반복 예산이 소진됐지만 작업 자체는 완료됐음을 뜻하며, UI 가 빨강 대신
    # 중립(완료) 스타일로 표시할 수 있도록 신호를 전달한다.
    is_recovered: bool = False


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
    # 서브 에이전트가 슬롯 부족으로 중단됐을 때 — 다음 턴에 재위임 유도.
    pending_sub_agent: str | None = None
    pending_sub_task: str | None = None
    # ask_user sentinel 이 능동적으로 던진 질문 — 다음 턴 system prompt 에 재주입해
    # LLM 이 사용자 답변을 활용하도록 유도. 다음 턴 진입 시 즉시 클리어된다.
    pending_question: str | None = None


class AskUserEvent(BaseModel):
    """사용자에게 보완 질문을 던지는 구조화 이벤트.

    두 가지 경로로 발생:
        1) 슬롯 가드: 도구 인자 검증 실패 시 자동.
        2) ask_user sentinel: LLM 이 능동적으로 호출해 모호한 입력 보완.
    """

    type: Literal["ask_user"] = "ask_user"
    question: Annotated[str, "사용자에게 보일 자연어 질문"]
    slot_key: Annotated[str, "응답을 매핑할 슬롯 키"]
    options: Annotated[list[str] | None, "선택지 버튼 후보 (enum 또는 LLM 제시)"] = None
    tool_name: Annotated[str | None, "어떤 도구 호출을 위한 질문인지"] = None
    input_type: Annotated[
        Literal["choice", "text", "both"],
        "UI 모드 — choice: 옵션만, text: 자유입력만, both: 옵션+자유입력 (기본)",
    ] = "both"
    multi_select: Annotated[
        bool, "options 다중 선택 허용 — True 면 여러 개 고른 뒤 한 번에 제출"
    ] = False


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
    # 디스패치별 고유 상관키 — 병렬 실행 시 같은 이름 에이전트가 둘 이상 동시에 떠도
    # 프론트가 이벤트를 정확한 트레일로 라우팅하게 한다. 순차 위임은 call.id 를 그대로 채운다.
    dispatch_id: Annotated[str | None, "디스패치 상관키 (병렬 라우팅용)"] = None


class AgentReturnEvent(BaseModel):
    """서브 에이전트가 작업을 마치고 요약본을 지닌 채 복귀할 때 발송.

    부모 _run_agent_turn 은 이 이벤트의 summary 와 todo_log 를 합쳐
    구조화된 tool_result 텍스트로 변환해 오케스트레이터 LLM 컨텍스트에 주입한다.
    """

    type: Literal["agent:return"] = "agent:return"
    from_agent: Annotated[str, "복귀하는 에이전트 이름"]
    summary: Annotated[str, "complete_subagent 가 제출한 원본 1~3문장 요약"]
    todo_log: Annotated[
        list["TodoItem"], "서브 에이전트 실행 중 생성·갱신된 todo 스냅샷"
    ] = Field(default_factory=list)
    tool_calls_count: Annotated[int, "서브 에이전트가 실행한 도구 호출 총 수"] = 0
    error_count: Annotated[int, "is_error=True 였던 도구 호출 수"] = 0
    # AgentSwitchEvent 와 짝을 이루는 디스패치 상관키 — 병렬 라우팅용.
    dispatch_id: Annotated[str | None, "디스패치 상관키 (병렬 라우팅용)"] = None


class SkillCompleteEvent(BaseModel):
    """todo_list 전체가 terminal 상태(completed/failed/skipped)에 도달했을 때 발송.

    오케스트레이터와 서브 에이전트 양쪽에서 모두 발생할 수 있다.
    프론트는 이 이벤트를 받으면 SKILL 진행 표시기를 '완료'로 전환한다.
    """

    type: Literal["skill_complete"] = "skill_complete"
    completed: Annotated[int, "COMPLETED 상태로 끝난 단계 수"]
    failed: Annotated[int, "FAILED 상태로 끝난 단계 수"]
    skipped: Annotated[int, "SKIPPED 상태로 끝난 단계 수"]


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
    # AgentSwitchEvent 와 짝을 이루는 디스패치 상관키 — 병렬 라우팅용.
    dispatch_id: Annotated[str | None, "디스패치 상관키 (병렬 라우팅용)"] = None


StreamEvent = Annotated[
    DeltaEvent
    | ToolCallEvent
    | ToolResultEvent
    | DoneEvent
    | ErrorEvent
    | AskUserEvent
    | TodoUpdateEvent
    | SkillActiveEvent
    | SkillCompleteEvent
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
