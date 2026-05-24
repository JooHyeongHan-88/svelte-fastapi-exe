"""FastAPI 의존성 + 프로세스 전역 싱글톤 store 초기화.

도메인별 라우터(api/chat.py, api/settings.py, ...)는 이 모듈에서
require_local_origin / _store / _state_store / _settings_store 를 공유한다.
"""

import sys

from fastapi import Header, HTTPException

from agent.config import (
    AGENT_STATE_PATH,
    MAX_HISTORY_MESSAGES,
)
from agent.stores.agent_state import AgentStateStore
from agent.stores.conversation import ConversationStore
from core.config import ALLOWED_ORIGIN
from settings.config import SETTINGS_FILE_PATH
from settings.store import SettingsStore


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


# 프로세스 전역 대화 저장소. browser._connections 와 동일하게 인메모리 단일 인스턴스.
_store = ConversationStore(max_history=MAX_HISTORY_MESSAGES)

# Agent planner / slot 상태는 디스크 영속 — EXE 재기동 후에도 진행 상황 유지.
_state_store = AgentStateStore(file_path=AGENT_STATE_PATH)


# 프로세스 전역 설정 저장소. 파일 기반 영속화, 스레드 안전.
def _init_settings_store() -> SettingsStore:
    """Initialize settings store with legacy env var fallback."""
    store = SettingsStore(file_path=SETTINGS_FILE_PATH)
    # If settings file doesn't exist, try to seed from env vars
    if not SETTINGS_FILE_PATH.exists():
        from agent.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_PROVIDER

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
