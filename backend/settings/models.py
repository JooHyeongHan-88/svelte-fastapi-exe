"""Data models for LLM settings."""

from typing import Literal

from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    """Provider별 접속 정보."""

    model: str = ""
    api_key: str = ""
    base_url: str = ""


class LLMSettings(BaseModel):
    """LLM provider connection configuration.

    Persisted to disk as JSON. Generation parameters (temperature, max_tokens)
    are managed via environment variables, not here.

    providers 에 각 provider 의 접속 정보를 캐싱한다. active provider 가 바뀌어도
    이전 provider 의 값이 유지되어 다시 선택했을 때 그대로 복원된다.
    """

    provider: Literal["mock", "openai_compatible", "dtgpt"] = "mock"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    # 사용자가 SettingsModal 에서 작성한 추가 지침. 비어 있지 않으면 매 턴 system prompt
    # 베이스 뒤에 "# 사용자 지침" 섹션으로 합성된다. 2000자 상한은 토큰 예산 보호용.
    user_prompt: str = Field(default="", max_length=2000)

    def active(self) -> ProviderConfig:
        """활성 provider 의 접속 정보를 반환한다. 없으면 빈 ProviderConfig 생성."""
        if self.provider not in self.providers:
            self.providers[self.provider] = ProviderConfig()
        return self.providers[self.provider]

    # 하위호환 프로퍼티 — factory.py 등이 settings.model / settings.api_key 로 접근하던 코드.
    @property
    def model(self) -> str:
        return self.active().model

    @property
    def api_key(self) -> str:
        return self.active().api_key

    @property
    def base_url(self) -> str:
        return self.active().base_url


class ProviderMeta(BaseModel):
    """Metadata about an available LLM provider for UI rendering."""

    id: Literal["mock", "openai_compatible", "dtgpt"]
    label: str
    requires_api_key: bool
    requires_base_url: bool
    requires_model: bool
    suggested_models: list[str]
    docs_url: str | None = None


class ConnectionTestRequest(BaseModel):
    """Request to test LLM provider connectivity."""

    provider: Literal["mock", "openai_compatible", "dtgpt"]
    model: str = ""
    api_key: str = ""
    base_url: str = ""


class ConnectionTestResult(BaseModel):
    """Result of testing LLM provider connectivity."""

    ok: bool
    message: str
    latency_ms: float | None = None
