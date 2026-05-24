import asyncio
import logging
import sys

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

import browser
import updater
from _version import __version__
from chat import harness
from chat.models import ChatRequest, ConversationResponse, RestoreRequest
from chat.providers.factory import get_provider
from chat.store import ConversationStore
from chat.tools import registry
from config import (
    ALLOWED_ORIGIN,
    MAX_AGENT_ITERATIONS,
    MAX_HISTORY_MESSAGES,
    PRESENCE_KEEPALIVE_INTERVAL,
    PRESENCE_RETRY_HINT_MS,
    SETTINGS_FILE_PATH,
    SYSTEM_PROMPT,
)
from settings.masking import mask_api_key
from settings.models import (
    ConnectionTestRequest,
    ConnectionTestResult,
    LLMSettings,
    ProviderMeta,
)
from settings.store import SettingsStore

logger = logging.getLogger(__name__)


def require_local_origin(
    origin: str | None = Header(default=None),
    sec_fetch_site: str | None = Header(default=None, alias="sec-fetch-site"),
) -> None:
    # frozen 이 아닌 dev 모드에서는 Vite proxy 가 다른 origin 으로 요청을 보내므로 가드 비활성화.
    if not getattr(sys, "frozen", False):
        return

    # 브라우저가 같은 origin 으로 요청한 경우만 통과.
    # - Origin 헤더가 있으면 ALLOWED_ORIGIN 과 일치해야 함.
    # - Origin 헤더가 없는 same-origin GET 같은 경우는 sec-fetch-site 가 same-origin/none 이어야 함.
    if origin is not None:
        if origin != ALLOWED_ORIGIN:
            raise HTTPException(status_code=403, detail="origin not allowed")
        return

    if sec_fetch_site is not None and sec_fetch_site not in ("same-origin", "none"):
        raise HTTPException(status_code=403, detail="cross-site request blocked")


router = APIRouter(prefix="/api", dependencies=[Depends(require_local_origin)])

# 프로세스 전역 대화 저장소. browser._connections 와 동일하게 인메모리 단일 인스턴스.
_store = ConversationStore(max_history=MAX_HISTORY_MESSAGES)


# 프로세스 전역 설정 저장소. 파일 기반 영속화, 스레드 안전.
def _init_settings_store() -> SettingsStore:
    """Initialize settings store with legacy env var fallback."""
    store = SettingsStore(file_path=SETTINGS_FILE_PATH)
    # If settings file doesn't exist, try to seed from env vars
    if not SETTINGS_FILE_PATH.exists():
        from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_PROVIDER

        patch = {}
        if LLM_PROVIDER and LLM_PROVIDER != "mock":
            patch["provider"] = LLM_PROVIDER
        if LLM_MODEL:
            patch["model"] = LLM_MODEL
        if LLM_API_KEY:
            patch["api_key"] = LLM_API_KEY
        if LLM_BASE_URL:
            patch["base_url"] = LLM_BASE_URL
        if patch:
            store.update(patch)
    return store


_settings_store = _init_settings_store()


@router.post("/chat")
async def chat(req: ChatRequest, client_id: str = Query(...)) -> StreamingResponse:
    """사용자 메시지 1건에 대한 응답을 SSE 로 흘려보낸다.

    이벤트 포맷: `data: <StreamEvent JSON>\\n\\n`
    이벤트 종류는 chat.models.StreamEvent 의 discriminator 참고.
    """
    settings = _settings_store.get()
    provider = get_provider(settings)

    async def event_source():
        try:
            async for event in harness.run_turn(
                client_id,
                req.message,
                store=_store,
                registry=registry,
                provider=provider,
                system_prompt=SYSTEM_PROMPT,
                max_iterations=MAX_AGENT_ITERATIONS,
            ):
                yield f"data: {event.model_dump_json()}\n\n"
        except Exception:
            # Log but don't expose full error to client
            logger.exception("chat event_source error")
            raise

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        # nginx 등 중간 프록시가 버퍼링하지 못하도록 표시. uvicorn 직결이면 무해.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversation")
async def get_conversation(
    client_id: str = Query(...),
) -> ConversationResponse:
    """현재 client 의 대화 히스토리. 새로고침 후 복원용."""
    history = _store.get_history(client_id)
    # system 메시지는 harness 가 매 턴 다시 붙이므로 사용자에게는 노출하지 않음.
    visible = [m for m in history if m.role != "system"]
    return ConversationResponse(messages=visible)


@router.delete("/conversation")
async def reset_conversation(client_id: str = Query(...)) -> dict:
    """현재 client 의 대화를 비운다 (새 대화 버튼)."""
    _store.reset(client_id)
    return {"ok": True}


@router.post("/conversation/restore")
async def restore_conversation(
    req: RestoreRequest, client_id: str = Query(...)
) -> dict:
    """프론트 localStorage 의 히스토리를 백엔드 store 에 다시 주입.

    EXE 재시작이나 세션 전환 시 LLM context 가 끊기지 않도록 사용한다.
    system 메시지는 harness 가 매 턴 다시 머리에 붙이므로 여기서 받아도 의미 없음 — 제거.
    """
    payload = [m for m in req.messages if m.role != "system"]
    _store.reset(client_id)
    if payload:
        _store.append(client_id, *payload)
    return {"ok": True}


@router.get("/presence")
async def presence(request: Request, client_id: str = Query(...)) -> StreamingResponse:
    """클라이언트 생존을 SSE 단일 채널로 추적한다.

    연결 유지 = 살아있음. EventSource 종료 시 generator finally 가 disconnect_client
    를 부르고, browser.py 의 grace timer 가 F5/네트워크 블립을 흡수한다.
    """

    async def stream():
        browser.connect_client(client_id)
        print(f"connect: {client_id}")

        try:
            # EventSource 가 재연결할 때 사용할 backoff 힌트 (ms).
            yield f"retry: {PRESENCE_RETRY_HINT_MS}\n\n"
            yield ": connected\n\n"

            while True:
                await asyncio.sleep(PRESENCE_KEEPALIVE_INTERVAL)

                if await request.is_disconnected():
                    break

                yield ": ping\n\n"
        finally:
            browser.disconnect_client(client_id)
            print(f"disconnect: {client_id}")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/version")
async def version():
    return {"version": __version__}


@router.get("/update/check")
async def update_check():
    return updater.check_latest()


@router.post("/update/apply")
async def update_apply():
    return updater.apply_update()


@router.get("/update/status")
async def update_status():
    return updater.get_state()


# ---------------------------------------------------------------------------
# Settings management
# ---------------------------------------------------------------------------


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
