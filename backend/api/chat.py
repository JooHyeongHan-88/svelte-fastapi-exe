"""채팅 SSE + 대화 히스토리 (restore/reset 포함) 라우터."""

import asyncio
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from agent import harness
from agent.config import (
    MAX_AGENT_CALLS_PER_TURN,
    MAX_AGENT_ITERATIONS,
    ORCHESTRATOR_API_REFS,
)
from agent.models import (
    ChatRequest,
    ConversationResponse,
    DoneEvent,
    ErrorEvent,
    RestoreRequest,
)
from agent.providers.factory import get_provider
from agent.registries.agents import registry as agent_registry
from agent.registries.prompts import registry as prompt_registry
from agent.registries.skills import registry as skill_registry
from agent.registries.tools import registry
from api.deps import _settings_store, _state_store, _store, require_local_origin
from core.log_collector import collector as log_collector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", dependencies=[Depends(require_local_origin)])

# 동시 턴 가드 — 같은 client_id 로 턴이 진행 중이면 두 번째 요청을 즉시 거부한다.
# 탭 복제(같은 세션 공유)에서 양쪽이 전송하면 두 run_turn 이 병주해 히스토리 교차
# 저장·state Last-Write-Wins 오염이 발생한다. 프론트 ui.streaming 가드는 탭 단위라
# 백엔드에서 한 번 더 막는다. uvicorn 단일 event loop 에서 check-and-add 사이에
# await 가 없으므로 set 만으로 원자적이다.
_active_turn_clients: set[str] = set()

_BUSY_TURN_MESSAGE = (
    "이미 응답을 생성 중입니다. 진행 중인 응답이 끝난 뒤 다시 시도하세요."
)


@router.post("/chat")
async def chat(
    req: ChatRequest,
    client_id: str = Query(...),
    session_title: str = Query(""),
) -> StreamingResponse:
    """사용자 메시지 1건에 대한 응답을 SSE 로 흘려보낸다.

    이벤트 포맷: `data: <StreamEvent JSON>\\n\\n`
    이벤트 종류는 chat.models.StreamEvent 의 discriminator 참고.
    """

    async def event_source():
        if client_id in _active_turn_clients:
            logger.warning("동시 턴 거부: client_id=%s 턴 진행 중", client_id)
            yield f"data: {ErrorEvent(message=_BUSY_TURN_MESSAGE).model_dump_json()}\n\n"
            yield f"data: {DoneEvent().model_dump_json()}\n\n"
            return
        _active_turn_clients.add(client_id)
        # 사용 로그 tap — run_turn 이 흘리는 이벤트를 여기 한 곳에서 관찰해 Loki 로 남긴다
        # (하니스 무변경, 미설정 시 no-op). ESC 취소 포함 모든 경로에서 finally 로 마감.
        tap = log_collector.new_turn(client_id)
        tap.query(req.message, title=session_title)
        cancelled = False
        try:
            settings = _settings_store.get()
            provider = get_provider(settings)
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
                max_iterations=MAX_AGENT_ITERATIONS,
                max_agent_calls=MAX_AGENT_CALLS_PER_TURN,
                force_skills=req.force_skills,
                session_title=session_title,
                user_prompt=settings.user_prompt,
                orchestrator_api_refs=ORCHESTRATOR_API_REFS,
            ):
                tap.observe(event)
                yield f"data: {event.model_dump_json()}\n\n"
        except asyncio.CancelledError:
            # 클라이언트가 SSE 연결을 닫았거나 사용자가 ESC 로 취소 — 정상 종료.
            # Exception 으로 로깅하면 운영 로그에 노이즈가 쌓이므로 debug 레벨로만 기록.
            cancelled = True
            logger.debug(
                "chat SSE cancelled for client_id=%s (client disconnect or ESC)",
                client_id,
            )
            raise  # Starlette/uvicorn 이 연결 정리를 완료할 수 있도록 재전파.
        except Exception as exc:
            logger.exception("chat event_source error for client_id=%s", client_id)
            # str(exc) 는 API 키·URL 등 민감 정보를 노출할 수 있으므로 type 만 전달.
            safe_msg = f"[{type(exc).__name__}] 처리 중 오류가 발생했습니다."
            tap.observe(ErrorEvent(message=safe_msg))
            yield f"data: {ErrorEvent(message=safe_msg).model_dump_json()}\n\n"
        finally:
            tap.finish(cancelled=cancelled)
            # CancelledError 포함 모든 종료 경로에서 가드 해제.
            _active_turn_clients.discard(client_id)

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
