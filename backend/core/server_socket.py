"""frozen EXE 용 고정 포트 소켓 생성 + 단일 인스턴스 감지.

frozen EXE 가 매 실행 동일한 TCP 포트를 바인딩하도록 해 localStorage origin 이
실행마다 일정하게 유지되고, 대화 기록이 재기동 후에도 보존된다.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import socket
import sys
import time
import urllib.request
from typing import Optional

from core.config import APP_NAME, DEV_PORT, HOST, set_runtime_port

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

# 해시 유도 포트 구간 — Windows ephemeral 49152+ 아래, well-known 아님.
# 같은 코드베이스의 형제 앱(APP_NAME 만 다름)이 같은 PC 에 공존할 때
# origin 교차 오염을 방지하기 위해 앱별로 구간 내 고유 포트를 배정한다.
FROZEN_PORT_RANGE_START: int = 47100
FROZEN_PORT_RANGE_SIZE: int = 1900

PORT_FALLBACK_ATTEMPTS: int = 5  # base, base+1 .. base+4
DYNAMIC_PORT: int = 0  # APP_PORT=0 → 동적 escape hatch
SAME_APP_PROBE_TIMEOUT: float = 1.0  # /api/app-info 프로브 타임아웃 (초)
BIND_RETRY_INTERVAL: float = 0.5  # 과도기(이중 클릭 등) bind 재시도 대기 (초)

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 공개 예외
# ---------------------------------------------------------------------------


class ServerAlreadyRunning(RuntimeError):
    """같은 APP_NAME 의 인스턴스가 이미 실행 중일 때 create_server_socket 이 올린다.

    Args:
        url (str): 실행 중인 인스턴스의 origin URL (e.g. ``http://127.0.0.1:47381``).
    """

    def __init__(self, url: str) -> None:
        super().__init__(f"Server already running at {url}")
        self.url: str = url


# ---------------------------------------------------------------------------
# 포트 계산
# ---------------------------------------------------------------------------


def default_frozen_port(app_name: str) -> int:
    """APP_NAME 의 SHA-256 해시에서 포트를 결정론적으로 유도한다.

    Args:
        app_name (str): APP_NAME 환경 변수 값.

    Returns:
        int: [FROZEN_PORT_RANGE_START, FROZEN_PORT_RANGE_START + FROZEN_PORT_RANGE_SIZE) 범위 포트.
    """
    digest = int(hashlib.sha256(app_name.encode()).hexdigest(), 16)
    return FROZEN_PORT_RANGE_START + (digest % FROZEN_PORT_RANGE_SIZE)


def _resolve_frozen_port_base() -> int:
    """APP_PORT 환경 변수 또는 APP_NAME 해시로 frozen 포트 기준값을 결정한다.

    Returns:
        int: 0(동적 escape), 또는 1–65535 범위의 포트.
    """
    import os

    raw = os.environ.get("APP_PORT", "").strip()
    if not raw:
        return default_frozen_port(APP_NAME)

    try:
        port = int(raw)
    except ValueError:
        _logger.warning(
            "APP_PORT=%r is not an integer; falling back to hash-derived default port",
            raw,
        )
        return default_frozen_port(APP_NAME)

    if port != DYNAMIC_PORT and not (1 <= port <= 65535):
        _logger.warning(
            "APP_PORT=%d is out of range (1-65535); falling back to hash-derived default port",
            port,
        )
        return default_frozen_port(APP_NAME)

    return port


# ---------------------------------------------------------------------------
# 소켓 헬퍼
# ---------------------------------------------------------------------------


def _bind_listen_socket(port: int) -> socket.socket:
    """지정 포트에 바인딩된 TCP 소켓을 반환한다.

    win32 에서는 SO_REUSEADDR 를 설정하지 않는다. Windows 의 SO_REUSEADDR 는
    LISTEN 소켓 이중 바인딩을 허용하는 다른 의미론이라 단일 인스턴스 감지를
    무력화한다. SO_EXCLUSIVEADDRUSE 는 TIME_WAIT 잔존(60-120s) 동안 재바인딩이
    막혀 업데이트 재기동에서 포트 충돌이 생긴다. 기본 바인딩(옵션 없음)은 살아있는
    listener 와 충돌하면서 TIME_WAIT 위 재바인딩은 허용 — 정답.
    비-win32 는 기존대로 SO_REUSEADDR 를 설정한다.

    Args:
        port (int): 바인딩할 TCP 포트.

    Returns:
        socket.socket: 바인딩된 소켓.

    Raises:
        OSError: 바인딩 실패 시.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform != "win32":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, port))
    return sock


