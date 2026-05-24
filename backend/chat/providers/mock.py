"""Mock LLM provider for UI validation without real API calls."""

import asyncio
import uuid
from collections.abc import AsyncIterator

from chat.models import (
    DeltaEvent,
    DoneEvent,
    Message,
    StreamEvent,
    ToolCall,
    ToolCallEvent,
    ToolSpec,
)

# Delay between mock tokens to simulate streaming.
_MOCK_TOKEN_DELAY = 0.02

# Triggers for MockProvider to fake "now" tool call.
_NOW_TOOL_TRIGGERS = (
    "몇 시",
    "지금 시간",
    "현재 시각",
    "what time",
    "current time",
    "now()",
)


class MockProvider:
    """Fake LLM provider for testing UI without real API.

    Behavior:
        - If last user message contains a time-related trigger and 'now' tool
          hasn't been called in this turn, yields a fake tool_call event.
        - Otherwise, echoes the user message char by char as deltas.
    """

    async def astream(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> AsyncIterator[StreamEvent]:
        """Stream mock response events."""
        last_user = _find_last_user(messages)
        already_called_now = any(
            m.role == "tool" and (m.tool_call_id or "").startswith("mock-now-")
            for m in messages
        )

        if (
            last_user is not None
            and _should_call_now(last_user.content)
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

        reply = _compose_reply(last_user, messages)
        for ch in reply:
            await asyncio.sleep(_MOCK_TOKEN_DELAY)
            yield DeltaEvent(content=ch)

        yield DoneEvent()


def _find_last_user(messages: list[Message]) -> Message | None:
    """Find the most recent user message in the conversation."""
    for m in reversed(messages):
        if m.role == "user":
            return m
    return None


def _should_call_now(text: str) -> bool:
    """Check if text contains time-related keywords."""
    lowered = text.lower()
    return any(trigger.lower() in lowered for trigger in _NOW_TOOL_TRIGGERS)


def _compose_reply(last_user: Message | None, messages: list[Message]) -> str:
    """Compose a mock response based on context."""
    if messages and messages[-1].role == "tool":
        return f"현재 시각은 {messages[-1].content} 입니다."

    if last_user is None:
        return "안녕하세요. 무엇을 도와드릴까요?"

    return f"[mock] '{last_user.content}' 라고 하셨네요. 실제 LLM 이 연결되면 이 자리에 답변이 옵니다."
