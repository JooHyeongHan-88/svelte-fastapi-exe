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
# LLM / Agent harness / Settings
# ---------------------------------------------------------------------------

# App name for settings file and EXE naming.
APP_NAME: str = os.environ.get("APP_NAME", "MyAgent")


# Settings file location: %APPDATA%\{APP_NAME}\settings.json
def _get_settings_path() -> Path:
    """Get platform-specific settings directory path."""
    if getattr(sys, "frozen", False):
        # Windows frozen EXE
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME / "settings.json"
    # dev mode
    return _project_root() / "backend" / "settings" / "settings.json"


SETTINGS_FILE_PATH: Path = _get_settings_path()

# Timeout for testing provider connectivity.
SETTINGS_TEST_TIMEOUT: int = int(os.environ.get("APP_SETTINGS_TEST_TIMEOUT", "10"))

# Legacy env var fallback for initial settings seed (deprecated, use settings file)
LLM_PROVIDER: str = os.environ.get("APP_LLM_PROVIDER", "mock")
LLM_BASE_URL: str | None = os.environ.get("APP_LLM_BASE_URL")
LLM_MODEL: str | None = os.environ.get("APP_LLM_MODEL")
LLM_API_KEY: str | None = os.environ.get("APP_LLM_API_KEY")

SYSTEM_PROMPT: str = os.environ.get(
    "APP_SYSTEM_PROMPT",
    "You are a helpful AI agent. 한국어 사용자에게는 한국어로 친절히 답한다. "
    "필요하면 등록된 도구를 사용해 정확한 정보를 제공한다.",
)

# LLM 생성 파라미터 — settings.json 대신 환경 변수로 제어한다.
# UI에 노출하지 않고 배포 시 .env 또는 시스템 환경 변수로 조정.
LLM_TEMPERATURE: float = float(os.environ.get("APP_LLM_TEMPERATURE", "0.7"))
_max_tok_raw: str | None = os.environ.get("APP_LLM_MAX_TOKENS")
LLM_MAX_TOKENS: int | None = int(_max_tok_raw) if _max_tok_raw else None

# Agent harness 한 턴에서 허용하는 provider→tool→provider 반복 횟수 상한.
MAX_AGENT_ITERATIONS: int = int(os.environ.get("APP_MAX_AGENT_ITERATIONS", "5"))

# store 가 client 한 명당 보관하는 메시지 수 상한 (system 제외).
MAX_HISTORY_MESSAGES: int = int(os.environ.get("APP_MAX_HISTORY_MESSAGES", "40"))
