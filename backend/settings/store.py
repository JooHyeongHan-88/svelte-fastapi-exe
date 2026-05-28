"""Persistent settings store with JSON file backend and thread-safe access."""

import json
import logging
import threading
from pathlib import Path

from settings.models import LLMSettings, ProviderConfig

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
            return self._cache.model_copy(deep=True)

    def update(self, patch: dict) -> LLMSettings:
        """Update settings from a partial patch dict.

        patch 는 다음 두 형태를 지원한다.
        - flat: {provider, model, api_key, base_url} — UI 저장 형태.
          model/api_key/base_url 은 현재 활성 provider 의 캐시 슬롯에 반영한다.
        - structured: {provider, providers: {id: {model, api_key, base_url}}} — 전체 교체.

        api_key 처리 규칙:
            ""  → 키 삭제 (clearKey)
            None → 변경 없음 (기존 유지)
            str  → 새 값으로 교체

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

            new_provider: str = patch.get("provider", self._cache.provider)
            # user_prompt 는 provider/providers 와 직교적 필드 — flat·structured 양쪽
            # 모두에서 동일한 방식으로 처리한다. 키 미포함 시 기존 값 유지.
            new_user_prompt: str = patch.get("user_prompt", self._cache.user_prompt)

            # providers 전체를 patch 로 교체하는 구조화 형태.
            if "providers" in patch and isinstance(patch["providers"], dict):
                new_providers: dict[str, ProviderConfig] = {}
                for pid, cfg_raw in patch["providers"].items():
                    if isinstance(cfg_raw, dict):
                        new_providers[pid] = _apply_api_key_rule(
                            ProviderConfig(
                                **{k: cfg_raw.get(k, "") for k in ("model", "base_url")}
                            ),
                            raw_key=cfg_raw.get("api_key"),
                            existing_key=self._cache.providers.get(
                                pid, ProviderConfig()
                            ).api_key,
                        )
                self._cache = LLMSettings(
                    provider=new_provider,
                    providers={**self._cache.providers, **new_providers},
                    user_prompt=new_user_prompt,
                )
            else:
                # flat 형태 — 활성 provider 슬롯에만 반영.
                existing = self._cache.providers.get(new_provider, ProviderConfig())
                updated_cfg = ProviderConfig(
                    model=patch.get("model", existing.model),
                    api_key=_apply_api_key_rule(
                        existing,
                        raw_key=patch.get("api_key", None),
                        existing_key=existing.api_key,
                    ).api_key,
                    base_url=patch.get("base_url", existing.base_url),
                )
                new_providers = {**self._cache.providers, new_provider: updated_cfg}
                self._cache = LLMSettings(
                    provider=new_provider,
                    providers=new_providers,
                    user_prompt=new_user_prompt,
                )

            self._save()
            return self._cache.model_copy(deep=True)

    def reload(self) -> LLMSettings:
        """Force reload from disk, discarding cache.

        Returns:
            Reloaded settings.
        """
        with self._lock:
            self._cache = None
            self._load()
            return self._cache.model_copy(deep=True)

    def _load(self) -> None:
        """Load settings from file or use defaults if file missing.

        구 포맷(top-level model/api_key/base_url) 감지 시 자동 마이그레이션한다.
        Must be called inside lock.
        """
        if not self._file_path.exists():
            self._cache = self._defaults
            logger.debug("settings file not found, using defaults")
            return

        try:
            with open(self._file_path, encoding="utf-8") as f:
                data = json.load(f)

            # 구 포맷 마이그레이션: providers 키 없이 top-level model/api_key/base_url 이 있는 경우.
            if "providers" not in data and any(
                k in data for k in ("model", "api_key", "base_url")
            ):
                provider_id = data.get("provider", "mock")
                legacy_cfg = ProviderConfig(
                    model=data.pop("model", ""),
                    api_key=data.pop("api_key", ""),
                    base_url=data.pop("base_url", ""),
                )
                data["providers"] = {provider_id: legacy_cfg.model_dump()}
                logger.info(
                    "migrated legacy settings format for provider '%s'", provider_id
                )

            self._cache = LLMSettings(**data)
            logger.debug("loaded settings from %s", self._file_path)

            # 마이그레이션된 경우 즉시 신 포맷으로 저장.
            if "providers" not in json.loads(
                self._file_path.read_text(encoding="utf-8")
            ):
                self._save()

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("failed to load settings: %s, using defaults", e)
            self._cache = self._defaults

    def _save(self) -> None:
        """Save cached settings to file.

        Creates parent directory if needed. Must be called inside lock.
        """
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._file_path, "w", encoding="utf-8") as f:
                json.dump(self._cache.model_dump(), f, indent=2)
            logger.debug("saved settings to %s", self._file_path)
        except OSError as e:
            logger.error("failed to save settings: %s", e)
            raise


def _apply_api_key_rule(
    existing: ProviderConfig,
    raw_key: str | None,
    existing_key: str,
) -> ProviderConfig:
    """api_key 처리 규칙을 적용한 새 ProviderConfig 를 반환한다.

    ""  → 키 삭제 / None → 기존 유지 / str → 새 값.
    """
    if raw_key == "":
        api_key = ""
    elif raw_key is None:
        api_key = existing_key
    else:
        api_key = raw_key
    return existing.model_copy(update={"api_key": api_key})
