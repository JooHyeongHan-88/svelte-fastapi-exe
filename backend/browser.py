import threading
import time
import webbrowser

from config import HOST, PORT, STARTUP_GRACE, HEARTBEAT_TIMEOUT, SHUTDOWN_GRACE


_lock = threading.Lock()
clients: dict[str, float] = {}
_ever_registered = False

# uvicorn.Server 인스턴스. main.py 에서 세팅한다.
server = None


def register_client(client_id: str) -> None:
    global _ever_registered

    with _lock:
        clients[client_id] = time.time()
        _ever_registered = True


def touch_client(client_id: str) -> None:
    with _lock:
        clients[client_id] = time.time()


def unregister_client(client_id: str) -> None:
    with _lock:
        clients.pop(client_id, None)


def _snapshot() -> tuple[list[tuple[str, float]], bool]:
    with _lock:
        return list(clients.items()), _ever_registered


def _remove_stale(now: float) -> list[str]:
    with _lock:
        stale = [cid for cid, ts in clients.items() if now - ts > HEARTBEAT_TIMEOUT]

        for cid in stale:
            clients.pop(cid, None)

        return stale


def open_browser() -> None:
    time.sleep(1)
    webbrowser.open(f"http://{HOST}:{PORT}")


def request_shutdown() -> None:
    print("shutdown server")

    if server is not None:
        server.should_exit = True


def watchdog() -> None:
    started_at = time.time()
    empty_since: float | None = None

    while True:
        time.sleep(1)

        now = time.time()

        stale = _remove_stale(now)
        for cid in stale:
            print(f"stale remove: {cid}")

        snapshot, ever_registered = _snapshot()

        # 첫 register 가 아직 안 들어왔으면 STARTUP_GRACE 만큼만 대기.
        # 그 안에는 비었다고 판정하지 않는다.
        if not ever_registered:
            if now - started_at < STARTUP_GRACE:
                continue

            # STARTUP_GRACE 동안 한 번도 client 가 안 붙었으면 종료.
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
