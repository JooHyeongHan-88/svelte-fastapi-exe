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

    # backend/core/config.py → backend/ → project_root
    return Path(__file__).resolve().parent.parent.parent


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

HOST: str = os.environ.get("APP_HOST", "127.0.0.1")
PORT: int = int(os.environ.get("APP_PORT", "8765"))
ALLOWED_ORIGIN: str = f"http://{HOST}:{PORT}"


# ---------------------------------------------------------------------------
# browser / watchdog
# ---------------------------------------------------------------------------

# 첫 client 연결까지 기다리는 상한.
# 이 시간 동안 한 번도 연결이 없으면 비었다고 판단하지 않고 계속 대기.
STARTUP_GRACE: int = int(os.environ.get("APP_STARTUP_GRACE", "60"))
# 마지막 클라이언트 사라진 후 종료까지 대기.
SHUTDOWN_GRACE: int = int(os.environ.get("APP_SHUTDOWN_GRACE", "2"))

# presence SSE 가 끊겼다가 같은 client_id 로 재연결될 수 있는 시간 (F5/네트워크 블립 흡수).
# 이 시간 안에 다시 붙으면 실제 제거를 취소한다.
PRESENCE_RECONNECT_GRACE: int = int(os.environ.get("APP_PRESENCE_RECONNECT_GRACE", "2"))

# 서버가 SSE 채널에 `: ping` 코멘트 라인을 흘려보내는 주기.
# 중간 프록시의 idle timeout 으로 끊기지 않도록 유지.
PRESENCE_KEEPALIVE_INTERVAL: int = int(
    os.environ.get("APP_PRESENCE_KEEPALIVE_INTERVAL", "30")
)

# SSE 첫 응답에 실어보내는 `retry:` 디렉티브 — EventSource 재연결 간격(ms).
PRESENCE_RETRY_HINT_MS: int = int(os.environ.get("APP_PRESENCE_RETRY_HINT_MS", "1000"))


# ---------------------------------------------------------------------------
# update / nexus
# ---------------------------------------------------------------------------

NEXUS_BASE_URL: str = os.environ.get(
    "APP_NEXUS_BASE_URL",
    "https://nexus.internal/repository/app",
).rstrip("/")
LATEST_JSON_URL: str = f"{NEXUS_BASE_URL}/latest.json"
UPDATE_CHECK_TIMEOUT: int = int(os.environ.get("APP_UPDATE_CHECK_TIMEOUT", "5"))
UPDATE_DOWNLOAD_TIMEOUT: int = int(os.environ.get("APP_UPDATE_DOWNLOAD_TIMEOUT", "60"))
UPDATE_CHECK_CACHE_TTL: int = int(os.environ.get("APP_UPDATE_CHECK_CACHE_TTL", "300"))


# ---------------------------------------------------------------------------
# 앱 이름 — settings.json 경로, EXE 파일명에 공통 사용
# ---------------------------------------------------------------------------

APP_NAME: str = os.environ.get("APP_NAME", "MyAgent")


# ---------------------------------------------------------------------------
# 워크스페이스 — Python 도구가 생성한 파일(이미지·CSV 등)을 저장하는 디렉터리.
# /workspace/<filename> 으로 브라우저에서 직접 접근 가능.
# ---------------------------------------------------------------------------

if getattr(sys, "frozen", False):
    _appdata_str = os.environ.get("APPDATA", "")
    _appdata = (
        Path(_appdata_str) if _appdata_str else Path.home() / "AppData" / "Roaming"
    )
    WORKSPACE_DIR: Path = _appdata / APP_NAME / "workspace"
else:
    WORKSPACE_DIR: Path = _project_root() / "workspace"
