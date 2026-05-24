import threading

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent.registries.agents import registry as agent_registry
from agent.registries.prompts import registry as prompt_registry
from agent.registries.skills import registry as skill_registry
from api import router as api_router
from api.deps import state_store
from core import browser
from core.browser import open_browser, watchdog
from core.config import ASSETS_DIR, HOST, PORT, WEB_DIR


app = FastAPI()

# PROMPTS / SKILLS 베이스 메타데이터는 1회 캐시. dev 모드 핫리로드는 각 registry 가
# 본문 읽을 때 mtime 으로 자동 감지하므로 부팅 시점 로드만 명시한다.
prompt_registry.load()
skill_registry.load()
agent_registry.load()
# AGENTS body 의 skills 배열이 실제 SKILLS 와 일치하는지 확인 — 부팅 시 1회 경고.
agent_registry.cross_check_skills({m.name for m in skill_registry.list_meta()})

# API 라우터는 catch-all 보다 먼저 등록해야 GET /api/* 가 SPA fallback 에 잡히지 않는다.
app.include_router(api_router)

# 장기 미사용 클라이언트 상태를 정리해 agent_states.json 파일 크기가 무한 증가하는 것을
# 막는다. EXE 기동 시 1회 실행이면 단일 사용자 앱에서는 충분하다.
_evicted = state_store.evict_stale()
if _evicted:
    import logging as _logging

    _logging.getLogger(__name__).info(
        "startup: evicted %d stale agent state(s)", _evicted
    )

# build/web 가 존재할 때만 정적 자산을 서빙한다.
# - frozen EXE: 항상 존재(sys._MEIPASS/web 임베드)
# - dev + npm run build 완료: build/web 존재 → localhost:8765 에서 직접 서빙 가능
# - dev + build/web 없음: 기동만 하고 서빙 생략 (Vite dev server 사용 시 이 경로)
if WEB_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/{path:path}")
    async def spa_router(path: str) -> FileResponse:
        candidate = (WEB_DIR / path).resolve()

        try:
            candidate.relative_to(WEB_DIR.resolve())
        except ValueError:
            raise HTTPException(status_code=404)

        if candidate.is_file():
            return FileResponse(candidate)

        return FileResponse(WEB_DIR / "index.html")


if __name__ == "__main__":
    config = uvicorn.Config(app, host=HOST, port=PORT)
    server = uvicorn.Server(config)
    browser.server = server

    # FastAPI 가 SPA 를 서빙할 때(=build/web 존재)만 EXE 와 같은 생명주기를 가져간다.
    # Vite dev server 와 병행할 때(build/web 없음)는 Ctrl+C 로 끄므로 watchdog 불필요.
    if WEB_DIR.exists():
        threading.Thread(target=watchdog, daemon=True).start()
        threading.Thread(target=open_browser, daemon=True).start()

    server.run()
