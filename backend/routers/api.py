import sys

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

import browser
import updater
from _version import __version__
from config import ALLOWED_ORIGIN


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


class ChatRequest(BaseModel):
    message: str


class ClientRequest(BaseModel):
    client_id: str


@router.post("/chat")
async def chat(req: ChatRequest):
    return {"message": f"Echo: {req.message}"}


@router.post("/register")
async def register(req: ClientRequest):
    browser.register_client(req.client_id)

    print(f"register: {req.client_id}")

    return {"ok": True}


@router.post("/heartbeat")
async def heartbeat(req: ClientRequest):
    browser.touch_client(req.client_id)

    return {"ok": True}


@router.post("/unregister")
async def unregister(req: ClientRequest):
    browser.unregister_client(req.client_id)

    print(f"unregister: {req.client_id}")

    return {"ok": True}


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
