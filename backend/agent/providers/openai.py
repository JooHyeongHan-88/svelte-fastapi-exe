"""OpenAI API provider with streaming support."""

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)

from agent.models import (
    MALFORMED_TOOL_ARGS_KEY,
    DeltaEvent,
    DoneEvent,
    Message,
    ReasoningEvent,
    StreamEvent,
    ToolCall,
    ToolCallEvent,
)

logger = logging.getLogger(__name__)

# 일시적(transient) 오류 — 스트림 생성 전이므로 안전하게 재시도 가능.
# 인증(401)·잘못된 요청(400) 등 영구 오류는 포함하지 않는다 (재시도 무의미).
_RETRYABLE_ERRORS = (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    InternalServerError,
)
_MAX_RETRIES = 2  # 총 3회 시도 (최초 1 + 재시도 2)
_RETRY_BASE_DELAY = 0.5  # 초 — 지수 백오프 기준값


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
        """Stream response from OpenAI API.

        스트림 생성은 일시 오류에 한해 백오프 재시도한다(F4). 스트림이 어떤
        이유로 끝나든(tool_calls/stop/length/연결종료) 종료 시 버퍼된 tool_call 을
        flush 하고 DoneEvent 를 정확히 한 번 보낸다(F2) — 응답 잘림으로 tool_call
        이 증발하거나 DoneEvent 가 누락되는 것을 방지.
        """
        wire_messages = [_convert_message_to_wire(m) for m in messages]
        wire_tools = [_convert_tool_spec_to_wire(t) for t in tools]

        stream = await self._create_stream_with_retry(wire_messages, wire_tools)

        tool_calls_buffer: dict[int, dict] = {}
        finish_reason: str | None = None

        try:
            async for event in stream:
                if not (event.choices and len(event.choices) > 0):
                    continue
                choice = event.choices[0]
                delta = choice.delta

                # Reasoning content (OpenAI o-series 모델의 thinking 토큰).
                # getattr 로 접근해 reasoning_content 가 없는 모델에서도 안전하게 동작.
                reasoning_chunk = getattr(delta, "reasoning_content", None)
                if reasoning_chunk:
                    yield ReasoningEvent(content=reasoning_chunk)

                if delta.content:
                    yield DeltaEvent(content=delta.content)

                if delta.tool_calls:
                    _accumulate_tool_calls(tool_calls_buffer, delta.tool_calls)

                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                    break
        except Exception:
            # 스트림 도중 오류는 이미 일부 이벤트를 yield 했을 수 있어 안전한
            # 재시도가 불가능하다. 로깅 후 전파 → harness 가 ErrorEvent 로 변환.
            logger.exception("OpenAI provider error mid-stream")
            raise

        # 응답 잘림 경고 — 인자/본문이 불완전할 수 있음을 운영 로그에 남긴다.
        if finish_reason == "length":
            logger.warning(
                "OpenAI response truncated (finish_reason=length) — "
                "tool_call 인자나 본문이 불완전할 수 있습니다."
            )

        # 스트림이 어떻게 끝났든 버퍼된 tool_call 을 flush (F2: length·연결종료 시 증발 방지).
        for tc in tool_calls_buffer.values():
            yield ToolCallEvent(
                call=ToolCall(
                    id=tc["id"] or "unknown",
                    name=tc["function"]["name"] or "unknown",
                    arguments=_parse_tool_arguments(tc["function"]["arguments"]),
                )
            )

        yield DoneEvent()

    async def _create_stream_with_retry(self, wire_messages: list, wire_tools: list):
        """chat.completions.create 를 일시 오류에 한해 지수 백오프로 재시도한다.

        스트림을 받기 전(=아무 이벤트도 yield 하기 전) 단계이므로 재시도가 안전하다.
        영구 오류(인증·400 등)는 _RETRYABLE_ERRORS 에 없으므로 즉시 전파된다.
        """
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return await self._client.chat.completions.create(
                    model=self._model,
                    messages=wire_messages,
                    tools=wire_tools if wire_tools else None,
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                    stream=True,
                )
            except _RETRYABLE_ERRORS as exc:
                last_exc = exc
                if attempt >= _MAX_RETRIES:
                    break
                delay = _RETRY_BASE_DELAY * (2**attempt) + random.uniform(0, 0.3)
                logger.warning(
                    "OpenAI create() 일시 오류 (시도 %d/%d): %s — %.1fs 후 재시도",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    type(exc).__name__,
                    delay,
                )
                await asyncio.sleep(delay)
        assert last_exc is not None
        logger.exception("OpenAI create() 재시도 소진 — 전파", exc_info=last_exc)
        raise last_exc


def _accumulate_tool_calls(buffer: dict[int, dict], delta_tool_calls: list) -> None:
    """스트리밍 delta 의 tool_call 조각들을 index 별 버퍼에 누적한다."""
    for tool_call in delta_tool_calls:
        idx = tool_call.index
        if idx not in buffer:
            buffer[idx] = {"id": None, "function": {"name": None, "arguments": ""}}
        if tool_call.id:
            buffer[idx]["id"] = tool_call.id
        if tool_call.function and tool_call.function.name:
            buffer[idx]["function"]["name"] = tool_call.function.name
        if tool_call.function and tool_call.function.arguments:
            buffer[idx]["function"]["arguments"] += tool_call.function.arguments


def _parse_tool_arguments(raw: str) -> dict:
    """tool_call 인자 JSON 문자열을 dict 로 파싱한다 (F3).

    빈 문자열은 인자 없는 정상 호출이므로 {} 로 둔다. 비어 있지 않은데 파싱에
    실패하면(스트리밍 잘림·이스케이프 깨짐) 빈 dict 로 뭉개지 않고 원본을
    MALFORMED_TOOL_ARGS_KEY 에 담아, harness 가 "슬롯 누락" 으로 오인해 사용자에게
    되묻는 대신 LLM 에게 재전송을 요구하도록 한다.
    """
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("tool_call arguments JSON 파싱 실패 — 원본 보존: %.120s", raw)
        return {MALFORMED_TOOL_ARGS_KEY: raw}


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
    return json.dumps(args, ensure_ascii=False)
