"""Presence SSE — 클라이언트 생존을 단일 채널로 추적."""

import asyncio

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from api.deps import require_local_origin
from core import browser
from core.config import PRESENCE_KEEPALIVE_INTERVAL, PRESENCE_RETRY_HINT_MS

router = APIRouter(prefix="/api", dependencies=[Depends(require_local_origin)])


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
