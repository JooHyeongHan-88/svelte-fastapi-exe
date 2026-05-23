import os
import sys
from pathlib import Path


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


def _load_dotenv() -> None:
    """프로젝트 루트의 .env 를 dev 모드에서만 로드한다.

    EXE 로 패키징된 환경에서는 .env 가 함께 배포되지 않으므로 skip.
    이미 셸에서 export 된 값은 덮어쓰지 않는다 (os.environ.setdefault).
    """
    if getattr(sys, "frozen", False):
        return

    env_path = _project_root() / ".env"
    if not env_path.is_file():
        return

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


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
