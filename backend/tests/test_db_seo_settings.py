"""SEO LLM metadata and credential persistence."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.core.errors import ConfigurationError, StorageError, ValidationError
from app.db.seo_settings import SeoSettingsRepository
from tests.fakes import MemorySecrets, StrictSecrets, ToggleSecrets

ENDPOINT = "https://api.example.com/v1/chat/completions"
ENV_ENDPOINT = "https://env.example.com/v1/chat/completions"
KEY_ACCOUNT = ("test-service", "seo-llm")


def repo(path: Path, secrets: MemorySecrets, **kwargs) -> SeoSettingsRepository:
    return SeoSettingsRepository(
        path,
        secrets,
        env_endpoint=kwargs.get("env_endpoint"),
        env_model=kwargs.get("env_model"),
        env_api_key=kwargs.get("env_api_key"),
        service_name="test-service",
    )


def metadata(path: Path) -> dict:
    return json.loads((path / "seo-settings.json").read_text(encoding="utf-8"))


def test_absent_file_has_no_values_and_no_sources(tmp_path):
    repository = repo(tmp_path, MemorySecrets())

    settings = repository.load()

    assert (settings.endpoint, settings.model, settings.api_key) == ("", "", None)
    assert (settings.endpoint_source, settings.model_source, settings.api_key_source) == ("none", "none", "none")
    assert settings.has_api_key is False
    assert not (tmp_path / "seo-settings.json").exists()


def test_load_resolves_ui_over_env_per_field_with_independent_sources(tmp_path):
    store = MemorySecrets()
    repository = repo(tmp_path, store, env_endpoint=ENV_ENDPOINT, env_model="env-model", env_api_key="env-key")
    repository.update({"model": "ui-model"})

    settings = repository.load()

    assert (settings.endpoint, settings.endpoint_source) == (ENV_ENDPOINT, "env")
    assert (settings.model, settings.model_source) == ("ui-model", "ui")
    assert (settings.api_key, settings.api_key_source) == ("env-key", "env")


def test_metadata_is_atomic_private_and_never_contains_key(tmp_path, monkeypatch):
    store = MemorySecrets()
    repository = repo(tmp_path, store)
    repository.update({"endpoint": ENDPOINT, "model": "ui-model", "api_key": "private-key"})

    path = tmp_path / "seo-settings.json"
    assert metadata(tmp_path) == {"endpoint": ENDPOINT, "model": "ui-model"}
    assert "private-key" not in path.read_text(encoding="utf-8")
    assert path.stat().st_mode & 0o777 == 0o600
    assert store.values == {KEY_ACCOUNT: "private-key"}
    before = path.read_bytes()

    def fail_replace(*_args):
        raise OSError("disk unavailable")

    monkeypatch.setattr("app.db.seo_settings.os.replace", fail_replace)
    with pytest.raises(StorageError):
        repository.update({"endpoint": ENDPOINT, "model": "new-model"})
    assert path.read_bytes() == before
    assert list(tmp_path.glob(".seo-settings-*")) == []


def test_keyring_write_failure_preserves_metadata_and_old_key(tmp_path):
    store = ToggleSecrets()
    repository = repo(tmp_path, store)
    repository.update({"endpoint": ENDPOINT, "model": "old-model", "api_key": "old-key"})
    before = metadata(tmp_path)
    store.read_only = True

    with pytest.raises(ConfigurationError):
        repository.update({"model": "new-model", "api_key": "new-key"})

    assert metadata(tmp_path) == before
    assert store.values[KEY_ACCOUNT] == "old-key"


def test_metadata_write_failure_restores_previous_key(tmp_path, monkeypatch):
    store = MemorySecrets()
    repository = repo(tmp_path, store)
    repository.update({"endpoint": ENDPOINT, "model": "old-model", "api_key": "old-key"})
    before = metadata(tmp_path)
    monkeypatch.setattr("app.db.seo_settings.os.replace", lambda *_: (_ for _ in ()).throw(OSError("disk")))

    with pytest.raises(StorageError):
        repository.update({"model": "new-model", "api_key": "new-key"})

    assert metadata(tmp_path) == before
    assert store.values[KEY_ACCOUNT] == "old-key"


def test_partial_and_empty_updates_preserve_credentials(tmp_path):
    store = MemorySecrets()
    repository = repo(tmp_path, store)
    repository.update({"endpoint": ENDPOINT, "model": "ui-model", "api_key": "ui-key"})

    repository.update({"endpoint": "", "model": "  ", "api_key": ""})
    settings = repository.update({})

    assert (settings.endpoint, settings.model, settings.api_key) == (ENDPOINT, "ui-model", "ui-key")
    assert metadata(tmp_path) == {"endpoint": ENDPOINT, "model": "ui-model"}
    assert store.values[KEY_ACCOUNT] == "ui-key"


def test_reset_removes_overrides_and_falls_back_to_the_environment(tmp_path):
    store = MemorySecrets()
    repository = repo(tmp_path, store, env_endpoint=ENV_ENDPOINT, env_model="env-model", env_api_key="env-key")
    repository.update({"endpoint": ENDPOINT, "model": "ui-model", "api_key": "ui-key"})

    settings = repository.reset_credentials()

    assert (settings.endpoint, settings.endpoint_source) == (ENV_ENDPOINT, "env")
    assert (settings.model, settings.model_source) == ("env-model", "env")
    assert (settings.api_key, settings.api_key_source) == ("env-key", "env")
    assert metadata(tmp_path) == {}
    assert store.values == {}


def test_reset_without_overrides_is_a_no_op_even_with_a_strict_store(tmp_path):
    store = StrictSecrets()
    repository = repo(tmp_path, store)

    settings = repository.reset_credentials()

    assert (settings.endpoint_source, settings.model_source, settings.api_key_source) == ("none", "none", "none")
    assert not (tmp_path / "seo-settings.json").exists()


def test_update_rejects_unknown_fields_and_wrong_types(tmp_path):
    repository = repo(tmp_path, MemorySecrets())

    for payload in ({"other": "value"}, {"endpoint": None}, {"model": 42}, {"api_key": None}):
        with pytest.raises(ValidationError):
            repository.update(payload)

    assert not (tmp_path / "seo-settings.json").exists()


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://api.example.com/v1/chat/completions",
        "https://192.168.1.10/v1/chat/completions",
        "https://api.example.com/v1/other",
    ],
)
def test_update_rejects_an_unsafe_endpoint_without_persisting(tmp_path, endpoint):
    store = MemorySecrets()
    repository = repo(tmp_path, store)

    with pytest.raises(ValidationError):
        repository.update({"endpoint": endpoint, "model": "ui-model"})

    assert not (tmp_path / "seo-settings.json").exists()
    assert store.values == {}


@pytest.mark.parametrize("value", ['{"endpoint": 42}', '{"model": ""}', '{"endpoint": "not a url"}', "[]"])
def test_unreadable_metadata_is_a_safe_storage_error(tmp_path, value):
    (tmp_path / "seo-settings.json").write_text(value, encoding="utf-8")
    repository = repo(tmp_path, MemorySecrets())

    with pytest.raises(StorageError) as error:
        repository.load()

    assert str(tmp_path) not in str(error.value)


def test_keyring_read_failure_is_reported_safely(tmp_path):
    store = MemorySecrets()

    def fail_read(_service, _username):
        raise RuntimeError("private keyring path")

    store.get_password = fail_read
    repository = repo(tmp_path, store)

    with pytest.raises(ConfigurationError, match="Системное хранилище ключей недоступно") as error:
        repository.load()

    assert "private keyring path" not in str(error.value)


def test_unreadable_metadata_path_is_reported_safely(tmp_path, monkeypatch):
    repository = repo(tmp_path, MemorySecrets())
    original_exists = Path.exists

    def inaccessible(path):
        if path == repository.path:
            raise PermissionError("private metadata path")
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", inaccessible)
    with pytest.raises(StorageError, match="прочитать настройки SEO-анализа") as error:
        repository.load()
    assert "private metadata path" not in str(error.value)


def test_failed_update_reports_rollback_failure_with_storage_context(tmp_path, monkeypatch):
    store = MemorySecrets()
    repository = repo(tmp_path, store)
    repository.update({"endpoint": ENDPOINT, "model": "old-model", "api_key": "old-key"})
    original_set = store.set_password

    def refuse_restore(service, username, password):
        if password == "old-key":
            raise RuntimeError("keyring rollback unavailable")
        original_set(service, username, password)

    store.set_password = refuse_restore
    monkeypatch.setattr("app.db.seo_settings.os.replace", lambda *_: (_ for _ in ()).throw(OSError("disk")))

    with pytest.raises(ConfigurationError, match="восстановить ключ") as error:
        repository.update({"model": "new-model", "api_key": "new-key"})

    assert isinstance(error.value.__cause__, StorageError)
    assert metadata(tmp_path) == {"endpoint": ENDPOINT, "model": "old-model"}


def test_failed_reset_reports_rollback_failure_with_storage_context(tmp_path, monkeypatch):
    store = MemorySecrets()
    repository = repo(tmp_path, store)
    repository.update({"endpoint": ENDPOINT, "model": "old-model", "api_key": "old-key"})

    def refuse_restore(_service, _username, _password):
        raise RuntimeError("keyring rollback unavailable")

    store.set_password = refuse_restore
    monkeypatch.setattr("app.db.seo_settings.os.replace", lambda *_: (_ for _ in ()).throw(OSError("disk")))

    with pytest.raises(ConfigurationError, match="восстановить ключ") as error:
        repository.reset_credentials()

    assert isinstance(error.value.__cause__, StorageError)
    assert metadata(tmp_path) == {"endpoint": ENDPOINT, "model": "old-model"}


def test_cleanup_failure_does_not_mask_storage_error_or_prevent_key_rollback(tmp_path, monkeypatch):
    store = MemorySecrets()
    repository = repo(tmp_path, store)
    repository.update({"endpoint": ENDPOINT, "model": "old-model", "api_key": "old-key"})
    monkeypatch.setattr("app.db.seo_settings.os.replace", lambda *_: (_ for _ in ()).throw(OSError("disk")))
    monkeypatch.setattr("app.db.seo_settings.os.unlink", lambda *_: (_ for _ in ()).throw(OSError("cleanup")))

    with pytest.raises(StorageError):
        repository.update({"model": "new-model", "api_key": "new-key"})

    assert store.values[KEY_ACCOUNT] == "old-key"
    assert metadata(tmp_path) == {"endpoint": ENDPOINT, "model": "old-model"}


def test_cleanup_only_failure_is_reported_as_storage_error(tmp_path, monkeypatch):
    repository = repo(tmp_path, MemorySecrets())
    # Keep the temporary file after an otherwise successful write so cleanup runs.
    monkeypatch.setattr("app.db.seo_settings.os.replace", shutil.copyfile)
    monkeypatch.setattr("app.db.seo_settings.os.unlink", lambda *_: (_ for _ in ()).throw(OSError("cleanup")))

    with pytest.raises(StorageError, match="очистить временные настройки"):
        repository._write({"model": "ui-model"})


def test_update_does_not_read_the_keyring_after_persistence(tmp_path):
    store = MemorySecrets()
    repository = repo(tmp_path, store)
    repository.update({"endpoint": ENDPOINT, "model": "old-model", "api_key": "old-key"})
    original_get = store.get_password
    reads = 0

    def fail_second_read(service, username):
        nonlocal reads
        reads += 1
        if reads == 2:
            raise RuntimeError("post-commit keyring unavailable")
        return original_get(service, username)

    store.get_password = fail_second_read
    saved = repository.update({"model": "new-model", "api_key": "new-key"})

    assert reads == 1
    assert (saved.endpoint, saved.model, saved.api_key) == (ENDPOINT, "new-model", "new-key")
    assert metadata(tmp_path) == {"endpoint": ENDPOINT, "model": "new-model"}
    assert store.values[KEY_ACCOUNT] == "new-key"


def test_reset_does_not_read_the_keyring_after_persistence(tmp_path):
    store = MemorySecrets()
    repository = repo(tmp_path, store)
    repository.update({"endpoint": ENDPOINT, "model": "old-model", "api_key": "old-key"})
    original_get = store.get_password
    reads = 0

    def fail_second_read(service, username):
        nonlocal reads
        reads += 1
        if reads == 2:
            raise RuntimeError("post-commit keyring unavailable")
        return original_get(service, username)

    store.get_password = fail_second_read
    saved = repository.reset_credentials()

    assert reads == 1
    assert (saved.endpoint, saved.model, saved.api_key) == ("", "", None)
    assert metadata(tmp_path) == {}
    assert store.values == {}
