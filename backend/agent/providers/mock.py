"""Mock LLM provider for UI validation without real API calls.

지원하는 시나리오 (SKILLS / AGENTS 라우팅 검증용):
    1. now tool       — "지금 몇 시", "현재 시각" 등 → now 도구 호출 → 시각 응답
    2. add_todo       — "보고서", "리포트", "report" → add_todo 3-step 플래너
    3. search         — "검색", "데이터 조회" → demo_search (빈 인자) → AskUserEvent
    4. reasoning      — "생각해", "추론" → ReasoningEvent 청크 → DeltaEvent 응답
    5. full report    — "전체 보고서" → add_todo 3개 → complete_todo 순차 실행
    6. 명시 위임      — "코딩 에이전트", "리서치 에이전트" → call_sub_agent (Case 2)
    7. 체이닝         — "전체 분석" → coding_agent → research_agent 순차 위임
    8. 서브 에이전트  — system 메시지에 "당신은 '<name>' 서브 에이전트" 포함 시 분기
                        (오케스트레이터가 _dispatch_sub_agent 로 호출한 격리된 turn)
    9. 기본 echo      — 위 트리거가 없으면 메시지를 그대로 echo
"""

import asyncio
import uuid
from collections.abc import AsyncIterator

from agent.models import (
    DeltaEvent,
    DoneEvent,
    Message,
    ReasoningEvent,
    StreamEvent,
    ToolCall,
    ToolCallEvent,
    ToolSpec,
)

# 스트리밍 체감을 위한 토큰 간 지연 (초).
_MOCK_TOKEN_DELAY = 0.02

# skill_time 시나리오 트리거.
_NOW_TRIGGERS = (
    "몇 시",
    "지금 시간",
    "현재 시각",
    "what time",
    "current time",
    "now()",
)

# skill_report 시나리오 트리거 — add_todo 플래너 경로 실연.
_REPORT_TRIGGERS = ("보고서", "리포트", "report")

# AskUserEvent UI 검증용 — demo_search 슬롯 가드 발동.
_SEARCH_TRIGGERS = ("검색", "search", "데이터 조회")

# ReasoningEvent UI 검증용.
_REASONING_TRIGGERS = ("생각해", "생각 해", "think", "reason", "추론")

# full report 시나리오 — add_todo + complete_todo 순차 실행.
_FULL_REPORT_TRIGGERS = ("전체 보고서", "full report")

# Case 2: 명시 위임 — 사용자가 에이전트를 지명. 가장 먼저 검사돼야 한다.
_CODING_AGENT_TRIGGERS = ("코딩 에이전트", "coding_agent", "코드 리팩토링")
_RESEARCH_AGENT_TRIGGERS = ("리서치 에이전트", "research_agent", "조사 에이전트")

# Case 2 + 체이닝 — 한 번의 사용자 입력으로 두 에이전트 순차 위임.
_CHAIN_TRIGGERS = ("전체 분석", "full analysis")

# 서브 에이전트 분기 marker — _compose_sub_agent_system_prompt 가 항상 포함.
_SUB_AGENT_MARKER = "당신은 '"


