import threading

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import browser
from browser import watchdog, open_browser
from config import ASSETS_DIR, WEB_DIR, HOST, PORT
from routers.api import router as api_router


app = FastAPI()

# API 라우터는 catch-all 보다 먼저 등록해야 GET /api/* 가 SPA fallback 에 잡히지 않는다.
app.include_router(api_router)

app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/{path:path}")
async def spa_router(path: str) -> FileResponse:
    # dist/ 루트에 실제 존재하는 파일(favicon.svg, icons.svg 등)은 그대로 서빙.
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

    threading.Thread(target=watchdog, daemon=True).start()
    threading.Thread(target=open_browser, daemon=True).start()

    server.run()
