import mimetypes
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import agent.tools  # noqa: F401 — @register_tool 데코레이터 자기등록 트리거
from agent.registries.agents import registry as agent_registry
from agent.registries.prompts import registry as prompt_registry
from agent.registries.skills import registry as skill_registry
from api import router as api_router
from api.deps import state_store
from core import browser
from core.browser import open_browser, watchdog
from core.config import (
    ASSETS_DIR,
    RESULT_DIR,
    WEB_DIR,
    WORKSPACE_DIR,
)
from core.extensions_loader import load_extensions
from core.server_socket import ServerAlreadyRunning, create_server_socket

# Windows Python 환경에 따라 mimetypes 레지스트리가 누락된 확장자를 보정한다.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


@asynccontextmanager
async def lifespan(app: FastAPI):
    browser.init_shutdown_event()
    yield


app = FastAPI(lifespan=lifespan)


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

# workspace 디렉터리 — Python 도구가 생성한 파일을 /workspace/<path> 로 서빙한다.
# dev / frozen 모두 항상 활성화.
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/workspace", StaticFiles(directory=WORKSPACE_DIR), name="workspace")

# result 디렉터리 — 에이전트·SKILL 실행으로 생성된 산출물(이미지·차트·markdown 등)을
# /result/<session>/<timestamp>/<filename> 으로 서빙한다. 세션 복귀 후 칩 클릭 시
# 동일 파일을 다시 fetch 해 시각화를 복원한다.
RESULT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/result", StaticFiles(directory=RESULT_DIR), name="result")

# 확장(extensions/<tool>/) 의 API 라우터(/api/ext/<name>)와 정적 SPA(/ext/<name>)를 마운트.
# 반드시 아래 SPA catch-all(/{path:path}) 보다 먼저 등록해야 폴백에 잡히지 않는다.
# extensions/ 가 없거나 비면 no-op — 메인 앱 동작에 영향 없음.
load_extensions(app)

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
            media_type = (
                mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
            )
            return FileResponse(candidate, media_type=media_type)

        return FileResponse(WEB_DIR / "index.html", media_type="text/html")


if __name__ == "__main__":
    # 포트를 직접 바인딩한 소켓을 uvicorn 에 넘긴다.
    # 실제 포트는 create_server_socket() 안에서 set_runtime_port() 로 전역에 반영되므로
    # open_browser / Origin 가드가 동일 포트를 참조한다.
    try:
        sock = create_server_socket()
    except ServerAlreadyRunning as exc:
        # 같은 앱이 이미 실행 중 — 새 서버를 띄우는 대신 기존 탭을 열고 종료한다.
        webbrowser.open(exc.url)
        sys.exit(0)
    config = uvicorn.Config(app, timeout_graceful_shutdown=5)
    server = uvicorn.Server(config)
    browser.server = server

    # FastAPI 가 SPA 를 서빙할 때(=build/web 존재)만 EXE 와 같은 생명주기를 가져간다.
    # Vite dev server 와 병행할 때(build/web 없음)는 Ctrl+C 로 끄므로 watchdog 불필요.
    if WEB_DIR.exists():
        threading.Thread(target=watchdog, daemon=True).start()
        threading.Thread(target=open_browser, daemon=True).start()

    server.run(sockets=[sock])