class MockProvider:
    """LLM 없이 UI 검증을 위한 가짜 프로바이더.

    시나리오 1 (skill_time):
        트리거 키워드 포함 + 이번 턴에 now 아직 미호출 → ToolCallEvent(now) 발생.
        tool_result 가 담긴 다음 루프에서는 시각 텍스트를 delta 로 응답.

    시나리오 2 (skill_report):
        트리거 키워드 포함 + 이번 턴에 add_todo 아직 미호출 → ToolCallEvent(add_todo) 발생.
        harness 가 TodoUpdateEvent 를 yield 한 뒤 provider 를 재호출하면, 이 분기로
        들어와 계획이 완성됐다는 텍스트를 echo.

    시나리오 3 (skill_search — AskUserEvent 검증):
        "검색" 트리거 → demo_search 를 빈 인자로 호출 → guard 가 AskUserEvent 발동.
        사용자가 답변하면 다음 루프에서 tool_result 를 받아 결과 텍스트를 echo.

    시나리오 4 (reasoning — ReasoningEvent 검증):
        "생각해" 트리거 → ReasoningEvent 청크를 먼저 스트리밍 → DeltaEvent 로 응답.

    시나리오 5 (full_report — TodoProgress 완료 전환 검증):
        "전체 보고서" 트리거 → add_todo 3개 등록 → 재호출 시 complete_todo 순차 실행
        → 모두 완료 후 응답 텍스트. TodoProgress 의 PENDING→COMPLETED 전환을 확인한다.

    시나리오 6 (기본 echo):
        위 트리거 없음 → 사용자 메시지를 그대로 echo.
    """

    async def astream(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> AsyncIterator[StreamEvent]:
        """Stream mock response events."""
        last_user = _find_last_user(messages)

        # ── 서브 에이전트 분기 — system marker 로 결정론 판별 ──────────────────
        # _compose_sub_agent_system_prompt 가 항상 "당신은 '<name>' 서브 에이전트" 헤더를
        # 포함하므로 mock 도 같은 marker 로 컨텍스트를 식별한다.
        sub_name = _detect_sub_agent_name(messages)
        if sub_name is not None:
            async for event in _sub_agent_scenario(messages, sub_name):
                yield event
            return

        # ── 시나리오 7: 체이닝 — coding_agent → research_agent ─────────────────
        if last_user is not None and _matches(last_user.content, _CHAIN_TRIGGERS):
            async for event in _chain_scenario(messages, last_user):
                yield event
            return

        # ── 시나리오 6: Case 2 명시 위임 ───────────────────────────────────────
        already_dispatched = _has_recent_tool_result(messages, "mock-dispatch-")
        if last_user is not None and not already_dispatched:
            if _matches(last_user.content, _CODING_AGENT_TRIGGERS):
                yield ToolCallEvent(
                    call=ToolCall(
                        id=f"mock-dispatch-coding-{uuid.uuid4().hex[:8]}",
                        name="call_sub_agent",
                        arguments={
                            "agent_name": "coding_agent",
                            "task": last_user.content,
                        },
                    )
                )
                yield DoneEvent()
                return
            if _matches(last_user.content, _RESEARCH_AGENT_TRIGGERS):
                yield ToolCallEvent(
                    call=ToolCall(
                        id=f"mock-dispatch-research-{uuid.uuid4().hex[:8]}",
                        name="call_sub_agent",
                        arguments={
                            "agent_name": "research_agent",
                            "task": last_user.content,
                        },
                    )
                )
                yield DoneEvent()
                return

        # 위임 결과를 받은 다음 루프 — 자연어 최종 보고.
        if already_dispatched:
            async for event in _orchestrator_final_report(messages):
                yield event
            return

        # ── 시나리오 1: now tool ──────────────────────────────────────────────
        already_called_now = _has_recent_tool_result(messages, "mock-now-")
        if (
            last_user is not None
            and _matches(last_user.content, _NOW_TRIGGERS)
            and not already_called_now
        ):
            yield ToolCallEvent(
                call=ToolCall(
                    id=f"mock-now-{uuid.uuid4().hex[:8]}",
                    name="now",
                    arguments={},
                )
            )
            yield DoneEvent()
            return

        # ── 시나리오 5: full_report (add_todo + complete_todo 순차) ──────────
        # 시나리오 2 보다 먼저 검사 — "전체 보고서"는 더 구체적인 트리거.
        if last_user is not None and _matches(last_user.content, _FULL_REPORT_TRIGGERS):
            async for event in _full_report_scenario(messages):
                yield event
            return

        # ── 시나리오 2: add_todo (report 플래너) ─────────────────────────────
        already_planned = _has_recent_tool_result(messages, "mock-todo-")
        if (
            last_user is not None
            and _matches(last_user.content, _REPORT_TRIGGERS)
            and not already_planned
        ):
            yield ToolCallEvent(
                call=ToolCall(
                    id=f"mock-todo-{uuid.uuid4().hex[:8]}",
                    name="add_todo",
                    arguments={
                        "items": [
                            {
                                "description": "매출 데이터 조회",
                                "tool_name": "fetch_sales",
                            },
                            {
                                "description": "보고서 본문 생성",
                                "tool_name": "render_report",
                            },
                            {"description": "이메일 발송", "tool_name": "send_email"},
                        ]
                    },
                )
            )
            yield DoneEvent()
            return

        # ── 시나리오 3: demo_search → AskUserEvent ────────────────────────────
        already_searched = _has_recent_tool_result(messages, "mock-search-")
        if (
            last_user is not None
            and _matches(last_user.content, _SEARCH_TRIGGERS)
            and not already_searched
        ):
            # 인자를 비워서 호출 → harness guard 가 AskUserEvent 를 발동시킨다.
            yield ToolCallEvent(
                call=ToolCall(
                    id=f"mock-search-{uuid.uuid4().hex[:8]}",
                    name="demo_search",
                    arguments={},
                )
            )
            yield DoneEvent()
            return

        # ── 시나리오 4: reasoning ─────────────────────────────────────────────
        if last_user is not None and _matches(last_user.content, _REASONING_TRIGGERS):
            async for event in _reasoning_scenario(last_user.content):
                yield event
            return

        # ── 기본 echo ─────────────────────────────────────────────────────────
        reply = _compose_reply(last_user, messages)
        for ch in reply:
            await asyncio.sleep(_MOCK_TOKEN_DELAY)
            yield DeltaEvent(content=ch)

        yield DoneEvent()


def _full_report_scenario(
    messages: list[Message],
) -> AsyncIterator[StreamEvent]:
    """전체 보고서 시나리오 — add_todo 등록 후 complete_todo 순차 실행.

    harness 가 add_todo 를 처리하고 provider 를 재호출할 때마다
    등록된 task_id 를 완료 처리해 TodoProgress 의 전환을 시연한다.
    """
    # harness 가 add_todo tool_result 를 messages 에 추가한 뒤 재호출한다.
    # tool_result 중 mock-full- prefix 를 가진 것이 있으면 완료 단계.
    full_todo_results = [
        m
        for m in messages
        if m.role == "tool" and (m.tool_call_id or "").startswith("mock-full-todo-")
    ]

    if not full_todo_results:
        # 1단계: add_todo 등록
        async def _add() -> AsyncIterator[StreamEvent]:
            yield ToolCallEvent(
                call=ToolCall(
                    id=f"mock-full-todo-{uuid.uuid4().hex[:8]}",
                    name="add_todo",
                    arguments={
                        "items": [
                            {"description": "데이터 수집", "tool_name": "fetch_sales"},
                            {
                                "description": "분석 및 정리",
                                "tool_name": "render_report",
                            },
                            {"description": "최종 발송", "tool_name": "send_email"},
                        ]
                    },
                )
            )
            yield DoneEvent()

        return _add()

    # 2단계 이후: 이전 TodoUpdateEvent 에서 task_id 목록을 파악해 순차 complete.
    # harness 가 add_todo 를 처리할 때 state.todo_list 에 task_id 가 들어가며,
    # tool_result content 에 "[planner] added N todo(s): ['id1', 'id2', ...]" 형태로
    # task_id 목록이 포함된다 — 이를 파싱해 complete_todo 를 호출한다.
    import re as _re

    task_ids: list[str] = []
    for tr in full_todo_results:
        found = _re.findall(r"'([0-9a-f]{8})'", tr.content)
        task_ids.extend(found)

    # 이미 complete_todo 를 호출한 task_id 는 건너뛴다.
    completed_ids = {
        m.tool_call_id.replace("mock-full-complete-", "", 1)
        for m in messages
        if m.role == "tool" and (m.tool_call_id or "").startswith("mock-full-complete-")
    }
    pending_ids = [tid for tid in task_ids if tid not in completed_ids]

    async def _complete() -> AsyncIterator[StreamEvent]:
        if pending_ids:
            # 다음 미완료 task 하나를 완료 처리한다.
            tid = pending_ids[0]
            yield ToolCallEvent(
                call=ToolCall(
                    id=f"mock-full-complete-{tid}",
                    name="complete_todo",
                    arguments={"task_id": tid, "summary": "완료"},
                )
            )
            yield DoneEvent()
            return

        # 모든 task 완료 → 최종 응답 텍스트
        reply = (
            "전체 보고서 작업이 모두 완료되었습니다. 3단계가 정상적으로 처리됐습니다."
        )
        for ch in reply:
            await asyncio.sleep(_MOCK_TOKEN_DELAY)
            yield DeltaEvent(content=ch)
        yield DoneEvent()

    return _complete()


async def _reasoning_scenario(user_text: str) -> AsyncIterator[StreamEvent]:
    """ReasoningEvent 청크를 먼저 스트리밍한 뒤 DeltaEvent 로 응답한다."""
    reasoning = (
        f"사용자가 '{user_text}' 라고 입력했습니다. "
        "핵심 의도를 분석합니다... "
        "관련 컨텍스트를 검토합니다... "
        "최적의 답변 형식을 결정합니다..."
    )
    for i in range(0, len(reasoning), 5):
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield ReasoningEvent(content=reasoning[i : i + 5])

    reply = "깊이 생각해 보았습니다. 결론적으로 이 질문에 대한 답변을 드릴 수 있습니다."
    for ch in reply:
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield DeltaEvent(content=ch)

    yield DoneEvent()


def _detect_sub_agent_name(messages: list[Message]) -> str | None:
    """system 메시지에 "당신은 '<name>' 서브 에이전트" 헤더가 있으면 agent_name 추출.

    _compose_sub_agent_system_prompt 가 항상 이 헤더를 포함하도록 강제하므로
    오케스트레이터 컨텍스트와 서브 에이전트 컨텍스트를 결정론적으로 구분할 수 있다.
    """
    if not messages or messages[0].role != "system":
        return None
    system_text = messages[0].content
    marker_pos = system_text.find(_SUB_AGENT_MARKER)
    if marker_pos == -1:
        return None
    start = marker_pos + len(_SUB_AGENT_MARKER)
    end = system_text.find("'", start)
    if end == -1:
        return None
    return system_text[start:end]


async def _chain_scenario(
    messages: list[Message], last_user: Message
) -> AsyncIterator[StreamEvent]:
    """체이닝 시연 — coding_agent → research_agent → 통합 보고 (3단계)."""
    coding_done = _has_recent_tool_result(messages, "mock-dispatch-coding-")
    research_done = _has_recent_tool_result(messages, "mock-dispatch-research-")

    if not coding_done:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"mock-dispatch-coding-{uuid.uuid4().hex[:8]}",
                name="call_sub_agent",
                arguments={
                    "agent_name": "coding_agent",
                    "task": f"코드 측면 분석 ({last_user.content})",
                },
            )
        )
        yield DoneEvent()
        return

    if not research_done:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"mock-dispatch-research-{uuid.uuid4().hex[:8]}",
                name="call_sub_agent",
                arguments={
                    "agent_name": "research_agent",
                    "task": f"배경 정보 조사 ({last_user.content})",
                },
            )
        )
        yield DoneEvent()
        return

    # 통합 보고 단계.
    reply = (
        "두 서브 에이전트의 결과를 통합했습니다.\n\n"
        "- 코딩 에이전트: 코드 검토 및 리팩토링 후보 식별 완료\n"
        "- 리서치 에이전트: 배경 정보 수집 완료\n\n"
        "전체 분석이 마무리되었습니다."
    )
    for ch in reply:
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield DeltaEvent(content=ch)
    yield DoneEvent()


