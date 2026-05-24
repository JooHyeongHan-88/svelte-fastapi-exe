"""Data models for LLM settings."""

from typing import Literal

from pydantic import BaseModel


class LLMSettings(BaseModel):
    """LLM provider connection configuration.

    Persisted to disk as JSON. Generation parameters (temperature, max_tokens)
    and system_prompt are managed via config.py / environment variables, not here.
    """

    provider: Literal["mock", "openai_compatible"] = "mock"
    model: str = ""
    api_key: str = ""
    base_url: str = ""  # For openai_compatible (e.g., http://localhost:8000/v1)


class ProviderMeta(BaseModel):
    """Metadata about an available LLM provider for UI rendering."""

    id: Literal["mock", "openai_compatible"]
    label: str
    requires_api_key: bool
    requires_base_url: bool
    requires_model: bool
    suggested_models: list[str]
    docs_url: str | None = None


class ConnectionTestRequest(BaseModel):
    """Request to test LLM provider connectivity."""

    provider: Literal["mock", "openai_compatible"]
    model: str = ""
    api_key: str = ""
    base_url: str = ""


class ConnectionTestResult(BaseModel):
    """Result of testing LLM provider connectivity."""

    ok: bool
    message: str
    latency_ms: float | None = None
