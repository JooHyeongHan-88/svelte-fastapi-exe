from backend.config import ASSETS_DIR

if not ASSETS_DIR.exists():
    raise RuntimeError(f"Frontend build not found: {ASSETS_DIR}")