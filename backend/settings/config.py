"""LLM 설정 파일(settings.json) 위치 + 설정 도메인 전용 타임아웃."""

import os
import sys
from pathlib import Path

from core.config import APP_NAME, _project_root


# ---------------------------------------------------------------------------
# Settings file location: %APPDATA%\{APP_NAME}\settings.json
# ---------------------------------------------------------------------------


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
