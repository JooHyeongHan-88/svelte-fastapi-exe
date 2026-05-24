"""Persistent settings store with JSON file backend and thread-safe access."""

import json
import logging
import threading
from pathlib import Path

from settings.models import LLMSettings

logger = logging.getLogger(__name__)


class SettingsStore:
    """Thread-safe persistent settings storage.

    Reads/writes LLMSettings to a JSON file on disk. Uses threading.Lock
    to serialize concurrent updates.
    """

    def __init__(self, file_path: Path, defaults: LLMSettings | None = None) -> None:
        """Initialize the store.

        Args:
            file_path: Path to JSON settings file.
            defaults: Default settings if file does not exist.
        """
        self._file_path = Path(file_path)
        self._lock = threading.Lock()
        self._cache: LLMSettings | None = None
        self._defaults = defaults or LLMSettings()

    def get(self) -> LLMSettings:
        """Get current settings (cached copy).

        Returns:
            A copy of cached settings. Safe for the caller to modify.
        """
        with self._lock:
            if self._cache is None:
                self._load()
            return self._cache.model_copy()

    def update(self, patch: dict) -> LLMSettings:
        """Update settings from a partial patch dict.

        Fields not in patch are left unchanged. Empty string for api_key
        is treated as "clear the key". None api_key is ignored.

        Args:
            patch: Dict of fields to update (from JSON parse, likely from UI).

        Returns:
            Updated settings after save.
        """
        with self._lock:
            # self.get() 을 호출하면 같은 Lock 을 재취득 시도 → 데드락.
            # 락 안에서 직접 캐시를 참조한다.
            if self._cache is None:
                self._load()
            update_dict = self._cache.model_dump()

            # Exclude keys that weren't explicitly set (e.g., not sent by UI).
            for key, value in patch.items():
                if key in update_dict:
                    # Special handling: empty api_key clears it, None is ignored.
                    if key == "api_key" and value == "":
                        update_dict[key] = ""
                    elif key == "api_key" and value is None:
                        continue
                    else:
                        update_dict[key] = value

            self._cache = LLMSettings(**update_dict)
            self._save()
            return self._cache.model_copy()

    def reload(self) -> LLMSettings:
        """Force reload from disk, discarding cache.

        Returns:
            Reloaded settings.
        """
        with self._lock:
            self._cache = None
            self._load()
            return self._cache.model_copy()

    def _load(self) -> None:
        """Load settings from file or use defaults if file missing.

        Must be called inside lock.
        """
        if self._file_path.exists():
            try:
                with open(self._file_path, encoding="utf-8") as f:
                    data = json.load(f)
                self._cache = LLMSettings(**data)
                logger.debug(f"loaded settings from {self._file_path}")
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"failed to load settings: {e}, using defaults")
                self._cache = self._defaults
        else:
            self._cache = self._defaults
            logger.debug("settings file not found, using defaults")

    def _save(self) -> None:
        """Save cached settings to file.

        Creates parent directory if needed. Must be called inside lock.
        """
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._file_path, "w", encoding="utf-8") as f:
                json.dump(self._cache.model_dump(), f, indent=2)
            logger.debug(f"saved settings to {self._file_path}")
        except OSError as e:
            logger.error(f"failed to save settings: {e}")
            raise