def _probe_same_app(port: int) -> tuple[Optional[str], bool]:
    """지정 포트의 /api/app-info 를 프로브해 같은 앱인지 확인한다.

    Origin / sec-fetch-site 헤더 없이 stdlib urllib 로 요청하므로
    require_local_origin 의 header-없음 통과 경로를 탄다.

    Args:
        port (int): 프로브할 TCP 포트.

    Returns:
        tuple[str | None, bool]: (같은 앱이면 origin URL 또는 None, ECONNREFUSED 여부).
            - (url, False): 같은 APP_NAME 응답 → ServerAlreadyRunning 대상
            - (None, False): 다른 앱 또는 파싱 실패 → 다음 후보로 진행
            - (None, True): 연결 거부(ECONNREFUSED) → bind 재시도 대상(과도기)
    """
    url = f"http://{HOST}:{port}"
    try:
        req = urllib.request.Request(f"{url}/api/app-info")
        with urllib.request.urlopen(req, timeout=SAME_APP_PROBE_TIMEOUT) as resp:
            body = json.loads(resp.read())
        if body.get("name") == APP_NAME:
            return url, False
        return None, False
    except ConnectionRefusedError:
        return None, True
    except OSError:
        return None, False
    except (ValueError, http.client.HTTPException):
        return None, False


# ---------------------------------------------------------------------------
# 메인 진입점
# ---------------------------------------------------------------------------


def create_server_socket() -> socket.socket:
    """uvicorn 에 넘길 바인딩된 리스닝 소켓을 생성한다.

    dev 에서는 DEV_PORT 에 직접 바인딩하고 즉시 반환한다.

    frozen EXE 에서는 APP_PORT 또는 APP_NAME 해시 기반 고정 포트를 사용해
    실행마다 동일한 origin(localhost:port)을 확보한다 → localStorage 대화 기록 보존.

    포트 후보 체인 (frozen):
        1. base, base+1 .. base+4 순으로 bind 시도
        2. 실패 시 /api/app-info 프로브
           - 같은 앱 → ServerAlreadyRunning raise (호출자가 기존 탭을 열고 종료)
           - 다른 앱 → 다음 후보로 진행
           - ECONNREFUSED(과도기) → 짧은 대기 후 1회 재시도 후 다음 후보
        3. 전수 실패 → 동적 포트(0) 최후수단 + warning 로그

    Returns:
        socket.socket: 바인딩된 소켓. ``uvicorn.Server(sockets=[...])`` 에 전달한다.

    Raises:
        ServerAlreadyRunning: 같은 APP_NAME 인스턴스가 이미 포트를 점유 중일 때.
    """
    if not getattr(sys, "frozen", False):
        sock = _bind_listen_socket(DEV_PORT)
        set_runtime_port(sock.getsockname()[1])
        return sock

    base = _resolve_frozen_port_base()

    if base == DYNAMIC_PORT:
        sock = _bind_listen_socket(DYNAMIC_PORT)
        actual = sock.getsockname()[1]
        set_runtime_port(actual)
        _logger.info("bound dynamic port %d (APP_PORT=0)", actual)
        return sock

    candidates = [base + i for i in range(PORT_FALLBACK_ATTEMPTS)]

    for candidate in candidates:
        try:
            sock = _bind_listen_socket(candidate)
            set_runtime_port(candidate)
            _logger.info("bound port %d", candidate)
            return sock
        except OSError:
            pass

        url, refused = _probe_same_app(candidate)
        if url is not None:
            raise ServerAlreadyRunning(url)
        if refused:
            time.sleep(BIND_RETRY_INTERVAL)
            try:
                sock = _bind_listen_socket(candidate)
                set_runtime_port(candidate)
                _logger.info("bound port %d (after retry)", candidate)
                return sock
            except OSError:
                pass

    _logger.warning(
        "all %d port candidates (%d-%d) occupied; falling back to dynamic port",
        PORT_FALLBACK_ATTEMPTS,
        candidates[0],
        candidates[-1],
    )
    sock = _bind_listen_socket(DYNAMIC_PORT)
    actual = sock.getsockname()[1]
    set_runtime_port(actual)
    return sock
