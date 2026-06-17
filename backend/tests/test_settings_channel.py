"""빌드 채널별 Mock provider 노출/강등 — prod 격리 검증.

- list_providers: prod 는 mock 제외, qa/dev 는 mock 노출.
- SettingsStore._enforce_channel: prod 에서 저장된 mock provider 를 비-mock 으로 강등.
- SettingsStore.update: prod 에서 들어오는 mock 전환을 거부.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.settings import list_providers
from core import config
from settings.store import SettingsStore


async def test_list_providers_hides_mock_in_prod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """prod 채널이면 provider 목록에 mock 이 없다."""
    monkeypatch.setattr(config, "BUILD_CHANNEL", "prod")

    ids = {p.id for p in await list_providers()}

    assert "mock" not in ids
    assert "dtgpt" in ids


async def test_list_providers_shows_mock_in_qa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """qa/dev 채널이면 mock 이 노출된다(테스트 시나리오용)."""
    monkeypatch.setattr(config, "BUILD_CHANNEL", "qa")

    ids = {p.id for p in await list_providers()}

    assert "mock" in ids


def _write_settings(path: Path, provider: str) -> None:
    payload = {
        "provider": provider,
        "providers": {provider: {"model": "", "api_key": "", "base_url": ""}},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_coerces_stored_mock_in_prod(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """과거 저장된 mock settings 가 prod 로 로드되면 비-mock 으로 강등된다."""
    monkeypatch.setattr(config, "BUILD_CHANNEL", "prod")
    settings_file = tmp_path / "settings.json"
    _write_settings(settings_file, "mock")

    store = SettingsStore(file_path=settings_file)

    assert store.get().provider != "mock"


def test_load_keeps_mock_in_qa(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """qa 채널은 저장된 mock 을 그대로 유지한다."""
    monkeypatch.setattr(config, "BUILD_CHANNEL", "qa")
    settings_file = tmp_path / "settings.json"
    _write_settings(settings_file, "mock")

    store = SettingsStore(file_path=settings_file)

    assert store.get().provider == "mock"


def test_update_rejects_mock_in_prod(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """prod 에서 mock 으로의 전환 patch 는 거부된다."""
    monkeypatch.setattr(config, "BUILD_CHANNEL", "prod")
    settings_file = tmp_path / "settings.json"
    _write_settings(settings_file, "dtgpt")
    store = SettingsStore(file_path=settings_file)

    with pytest.raises(ValueError, match="mock"):
        store.update({"provider": "mock"})


def test_update_allows_mock_in_qa(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """qa 채널은 mock 전환을 허용한다."""
    monkeypatch.setattr(config, "BUILD_CHANNEL", "qa")
    settings_file = tmp_path / "settings.json"
    _write_settings(settings_file, "dtgpt")
    store = SettingsStore(file_path=settings_file)

    updated = store.update({"provider": "mock"})

    assert updated.provider == "mock"
