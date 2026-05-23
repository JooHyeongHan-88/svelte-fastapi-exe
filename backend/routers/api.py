import asyncio
import sys

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

import browser
import updater
from _version import __version__
from chat import harness
from chat.models import ChatRequest, ConversationResponse, RestoreRequest
from chat.store import ConversationStore
from chat.tools import registry
from config import (
    ALLOWED_ORIGIN,
    MAX_AGENT_ITERATIONS,
    MAX_HISTORY_MESSAGES,
    PRESENCE_KEEPALIVE_INTERVAL,
    PRESENCE_RETRY_HINT_MS,
    SYSTEM_PROMPT,
)


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


@router.post("/chat")
async def chat(req: ChatRequest, client_id: str = Query(...)) -> StreamingResponse:
    """사용자 메시지 1건에 대한 응답을 SSE 로 흘려보낸다.

    이벤트 포맷: `data: <StreamEvent JSON>\\n\\n`
    이벤트 종류는 chat.models.StreamEvent 의 discriminator 참고.
    """

    async def event_source():
        async for event in harness.run_turn(
            client_id,
            req.message,
            store=_store,
            registry=registry,
            system_prompt=SYSTEM_PROMPT,
            max_iterations=MAX_AGENT_ITERATIONS,
        ):
            yield f"data: {event.model_dump_json()}\n\n"

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
