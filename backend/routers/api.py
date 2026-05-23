import time

from fastapi import APIRouter
from pydantic import BaseModel

from browser import clients

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    message: str


class ClientRequest(BaseModel):
    client_id: str


@router.post("/chat")
async def chat(req: ChatRequest):
    return {"message": f"Echo: {req.message}"}


@router.post("/register")
async def register(req: ClientRequest):
    clients[req.client_id] = time.time()

    print(f"register: {req.client_id}")

    return {"ok": True}


@router.post("/heartbeat")
async def heartbeat(req: ClientRequest):
    clients[req.client_id] = time.time()

    return {"ok": True}


@router.post("/unregister")
async def unregister(req: ClientRequest):
    clients.pop(req.client_id, None)

    print(f"unregister: {req.client_id}")

    return {"ok": True}