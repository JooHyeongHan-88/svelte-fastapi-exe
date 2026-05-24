"""Mock LLM provider for UI validation without real API calls.

지원하는 시나리오 (SKILLS 라우팅 검증용):
    1. now tool  — "지금 몇 시", "현재 시각" 등 → now 도구 호출 → 시각 응답
    2. add_todo  — "보고서", "리포트", "report" → add_todo 도구 호출 (3-step 플래너)
    3. 기본 echo — 위 트리거가 없으면 메시지를 그대로 echo
"""

import asyncio
import uuid
from collections.abc import AsyncIterator

from agent.models import (
    DeltaEvent,
    DoneEvent,
    Message,
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


class MockProvider:
    """LLM 없이 UI 검증을 위한 가짜 프로바이더.

    시나리오 1 (skill_time):
        트리거 키워드 포함 + 이번 턴에 now 아직 미호출 → ToolCallEvent(now) 발생.
        tool_result 가 담긴 다음 루프에서는 시각 텍스트를 delta 로 응답.

    시나리오 2 (skill_report):
        트리거 키워드 포함 + 이번 턴에 add_todo 아직 미호출 → ToolCallEvent(add_todo) 발생.
        harness 가 TodoUpdateEvent 를 yield 한 뒤 provider 를 재호출하면, 이 분기로
        들어와 계획이 완성됐다는 텍스트를 echo.

    시나리오 3 (기본 echo):
        위 트리거 없음 → 사용자 메시지를 그대로 echo.
    """

    async def astream(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> AsyncIterator[StreamEvent]:
        """Stream mock response events."""
        last_user = _find_last_user(messages)

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

        # ── 기본 echo ─────────────────────────────────────────────────────────
        reply = _compose_reply(last_user, messages)
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

    if last_user is None:
        return "안녕하세요. 무엇을 도와드릴까요?"

    return (
        f"[mock] '{last_user.content}' 라고 하셨네요. "
        "실제 LLM 이 연결되면 이 자리에 답변이 옵니다."
    )
