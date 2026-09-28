"""Yandex settings metadata and credential persistence."""

import json
from pathlib import Path

import pytest

from app.core.errors import ConfigurationError, StorageError
from app.db.search_settings import SearchSettingsRepository
from tests.fakes import MemorySecrets, StrictSecrets, ToggleSecrets


def repo(path: Path, secrets: MemorySecrets, **kwargs) -> SearchSettingsRepository:
    return SearchSettingsRepository(path, secrets, env_api_key=kwargs.get("env_api_key"),
                                    env_folder_id=kwargs.get("env_folder_id"), service_name="test-service")


def metadata(path: Path) -> dict:
    return json.loads((path / "search-settings.json").read_text(encoding="utf-8"))


def test_absent_file_and_missing_enabled_default_to_true(tmp_path):
    store = MemorySecrets()
    repository = repo(tmp_path, store)
    assert repository.load().enabled is True
    (tmp_path / "search-settings.json").write_text('{"folder_id": "ui-folder"}')
    settings = repository.load()
    assert settings.enabled is True
    assert (settings.folder_id, settings.folder_id_source) == ("ui-folder", "ui")


def test_load_resolves_ui_over_env_with_independent_sources(tmp_path):
    store = MemorySecrets()
    repository = repo(tmp_path, store, env_api_key="env-key", env_folder_id="env-folder")
    assert repository.load().api_key_source == "env"
    repository.update({"api_key": "ui-key"})
    settings = repository.load()
    assert (settings.api_key, settings.api_key_source) == ("ui-key", "ui")
    assert (settings.folder_id, settings.folder_id_source) == ("env-folder", "env")


def test_metadata_is_atomic_private_and_never_contains_key(tmp_path, monkeypatch):
    store = MemorySecrets()
    repository = repo(tmp_path, store)
    repository.update({"enabled": False, "api_key": "private-key", "folder_id": "ui-folder"})
    path = tmp_path / "search-settings.json"
    assert metadata(tmp_path) == {"enabled": False, "folder_id": "ui-folder"}
    assert "private-key" not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    assert store.values == {("test-service", "yandex-search"): "private-key"}
    before = path.read_bytes()

    def fail_replace(*_args):
        raise OSError("disk unavailable")

    monkeypatch.setattr("app.db.search_settings.os.replace", fail_replace)
    with pytest.raises(StorageError):
        repository.update({"enabled": True, "folder_id": "new-folder"})
    assert path.read_bytes() == before
    assert list(tmp_path.glob(".search-settings-*")) == []


def test_keyring_write_failure_preserves_metadata_and_old_key(tmp_path):
    store = ToggleSecrets()
    repository = repo(tmp_path, store)
    repository.update({"api_key": "old-key", "folder_id": "old-folder"})
    before = metadata(tmp_path)
    store.read_only = True
    with pytest.raises(ConfigurationError):
        repository.update({"enabled": False, "folder_id": "new-folder", "api_key": "new-key"})
    assert metadata(tmp_path) == before
    assert store.values[("test-service", "yandex-search")] == "old-key"


def test_metadata_write_failure_restores_previous_key(tmp_path, monkeypatch):
    store = MemorySecrets()
    repository = repo(tmp_path, store)
    repository.update({"api_key": "old-key", "folder_id": "old-folder"})
    before = metadata(tmp_path)
    monkeypatch.setattr("app.db.search_settings.os.replace", lambda *_: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(StorageError):
        repository.update({"api_key": "new-key", "folder_id": "new-folder"})
    assert metadata(tmp_path) == before
    assert store.values[("test-service", "yandex-search")] == "old-key"


def test_partial_and_empty_updates_preserve_credentials(tmp_path):
    store = MemorySecrets()
    repository = repo(tmp_path, store)
    repository.update({"enabled": False, "api_key": "ui-key", "folder_id": "ui-folder"})
    repository.update({"enabled": True, "api_key": "", "folder_id": "  "})
    settings = repository.update({})
    assert (settings.enabled, settings.api_key, settings.folder_id) == (True, "ui-key", "ui-folder")
    assert metadata(tmp_path) == {"enabled": True, "folder_id": "ui-folder"}


def test_reset_removes_both_overrides_and_preserves_enabled(tmp_path):
    store = MemorySecrets()
    repository = repo(tmp_path, store, env_api_key="env-key", env_folder_id="env-folder")
    repository.update({"enabled": False, "api_key": "ui-key", "folder_id": "ui-folder"})
    settings = repository.reset_credentials()
    assert settings.enabled is False
    assert (settings.api_key, settings.api_key_source) == ("env-key", "env")
    assert (settings.folder_id, settings.folder_id_source) == ("env-folder", "env")
    assert metadata(tmp_path) == {"enabled": False}
    assert store.values == {}


def test_reset_without_overrides_is_no_op_even_with_strict_store(tmp_path):
    store = StrictSecrets()
    repository = repo(tmp_path, store)
    settings = repository.reset_credentials()
    assert (settings.api_key_source, settings.folder_id_source) == ("none", "none")
    assert not (tmp_path / "search-settings.json").exists()
