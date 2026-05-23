import os
import signal
import time
import webbrowser

from config import HOST, PORT, STARTUP_GRACE, HEARTBEAT_TIMEOUT, SHUTDOWN_GRACE


clients: dict[str, float] = {}


def open_browser():
    time.sleep(1)
    webbrowser.open(f"http://{HOST}:{PORT}")


def _stop_server():
    print("shutdown server")
    os.kill(os.getpid(), signal.SIGTERM)


def watchdog():
    started_at = time.time()
    empty_since: float | None = None

    while True:
        time.sleep(1)

        now = time.time()

        # startup grace
        if now - started_at < STARTUP_GRACE:
            continue

        # stale client 제거
        stale = [cid for cid, ts in clients.items() if now - ts > HEARTBEAT_TIMEOUT]

        for cid in stale:
            print(f"stale remove: {cid}")
            clients.pop(cid, None)

        # client 없을 때 grace period 시작
        if not clients:
            if empty_since is None:
                empty_since = time.time()

                print("no clients. start shutdown timer")

            elif (time.time() - empty_since > SHUTDOWN_GRACE):
                print("still no clients. shutdown")

                _stop_server()

        else:
            # client 다시 생기면 timer reset
            if empty_since is not None:
                print("client connected. cancel shutdown")

            empty_since = None
