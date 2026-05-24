"""LLM 설정 CRUD + 프로바이더 메타 + 연결 테스트 라우터."""

from fastapi import APIRouter, Depends

from agent.providers.factory import get_provider
from api.deps import _settings_store, require_local_origin
from settings.masking import mask_api_key
from settings.models import (
    ConnectionTestRequest,
    ConnectionTestResult,
    LLMSettings,
    ProviderMeta,
)

router = APIRouter(prefix="/api", dependencies=[Depends(require_local_origin)])


@router.get("/settings")
async def get_settings() -> LLMSettings:
    """Get current LLM settings (api_key masked)."""
    settings = _settings_store.get()
    settings.api_key = mask_api_key(settings.api_key)
    return settings


@router.post("/settings")
async def update_settings(patch: dict) -> LLMSettings:
    """Update LLM settings from partial patch dict.

    Fields not in patch are left unchanged. Empty api_key clears it.
    """
    updated = _settings_store.update(patch)
    updated.api_key = mask_api_key(updated.api_key)
    return updated


@router.get("/settings/providers")
async def list_providers() -> list[ProviderMeta]:
    """Get metadata for available LLM providers."""
    return [
        ProviderMeta(
            id="mock",
            label="Mock (Test Mode)",
            requires_api_key=False,
            requires_base_url=False,
            requires_model=False,
            suggested_models=[],
            docs_url=None,
        ),
        ProviderMeta(
            id="openai_compatible",
            label="OpenAI Compatible",
            requires_api_key=True,
            requires_base_url=True,
            requires_model=True,
            suggested_models=[
                "gpt-4o",
                "gpt-4o-mini",
                "mistral-7b",
                "llama-3-70b",
            ],
            docs_url="https://platform.openai.com/docs/api-reference",
        ),
    ]


@router.post("/settings/test")
async def test_connection(req: ConnectionTestRequest) -> ConnectionTestResult:
    """Test LLM provider connectivity without saving.

    Returns latency if successful, error message otherwise.
    If api_key is not provided in the request, falls back to the currently stored key
    so users can test without re-entering their key.
    """
    try:
        # api_key가 비어 있으면 저장된 키를 fallback으로 사용.
        # 같은 프로바이더일 때만 — cross-provider 키 노출 방지.
        effective_api_key = req.api_key
        if not effective_api_key:
            stored = _settings_store.get()
            if stored.provider == req.provider:
                effective_api_key = stored.api_key

        # Create temporary settings for testing
        test_settings = LLMSettings(
            provider=req.provider,
            model=req.model,
            api_key=effective_api_key,
            base_url=req.base_url,
        )

        # Get provider instance
        provider = get_provider(test_settings)

        # Test with a simple message (no tools)
        import asyncio

        message = [
            {
                "role": "user",
                "content": "ping",
            }
        ]

        # For mock provider, just return ok immediately
        if req.provider == "mock":
            return ConnectionTestResult(
                ok=True,
                message="Mock provider ready",
                latency_ms=0,
            )

        # For real providers, measure latency
        import time

        start = time.perf_counter()

        # Use asyncio.wait_for with timeout
        try:
            async for event in asyncio.wait_for(
                provider.astream(message, []), timeout=10.0
            ):
                pass  # Just consume events
        except asyncio.TimeoutError:
            return ConnectionTestResult(
                ok=False,
                message="Connection timeout (10s)",
                latency_ms=10000,
            )

        elapsed_ms = (time.perf_counter() - start) * 1000

        return ConnectionTestResult(
            ok=True,
            message=f"{req.provider} {req.model} reachable",
            latency_ms=elapsed_ms,
        )

    except ValueError as e:
        # Config validation error
        return ConnectionTestResult(
            ok=False,
            message=f"Config error: {str(e)}",
        )
    except Exception as e:
        # Network or auth error
        error_msg = str(e)
        if "401" in error_msg or "unauthorized" in error_msg.lower():
            return ConnectionTestResult(
                ok=False,
                message="Unauthorized: Check API key",
            )
        return ConnectionTestResult(
            ok=False,
            message=f"Connection failed: {error_msg[:100]}",
        )
