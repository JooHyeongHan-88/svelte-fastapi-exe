"""FastAPI 라우터 모음 — 도메인별 분할 후 단일 `router` 로 노출."""

from fastapi import APIRouter

from api.chat import router as chat_router
from api.presence import router as presence_router
from api.settings import router as settings_router
from api.skills import router as skills_router
from api.update import router as update_router

# main.py 가 app.include_router(router) 한 번으로 전체를 끌어가도록 합친다.
router = APIRouter()
router.include_router(chat_router)
router.include_router(presence_router)
router.include_router(settings_router)
router.include_router(skills_router)
router.include_router(update_router)

__all__ = ["router"]