async def _sub_agent_scenario(
    messages: list[Message], agent_name: str
) -> AsyncIterator[StreamEvent]:
    """서브 에이전트 시뮬레이션 — now 도구 1회 호출 후 Task Summary 마무리."""
    already_called_now = _has_recent_tool_result(messages, "mock-sub-now-")
    if not already_called_now:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"mock-sub-now-{uuid.uuid4().hex[:8]}",
                name="now",
                arguments={},
            )
        )
        yield DoneEvent()
        return

    if agent_name == "coding_agent":
        reply = (
            "코드 부분 검토를 완료했습니다. 시각 도구로 작업 시점을 기록했고 "
            "안전한 리팩토링 후보 3곳, 네이밍 정리 2곳을 식별했습니다.\n\n"
            "Task Summary:\n"
            "- 코드 검토 완료 — 리팩토링 후보 3곳·네이밍 정리 2곳 식별\n"
            "- 다음 단계: 단위 테스트 추가 후 안전한 변경 진행 권장"
        )
    elif agent_name == "research_agent":
        reply = (
            "조사 작업을 마쳤습니다. 시각 도구로 현재 시점을 확인하고 관련 "
            "배경 정보를 정리했습니다.\n\n"
            "Task Summary:\n"
            "- 조사 주제 핵심 사실 수집 완료\n"
            "- 신뢰도: mock 환경 시뮬레이션 (실제 데이터 소스 미연결)"
        )
    else:
        reply = (
            f"{agent_name} 작업을 마쳤습니다.\n\n"
            "Task Summary:\n"
            f"- {agent_name} 위임 작업 완료"
        )

    for ch in reply:
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield DeltaEvent(content=ch)
    yield DoneEvent()


