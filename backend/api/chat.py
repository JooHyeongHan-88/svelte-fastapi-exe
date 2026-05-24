"""채팅 SSE + 대화 히스토리 (restore/reset 포함) 라우터."""

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from agent import harness
from agent.config import MAX_AGENT_CALLS_PER_TURN, MAX_AGENT_ITERATIONS, SYSTEM_PROMPT
from agent.models import ChatRequest, ConversationResponse, RestoreRequest
from agent.providers.factory import get_provider
from agent.registries.agents import registry as agent_registry
from agent.registries.prompts import registry as prompt_registry
from agent.registries.skills import registry as skill_registry
from agent.registries.tools import registry
from api.deps import _settings_store, _state_store, _store, require_local_origin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", dependencies=[Depends(require_local_origin)])


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
                state_store=_state_store,
                skill_registry=skill_registry,
                prompt_registry=prompt_registry,
                registry=registry,
                agent_registry=agent_registry,
                provider=provider,
                system_prompt_fallback=SYSTEM_PROMPT,
                max_iterations=MAX_AGENT_ITERATIONS,
                max_agent_calls=MAX_AGENT_CALLS_PER_TURN,
                force_skills=req.force_skills,
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
    """현재 client 의 대화와 에이전트 상태(todo/pending slot)를 함께 비운다."""
    _store.reset(client_id)
    _state_store.reset(client_id)
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
