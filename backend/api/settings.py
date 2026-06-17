"""LLM 설정 CRUD + 프로바이더 메타 + 연결 테스트 + 앱 정보 라우터."""

from fastapi import APIRouter, Depends

from agent.models import Message
from agent.providers.factory import get_provider
from api.deps import _settings_store, require_local_origin
from core import config
from core.config import APP_NAME
from core.version import APP_VERSION
from settings.masking import mask_api_key
from settings.models import (
    ConnectionTestRequest,
    ConnectionTestResult,
    LLMSettings,
    ProviderMeta,
)

router = APIRouter(prefix="/api", dependencies=[Depends(require_local_origin)])


@router.get("/app-info")
async def get_app_info() -> dict:
    """앱 이름과 버전 정보를 반환한다."""
    return {"name": APP_NAME, "version": APP_VERSION}


@router.get("/settings")
async def get_settings() -> LLMSettings:
    """Get current LLM settings (api_key masked for all providers)."""
    settings = _settings_store.get()
    for cfg in settings.providers.values():
        cfg.api_key = mask_api_key(cfg.api_key)
    return settings


@router.post("/settings")
async def update_settings(patch: dict) -> LLMSettings:
    """Update LLM settings from partial patch dict.

    Fields not in patch are left unchanged. Empty api_key clears it.
    """
    updated = _settings_store.update(patch)
    for cfg in updated.providers.values():
        cfg.api_key = mask_api_key(cfg.api_key)
    return updated


@router.get("/settings/providers")
async def list_providers() -> list[ProviderMeta]:
    """Get metadata for available LLM providers.

    Mock provider 는 dev·qa 채널에서만 노출한다. prod 빌드에서는 목록에서 제외해
    설정 UI 에 뜨지 않게 한다(프론트는 이 응답만으로 구동되므로 별도 처리 불필요).
    """
    providers = [
        ProviderMeta(
            id="dtgpt",
            label="DTGPT",
            requires_api_key=True,
            requires_base_url=False,
            requires_model=True,
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

    if config.BUILD_CHANNEL != "prod":
        providers.append(
            ProviderMeta(
                id="mock",
                label="Mock (Test Mode)",
                requires_api_key=False,
                requires_base_url=False,
                requires_model=False,
                suggested_models=[],
                docs_url=None,
            )
        )

    return providers


@router.get("/settings/models")
async def list_models(provider: str) -> dict:
    """provider 가 제공하는 모델 목록을 반환한다.

    openai_compatible / dtgpt 는 {base_url}/models 엔드포인트를 호출한다.
    실패하거나 mock 인 경우 빈 리스트를 반환한다.
    """
    import asyncio

    from agent.config import DTGPT_BASE_URL

    if provider == "mock":
        return {"models": ["mock-fast", "mock-smart"]}

    stored = _settings_store.get()
    cfg = stored.providers.get(provider)

    if provider == "dtgpt":
        base_url = DTGPT_BASE_URL
        api_key = cfg.api_key if cfg else ""
    else:
        base_url = cfg.base_url if cfg else ""
        api_key = cfg.api_key if cfg else ""

    if not base_url or not api_key:
        return {"models": [], "error": "base_url 또는 api_key 가 설정되지 않았습니다."}

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=api_key or "sk-none", base_url=base_url, timeout=10.0
        )

        async def _fetch_models() -> list[str]:
            response = await client.models.list()
            return sorted(m.id for m in response.data)

        models = await asyncio.wait_for(_fetch_models(), timeout=10.0)
        return {"models": models}
    except Exception as exc:
        return {"models": [], "error": str(exc)[:120]}


@router.post("/settings/test")
async def test_connection(req: ConnectionTestRequest) -> ConnectionTestResult:
    """Test LLM provider connectivity without saving.

    Returns latency if successful, error message otherwise.
    If api_key is not provided in the request, falls back to the currently stored key
    so users can test without re-entering their key.
    """
    try:
        # api_key가 비어 있으면 저장된 키를 fallback으로 사용.
        # cross-provider 키 노출 방지를 위해 같은 provider 슬롯에서만 가져온다.
        effective_api_key = req.api_key
        if not effective_api_key:
            stored = _settings_store.get()
            stored_cfg = stored.providers.get(req.provider)
            if stored_cfg:
                effective_api_key = stored_cfg.api_key

        # Create temporary settings for testing
        from settings.models import ProviderConfig

        test_settings = LLMSettings(
            provider=req.provider,
            providers={
                req.provider: ProviderConfig(
                    model=req.model,
                    api_key=effective_api_key or "",
                    base_url=req.base_url,
                )
            },
        )

        # Get provider instance
        provider = get_provider(test_settings)

        # Test with a simple message (no tools)
        import asyncio
        import time

        message = [Message(role="user", content="ping")]

        # For mock provider, just return ok immediately
        if req.provider == "mock":
            return ConnectionTestResult(
                ok=True,
                message="Mock provider ready",
                latency_ms=0,
            )

        # For real providers, measure latency
        start = time.perf_counter()

        async def _consume_stream() -> None:
            async for _ in provider.astream(message, []):
                pass

        try:
            await asyncio.wait_for(_consume_stream(), timeout=10.0)
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
