"""Agent harness — provider 와 도구 사이의 turn 실행 루프.

run_turn 한 번 = 사용자 입력 1건에 대한 응답 1턴(여러 tool 호출 포함 가능).

흐름:
    1. store 에서 client_id 의 기존 히스토리를 가져온다.
    2. system prompt + history + 사용자 메시지로 messages 를 구성.
    3. provider.astream 을 호출하며 이벤트를 그대로 프론트로 흘려보낸다.
       - delta: assistant 본문 버퍼에 누적
       - tool_call: 즉시 도구 실행 → tool_result yield → messages 에 결과 append → 루프 재진입
       - done: 루프 종료
    4. 루프 종료 후 사용자 메시지와 최종 assistant 메시지를 store 에 영구 반영.
"""

import logging
from collections.abc import AsyncIterator

from chat.models import (
    DoneEvent,
    ErrorEvent,
    Message,
    StreamEvent,
    ToolCall,
    ToolResultEvent,
)
from chat.store import ConversationStore
from chat.tools import ToolRegistry

logger = logging.getLogger(__name__)


async def run_turn(
    client_id: str,
    user_message: str,
    *,
    store: ConversationStore,
    registry: ToolRegistry,
    provider,
    system_prompt: str,
    max_iterations: int,
) -> AsyncIterator[StreamEvent]:
    history = store.get_history(client_id)
    user_msg = Message(role="user", content=user_message)

    messages: list[Message] = [
        Message(role="system", content=system_prompt),
        *history,
        user_msg,
    ]

    assistant_buffer: list[str] = []
    pending_tool_calls: list[ToolCall] = []
    turn_messages: list[Message] = [user_msg]

    try:
        for iteration in range(max_iterations):
            del iteration  # 디버깅 시 활용

            assistant_buffer.clear()
            pending_tool_calls.clear()

            async for event in provider.astream(messages, registry.specs()):
                if event.type == "delta":
                    assistant_buffer.append(event.content)
                    yield event
                    continue

                if event.type == "tool_call":
                    pending_tool_calls.append(event.call)
                    yield event
                    continue

                if event.type == "done":
                    break

                # provider 가 직접 error 를 보낸 경우 그대로 전달하고 종료.
                yield event
                return

            assistant_text = "".join(assistant_buffer)

            # tool_call 이 없으면 이번 턴 종료.
            if not pending_tool_calls:
                if assistant_text:
                    turn_messages.append(
                        Message(role="assistant", content=assistant_text)
                    )
                break

            # tool 호출이 있는 assistant 메시지를 messages 에 누적해 다음 iteration 의 컨텍스트로 사용.
            assistant_msg = Message(
                role="assistant",
                content=assistant_text,
                tool_calls=list(pending_tool_calls),
            )
            messages.append(assistant_msg)
            turn_messages.append(assistant_msg)

            for call in pending_tool_calls:
                result_text = await _execute_tool(call, registry)
                tool_msg = Message(
                    role="tool",
                    content=result_text,
                    tool_call_id=call.id,
                )
                messages.append(tool_msg)
                turn_messages.append(tool_msg)

                yield ToolResultEvent(
                    tool_call_id=call.id,
                    name=call.name,
                    result=result_text,
                )
        else:
            # max_iterations 초과 — 안전장치.
            logger.warning("agent harness reached max_iterations=%d", max_iterations)

        store.append(client_id, *turn_messages)
        yield DoneEvent()

    except Exception as exc:  # noqa: BLE001 — 사용자에게 에러 이벤트로 변환해 전달
        logger.exception("harness run_turn failed")
        yield ErrorEvent(message=str(exc))


async def _execute_tool(call: ToolCall, registry: ToolRegistry) -> str:
    tool = registry.get(call.name)
    if tool is None:
        return f"[error] unknown tool: {call.name}"

    try:
        return await tool.run(call.arguments)
    except (ValueError, KeyError, TypeError) as exc:
        return f"[error] {type(exc).__name__}: {exc}"
