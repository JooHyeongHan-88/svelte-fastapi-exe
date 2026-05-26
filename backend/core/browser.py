import asyncio
import threading
import time
import webbrowser

from core.config import (
    HOST,
    PORT,
    PRESENCE_RECONNECT_GRACE,
    SHUTDOWN_GRACE,
    STARTUP_GRACE,
)


_lock = threading.Lock()

# shutdown 이벤트 — presence SSE 루프가 즉시 깨어나도록 한다.
# asyncio.Event 는 특정 이벤트 루프에 바인딩되므로 서버 startup 시점에 초기화한다.
_shutdown_event: asyncio.Event | None = None
_loop: asyncio.AbstractEventLoop | None = None

# client_id → 살아있는 presence SSE 개수.
# 탭 복제 / "Open in new tab" 의 경우 sessionStorage 가 복사돼 두 탭이 같은 client_id 를
# 공유한다. 단순 set 이면 한 탭이 닫혔을 때 다른 탭도 함께 사라진 것처럼 보이므로
# 카운트로 추적한다.
_connections: dict[str, int] = {}

# grace 중인 client_id → Timer. 카운트가 0 까지 떨어진 경우에만 등록된다.
_pending_disconnects: dict[str, threading.Timer] = {}

_ever_registered = False

# uvicorn.Server 인스턴스. main.py 에서 세팅한다.
server = None


def connect_client(client_id: str) -> None:
    """presence SSE 가 새로 붙었을 때 호출. 직전에 잡힌 grace timer 가 있으면 취소한다."""
    global _ever_registered

    with _lock:
        _connections[client_id] = _connections.get(client_id, 0) + 1
        _ever_registered = True

        timer = _pending_disconnects.pop(client_id, None)

    # Timer.cancel() 은 자체 락을 잡으므로 우리 락 밖에서 호출 (lock ordering).
    if timer is not None:
        timer.cancel()


def disconnect_client(client_id: str) -> None:
    """presence SSE 가 끊겼을 때 호출.

    같은 client_id 로 살아있는 다른 연결이 있으면 카운트만 감소시키고, 마지막
    연결까지 떨어진 경우에만 grace timer 를 건다. F5 / 짧은 네트워크 블립에서
    EventSource 가 재연결되면 connect_client 가 이 timer 를 취소한다.
    """
    new_timer: threading.Timer | None = None

    with _lock:
        current = _connections.get(client_id, 0)

        if current > 1:
            # 같은 client_id 의 다른 탭이 살아있음 — grace 진입하지 않음.
            _connections[client_id] = current - 1
            return

        _connections.pop(client_id, None)

        # 정상 흐름에서는 이미 grace 가 도는 중일 수 없지만 방어적으로 체크.
        if client_id in _pending_disconnects:
            return

        new_timer = threading.Timer(
            PRESENCE_RECONNECT_GRACE,
            _finalize_disconnect,
            args=[client_id],
        )
        _pending_disconnects[client_id] = new_timer

    # Timer.start() 도 우리 락 밖에서.
    new_timer.start()


def _finalize_disconnect(client_id: str) -> None:
    """grace timer 가 만료된 뒤 _pending_disconnects 에서 항목 제거.

    grace 도중 재연결이 들어왔으면 connect_client 가 이미 이 timer 를 취소했어야
    하지만, 콜백이 락 대기 중이었다면 여기서 한 번 더 정리한다.
    """
    with _lock:
        _pending_disconnects.pop(client_id, None)


def _snapshot() -> tuple[set[str], bool]:
    """watchdog 가 보는 "살아있음" = 현재 연결 중인 client OR grace 중인 client."""
    with _lock:
        alive = set(_connections) | set(_pending_disconnects)
        return alive, _ever_registered


def init_shutdown_event() -> None:
    """서버 이벤트 루프 안에서 호출. shutdown 이벤트를 현재 루프에 바인딩한다."""
    global _shutdown_event, _loop
    _loop = asyncio.get_running_loop()
    _shutdown_event = asyncio.Event()


def get_shutdown_event() -> asyncio.Event | None:
    """presence SSE 루프가 shutdown 신호를 수신하기 위해 참조한다."""
    return _shutdown_event


def open_browser() -> None:
    time.sleep(1)
    webbrowser.open(f"http://{HOST}:{PORT}")


def request_shutdown() -> None:
    """uvicorn 종료를 요청한다.

    background thread 에서 호출되므로 asyncio.Event 설정은
    call_soon_threadsafe 로 이벤트 루프에 위임한다.
    """
    print("shutdown server")

    if server is not None:
        server.should_exit = True

    if _shutdown_event is not None and _loop is not None:
        _loop.call_soon_threadsafe(_shutdown_event.set)


def watchdog() -> None:
    started_at = time.time()
    empty_since: float | None = None

    while True:
        time.sleep(1)

        now = time.time()
        snapshot, ever_registered = _snapshot()

        # 첫 연결이 아직 안 들어왔으면 STARTUP_GRACE 만큼만 대기.
        # 그 안에는 비었다고 판정하지 않는다.
        if not ever_registered:
            if now - started_at < STARTUP_GRACE:
                continue

            print("no client connected during startup grace. shutdown")
            request_shutdown()
            return

        if not snapshot:
            if empty_since is None:
                empty_since = now
                print("no clients. start shutdown timer")
            elif now - empty_since > SHUTDOWN_GRACE:
                print("still no clients. shutdown")
                request_shutdown()
                return
        else:
            if empty_since is not None:
                print("client connected. cancel shutdown")
                empty_since = None
