import threading

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from browser import watchdog, open_browser
from config import ASSETS_DIR, DIST_DIR, HOST, PORT
from routers.api import router as api_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(DIST_DIR / "index.html")


@app.get("/{path:path}")
async def spa_router(path: str) -> FileResponse:
    return FileResponse(DIST_DIR / "index.html")


app.include_router(api_router)


if __name__ == "__main__":
    threading.Thread(target=watchdog, daemon=True).start()
    threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(app, host=HOST, port=PORT)