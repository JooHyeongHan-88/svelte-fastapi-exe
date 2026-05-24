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

    Args:
        settings: LLMSettings with provider type and credentials.

    Returns:
        An LLM provider instance ready for use.

    Raises:
        ValueError: If provider type is unsupported or credentials are missing.
    """
    if settings.provider == "mock":
        from agent.providers.mock import MockProvider

        return MockProvider()

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