async def _orchestrator_final_report(
    messages: list[Message],
) -> AsyncIterator[StreamEvent]:
    """서브 에이전트 위임 결과를 받은 후 사용자에게 자연어로 최종 보고."""
    last_dispatch = None
    for m in reversed(messages):
        if m.role == "tool" and (m.tool_call_id or "").startswith("mock-dispatch-"):
            last_dispatch = m
            break

    summary_text = last_dispatch.content if last_dispatch else "(결과 없음)"
    reply = f"서브 에이전트의 작업이 완료되었습니다.\n\n요약:\n{summary_text}"
    for ch in reply:
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield DeltaEvent(content=ch)
    yield DoneEvent()


def _find_last_user(messages: list[Message]) -> Message | None:
    """대화 히스토리에서 가장 최근 user 메시지를 반환한다."""
    for m in reversed(messages):
        if m.role == "user":
            return m
    return None


def _matches(text: str, triggers: tuple[str, ...]) -> bool:
    """text 에 triggers 중 하나라도 포함되어 있으면 True."""
    lowered = text.lower()
    return any(t.lower() in lowered for t in triggers)


def _has_recent_tool_result(messages: list[Message], prefix: str) -> bool:
    """현재 턴 안에서 특정 prefix 의 tool_result 가 이미 있는지 확인한다.

    "현재 턴" 은 마지막 user 메시지 이후의 슬라이스로 정의 — harness 가 매 턴
    user 메시지를 messages 끝에 추가하므로 이 경계가 정확하다.

    이전엔 전체 history 를 검사해서, 같은 client_id 가 "지금 몇 시?" 를 두 번째
    호출했을 때 첫 턴의 tool_result 가 남아 있어 mock 이 다시 트리거되지 않고
    echo 로 빠지는 버그가 있었다.
    """
    last_user_idx = -1
    for i, m in enumerate(messages):
        if m.role == "user":
            last_user_idx = i
    if last_user_idx < 0:
        return False
    for m in messages[last_user_idx + 1 :]:
        if m.role == "tool" and (m.tool_call_id or "").startswith(prefix):
            return True
    return False


def _compose_reply(last_user: Message | None, messages: list[Message]) -> str:
    """도구 결과 또는 echo 텍스트를 조합해 응답 문자열을 만든다."""
    # tool_result 다음 루프 — 직전 도구 응답을 자연어로 포장.
    last = messages[-1] if messages else None
    if last and last.role == "tool":
        call_id = last.tool_call_id or ""
        if call_id.startswith("mock-now-"):
            return f"현재 시각은 {last.content} 입니다."
        if call_id.startswith("mock-todo-"):
            return (
                "보고서 작업 계획을 등록했습니다.\n\n"
                "다음 3단계로 진행됩니다:\n"
                "1. 매출 데이터 조회 (fetch_sales)\n"
                "2. 보고서 본문 생성 (render_report)\n"
                "3. 이메일 발송 (send_email)\n\n"
                "보고 기간을 알려주시면 바로 시작할게요."
            )
        if call_id.startswith("mock-search-"):
            return f"검색이 완료되었습니다. 결과: {last.content}"

    if last_user is None:
        return "안녕하세요. 무엇을 도와드릴까요?"

    return (
        f"[mock] '{last_user.content}' 라고 하셨네요. "
        "실제 LLM 이 연결되면 이 자리에 답변이 옵니다."
    )
