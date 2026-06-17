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
# 네트워크
#
# HOST 는 루프백(127.0.0.1)으로 고정한다 — env 로 노출하지 않는다. 이 앱은 exec_code /
# 라이브러리 호출이 가능한 로컬 에이전트이므로, 루프백 바인딩이 "외부 네트워크에서 접근
# 불가"를 보장하는 보안 경계다. 0.0.0.0 등으로 바꾸면 LAN 에 노출되는 footgun 이 되므로
# Origin 가드와 함께 로컬 전용을 강제한다.
#
# frozen EXE 는 APP_PORT 또는 APP_NAME 해시(47100–48999)로 결정된 고정 포트를 쓴다.
# 고정 포트로 localStorage origin 이 실행마다 일정해져 대화 기록이 보존된다.
# 같은 포트가 점유 중이면 +1..+4 후보 체인으로 폴백한다 (core.server_socket).
# dev 는 Vite dev server 가 /api 를 이 포트로 프록시하므로 DEV_PORT 고정.
# ---------------------------------------------------------------------------

HOST: str = "127.0.0.1"

# dev 백엔드 포트. vite.config.js 가 같은 APP_DEV_PORT 를 읽어 프록시 타겟을 맞춘다.
# frozen 에서는 무시된다(고정 포트는 core.server_socket 이 결정). 기본 8765, 충돌 시에만 .env 에서 변경.
DEV_PORT: int = int(os.environ.get("APP_DEV_PORT", "8765"))

# 실제 바인딩된 포트로 런타임에 갱신된다. import 시점 기본값은 dev 고정 포트이며,
# main.py 가 create_server_socket() 안의 set_runtime_port() 로 덮어쓴다.
# frontend 는 절대 URL 을 박지 않고 상대 경로(/api/...)만 쓰므로, 자신을 띄워준
# origin(=실제 포트)으로 자동 따라온다 → 정적 빌드 재생성이 필요 없다.
PORT: int = DEV_PORT
ALLOWED_ORIGIN: str = f"http://{HOST}:{PORT}"


def set_runtime_port(port: int) -> None:
    """실제 바인딩된 포트를 프로세스 전역에 전파한다.

    브라우저 진입 URL(open_browser)과 Origin 가드(require_local_origin)가 동일한
    포트를 참조하도록 PORT 와 ALLOWED_ORIGIN 을 함께 갱신한다.

    Args:
        port (int): uvicorn 이 실제로 바인딩한 TCP 포트.
    """
    global PORT, ALLOWED_ORIGIN
    PORT = port
    ALLOWED_ORIGIN = f"http://{HOST}:{PORT}"


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
# update / 원격 저장소 (repository) — 현재는 Nexus, 저장소 중립적 변수명 사용
# ---------------------------------------------------------------------------

REPO_BASE_URL: str = os.environ.get(
    "APP_REPO_BASE_URL",
    "https://nexus.internal/repository/app",
).rstrip("/")
# GitHub Releases 전환 시 latest.json 은 release 에셋 경로(.../releases/latest/download/
# latest.json)라 REPO_BASE_URL 직속이 아니다. 그래서 별도 env 로 오버라이드 가능하게 둔다.
# 미설정 시 기존 동작(REPO_BASE_URL/latest.json = Nexus) 유지 — 하위호환.
LATEST_JSON_URL: str = os.environ.get(
    "APP_LATEST_JSON_URL", f"{REPO_BASE_URL}/latest.json"
)
# private GHE repo 의 latest.json·EXE 다운로드를 인증하는 읽기 전용 토큰.
# 업로드용 쓰기 자격증명(APP_REPO_USER/PASSWORD)과 분리해 EXE 에는 이 토큰만 번들한다.
# 빈 값이면 Authorization 헤더 없이 익명 GET (Nexus·공개 저장소 하위호환).
REPO_READ_TOKEN: str = os.environ.get("APP_REPO_READ_TOKEN", "")
UPDATE_CHECK_TIMEOUT: int = int(os.environ.get("APP_UPDATE_CHECK_TIMEOUT", "5"))
UPDATE_DOWNLOAD_TIMEOUT: int = int(os.environ.get("APP_UPDATE_DOWNLOAD_TIMEOUT", "60"))
UPDATE_CHECK_CACHE_TTL: int = int(os.environ.get("APP_UPDATE_CHECK_CACHE_TTL", "300"))

# 빌드 채널 — frozen 은 App.spec 이 빌드 시 .env 에 주입(release.ps1 -Channel).
#   qa   : 자동 업데이트 차단 + Mock provider 노출(테스트용)
#   prod : 정식 배포 — 자동 업데이트 활성 + Mock provider 제외
# dev(비-frozen)는 기본 qa 로 떨어져 Mock 시나리오(A~H)가 유지된다. frozen 기본값을
# prod 로 두는 건 채널 미주입 EXE 가 실수로 Mock 을 노출하지 않게 하는 안전판이다.
_DEFAULT_BUILD_CHANNEL = "prod" if getattr(sys, "frozen", False) else "qa"
BUILD_CHANNEL: str = os.environ.get("APP_BUILD_CHANNEL", _DEFAULT_BUILD_CHANNEL).lower()


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
    # 에이전트 산출물 — 세션별·시각별 하위 폴더로 구분.
    RESULT_DIR: Path = _appdata / APP_NAME / "result"
else:
    WORKSPACE_DIR: Path = _project_root() / "workspace"
    RESULT_DIR: Path = _project_root() / "result"
