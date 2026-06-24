"""Factory function to instantiate LLM provider from settings."""

import logging
from typing import Protocol

from agent.config import LLM_MAX_TOKENS, LLM_TEMPERATURE
from settings.models import LLMSettings

logger = logging.getLogger(__name__)


class LLMProvider(Protocol):
    """Protocol for LLM providers.

    All providers must implement astream() which yields StreamEvent objects.
    """

    async def astream(self, messages, tools):
        """Stream response events (DeltaEvent, ToolCallEvent, DoneEvent, ErrorEvent)."""
        ...


def get_provider(settings: LLMSettings) -> LLMProvider:
    """Get an LLM provider instance based on settings.

    dev 환경에서 ``APP_DEBUG_TRACE`` 가 켜져 있으면 provider 를 ``TracingProvider`` 로
    감싸 wire in/out 을 디버그 트레이스에 기록한다 (frozen 은 강제 비활성).

    Args:
        settings: LLMSettings with provider type and credentials.

    Returns:
        An LLM provider instance ready for use.

    Raises:
        ValueError: If provider type is unsupported or credentials are missing.
    """
    return _maybe_wrap_tracing(_build_provider(settings), settings)


def _maybe_wrap_tracing(provider: LLMProvider, settings: LLMSettings) -> LLMProvider:
    """디버그 트레이스가 활성이면 provider 를 TracingProvider 로 감싼다."""
    from agent.config import DEBUG_TRACE_ENABLED

    if not DEBUG_TRACE_ENABLED:
        return provider

    from agent.debug.trace import TracingProvider
    from settings.masking import mask_api_key

    return TracingProvider(
        provider,
        model=settings.model or "",
        masked_key=mask_api_key(settings.api_key or ""),
        base_url=settings.base_url,
    )


def _build_provider(settings: LLMSettings) -> LLMProvider:
    """settings.provider 분기로 실제 provider 인스턴스를 만든다."""
    if settings.provider == "mock":
        from agent.providers.mock import MockProvider

        return MockProvider()

    if settings.provider == "dtgpt":
        from agent.config import DTGPT_BASE_URL

        if not DTGPT_BASE_URL:
            raise ValueError("DTGPT requires APP_DTGPT_BASE_URL to be configured")
        if not settings.api_key or not settings.model:
            raise ValueError("DTGPT requires api_key and model")

        from agent.providers.openai import OpenAIProvider

        return OpenAIProvider(
            api_key=settings.api_key,
            model=settings.model,
            base_url=DTGPT_BASE_URL,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )

    if settings.provider == "openai_compatible":
        if not settings.api_key or not settings.model or not settings.base_url:
            raise ValueError("OpenAI-compatible requires api_key, model, and base_url")

        from agent.providers.openai import OpenAIProvider

        return OpenAIProvider(
            api_key=settings.api_key,
            model=settings.model,
            base_url=settings.base_url,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )

    raise ValueError(f"unsupported provider: {settings.provider}")
