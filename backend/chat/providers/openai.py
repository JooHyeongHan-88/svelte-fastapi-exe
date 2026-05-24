"""OpenAI API provider with streaming support."""

import logging
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from chat.models import (
    DeltaEvent,
    DoneEvent,
    Message,
    StreamEvent,
    ToolCall,
    ToolCallEvent,
)

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """LLM provider using OpenAI API (or compatible endpoint).

    Supports OpenAI, OpenAI-compatible (vLLM, LM Studio, Ollama, Groq, Together, etc.)
    by customizing base_url.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        request_timeout: float = 60.0,
    ) -> None:
        """Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key.
            model: Model identifier (e.g., "gpt-4o", "gpt-4o-mini").
            base_url: Custom API endpoint (for OpenAI-compatible services).
            temperature: Sampling temperature (0.0-2.0).
            max_tokens: Max tokens in response.
            request_timeout: HTTP request timeout in seconds.
        """
        self._client = AsyncOpenAI(
            api_key=api_key or "sk-none",
            base_url=base_url,
            timeout=request_timeout,
        )
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def astream(
        self,
        messages: list[Message],
        tools: list,
    ) -> AsyncIterator[StreamEvent]:
        """Stream response from OpenAI API."""
        wire_messages = [_convert_message_to_wire(m) for m in messages]
        wire_tools = [_convert_tool_spec_to_wire(t) for t in tools]

        try:
            async with self._client.chat.completions.create(
                model=self._model,
                messages=wire_messages,
                tools=wire_tools if wire_tools else None,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                stream=True,
            ) as stream:
                tool_calls_buffer: dict[int, dict] = {}
                current_delta = ""

                async for event in stream:
                    if event.choices and len(event.choices) > 0:
                        choice = event.choices[0]
                        delta = choice.delta

                        # Content delta (text)
                        if delta.content:
                            current_delta = delta.content
                            yield DeltaEvent(content=current_delta)

                        # Tool call started or continued
                        if delta.tool_calls:
                            for tool_call in delta.tool_calls:
                                idx = tool_call.index
                                if idx not in tool_calls_buffer:
                                    tool_calls_buffer[idx] = {
                                        "id": None,
                                        "function": {"name": None, "arguments": ""},
                                    }

                                if tool_call.id:
                                    tool_calls_buffer[idx]["id"] = tool_call.id
                                if tool_call.function and tool_call.function.name:
                                    tool_calls_buffer[idx]["function"]["name"] = (
                                        tool_call.function.name
                                    )
                                if tool_call.function and tool_call.function.arguments:
                                    tool_calls_buffer[idx]["function"]["arguments"] += (
                                        tool_call.function.arguments
                                    )

                        # Finish (tool_calls or stop)
                        if choice.finish_reason in ("tool_calls", "function_call"):
                            for tc in tool_calls_buffer.values():
                                import json

                                args = tc["function"]["arguments"]
                                try:
                                    parsed_args = json.loads(args) if args else {}
                                except json.JSONDecodeError:
                                    parsed_args = {}

                                yield ToolCallEvent(
                                    call=ToolCall(
                                        id=tc["id"] or "unknown",
                                        name=tc["function"]["name"] or "unknown",
                                        arguments=parsed_args,
                                    )
                                )
                            yield DoneEvent()
                            return
                        elif choice.finish_reason == "stop":
                            yield DoneEvent()
                            return

        except Exception:
            logger.exception("OpenAI provider error")
            raise


def _convert_message_to_wire(msg: Message) -> dict:
    """Convert internal Message to OpenAI wire format."""
    result = {"role": msg.role, "content": msg.content}

    if msg.role == "assistant" and msg.tool_calls:
        result["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": _serialize_args(call.arguments),
                },
            }
            for call in msg.tool_calls
        ]

    if msg.role == "tool":
        result = {
            "role": "tool",
            "tool_call_id": msg.tool_call_id,
            "content": msg.content,
        }

    return result


def _convert_tool_spec_to_wire(spec) -> dict:
    """Convert ToolSpec to OpenAI tool schema."""
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        },
    }


def _serialize_args(args: dict) -> str:
    """Serialize arguments dict to JSON string."""
    import json

    return json.dumps(args, ensure_ascii=False)
