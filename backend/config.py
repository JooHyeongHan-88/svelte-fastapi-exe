import sys
from pathlib import Path


def resource_path(relative_path: str) -> Path:
    if getattr(sys, "frozen", False):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = (Path(__file__).resolve().parent.parent)

    return base_path / relative_path


# directory
DIST_DIR = resource_path("dist")
ASSETS_DIR = (DIST_DIR / "assets")

# host, port
HOST = "127.0.0.1"
PORT = 8765

# browser
STARTUP_GRACE = 10
HEARTBEAT_TIMEOUT = 5
SHUTDOWN_GRACE = 2