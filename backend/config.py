import os
import sys
from pathlib import Path

from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# 경로 해석
#
# 빌드 결과물 위치:
#   - dev:     <project_root>/build/web         (Vite outDir)
#              <project_root>/build/updater     (PyInstaller Updater 출력)
#   - frozen:  <MEIPASS>/web                    (App.spec datas 로 임베드)
#              <MEIPASS>/updater                (동, Updater.exe 만 포함)
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]

    return Path(__file__).resolve().parent.parent


if not getattr(sys, "frozen", False):
    load_dotenv(dotenv_path=_project_root() / ".env", override=False)


# ---------------------------------------------------------------------------
# 디렉터리
# ---------------------------------------------------------------------------

if getattr(sys, "frozen", False):
    WEB_DIR = _project_root() / "web"
else:
    WEB_DIR = _project_root() / "build" / "web"

ASSETS_DIR = WEB_DIR / "assets"


# ---------------------------------------------------------------------------
# 네트워크 (frontend 와 공유 — .env 로 override 가능)
# ---------------------------------------------------------------------------

HOST = os.environ.get("APP_HOST", "127.0.0.1")
PORT = int(os.environ.get("APP_PORT", "8765"))
ALLOWED_ORIGIN = f"http://{HOST}:{PORT}"


# ---------------------------------------------------------------------------
# browser / watchdog
# ---------------------------------------------------------------------------

# STARTUP_GRACE: 첫 client register 까지 기다리는 상한.
# 이 시간 동안 register 가 한 번도 없으면 비었다고 판단하지 않고 계속 대기.
STARTUP_GRACE = 60
HEARTBEAT_TIMEOUT = 5
SHUTDOWN_GRACE = 2


# ---------------------------------------------------------------------------
# update / nexus
# ---------------------------------------------------------------------------

NEXUS_BASE_URL = os.environ.get(
    "APP_NEXUS_BASE_URL",
    "https://nexus.internal/repository/app",
).rstrip("/")
LATEST_JSON_URL = f"{NEXUS_BASE_URL}/latest.json"
UPDATE_CHECK_TIMEOUT = 5
UPDATE_DOWNLOAD_TIMEOUT = 60
UPDATE_CHECK_CACHE_TTL = 300
