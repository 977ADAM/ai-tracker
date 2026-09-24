"""Metadata persistence and credential-store behaviour of the repository."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.core.errors import ConfigurationError, StorageError
from app.db.connections import ConnectionRepository
from app.domain.connections import new_custom_connection
from app.domain.provider_groups import ProviderGroup, ProviderModel
from tests.fakes import ENDPOINT, MemorySecrets, StrictSecrets, ToggleSecrets

CUSTOM_PAYLOAD = {"name": "Тест", "kind": "openai", "endpoint": ENDPOINT, "model": "example-model"}
SECRET = "secret-value"


def custom(payload: dict | None = None):
    return new_custom_connection({**CUSTOM_PAYLOAD, **(payload or {})})


def metadata_text(config_dir: Path) -> str:
    return (config_dir / "providers.json").read_text(encoding="utf-8")


def test_presets_come_first_and_a_custom_connection_survives_a_restart(config_dir, secrets, settings):
    repository = ConnectionRepository(config_dir, secrets, presets=settings.presets, env_api_key=settings.env_api_key)
    assert [item.id for item in repository.all()] == ["gigachat", "deepseek"]

    saved = custom()
    repository.save(saved, SECRET)

    second = ConnectionRepository(config_dir, secrets, presets=settings.presets, env_api_key=settings.env_api_key)
    assert [item.id for item in second.all()] == ["gigachat", "deepseek", saved.id]
    assert second.find(saved.id).model == "example-model"
    assert second.key(saved.id) == SECRET


def test_a_saved_key_never_reaches_the_metadata_file(config_dir, secrets, settings):
    repository = ConnectionRepository(config_dir, secrets, presets=settings.presets, env_api_key=settings.env_api_key)
    saved = custom()
    repository.save(saved, SECRET)

    text = metadata_text(config_dir)
    assert SECRET not in text
    assert "api_key" not in text
    assert (config_dir / "providers.json").stat().st_mode & 0o777 == 0o600
    assert json.loads(text)["custom"][0]["id"] == saved.id


def test_a_blank_key_keeps_the_saved_one(config_dir, secrets, settings):
    repository = ConnectionRepository(config_dir, secrets, presets=settings.presets, env_api_key=settings.env_api_key)
    saved = custom()
    repository.save(saved, SECRET)
    repository.save(replace(saved, name="Новый"), None)

    assert repository.key(saved.id) == SECRET
    assert repository.find(saved.id).name == "Новый"


def test_delete_removes_the_connection_and_its_key(config_dir, secrets, settings):
    repository = ConnectionRepository(config_dir, secrets, presets=settings.presets, env_api_key=settings.env_api_key)
    saved = custom()
    repository.save(saved, SECRET)

    repository.delete(saved.id)

    assert repository.find(saved.id) is None
    assert repository.key(saved.id) is None
    assert len(repository.all()) == 2


def test_a_failed_key_write_leaves_the_connection_untouched(config_dir, settings):
    secrets = ToggleSecrets()
    repository = ConnectionRepository(config_dir, secrets, presets=settings.presets, env_api_key=settings.env_api_key)
    saved = custom()
    repository.save(saved, "old-key")
    before = metadata_text(config_dir)

    secrets.read_only = True
    with pytest.raises(ConfigurationError) as error:
        repository.save(replace(saved, model="new-model"), "new-key")

    assert str(error.value) == "Не удалось сохранить ключ в системном хранилище"
    assert metadata_text(config_dir) == before
    secrets.read_only = False
    assert repository.key(saved.id) == "old-key"
    assert repository.find(saved.id).model == "example-model"


def test_an_unreachable_credential_store_cannot_read_a_key(config_dir, settings):
    secrets = MemorySecrets()
    secrets.fail = True
    repository = ConnectionRepository(config_dir, secrets, presets=settings.presets, env_api_key=settings.env_api_key)
    with pytest.raises(ConfigurationError) as error:
        repository.key("gigachat")
    assert str(error.value) == "Системное хранилище ключей недоступно"


def test_a_failed_metadata_write_restores_the_previous_key(config_dir, secrets, settings, monkeypatch):
    repository = ConnectionRepository(config_dir, secrets, presets=settings.presets, env_api_key=settings.env_api_key)
    saved = custom()
    repository.save(saved, "old-key")
    before = metadata_text(config_dir)

    def explode(*_args, **_kwargs):
        raise OSError("disk is gone")

    monkeypatch.setattr("app.db.connections.os.replace", explode)
    with pytest.raises(StorageError):
        repository.save(replace(saved, model="new-model"), "new-key")

    monkeypatch.undo()
    assert metadata_text(config_dir) == before
    assert repository.key(saved.id) == "old-key"
    assert repository.find(saved.id).model == "example-model"


def test_a_preset_scope_override_is_persisted(config_dir, secrets, settings):
    repository = ConnectionRepository(config_dir, secrets, presets=settings.presets, env_api_key=settings.env_api_key)
    preset = repository.find("gigachat")
    repository.save(replace(preset, scope="GIGACHAT_API_CORP"), "abc")

    assert repository.find("gigachat").scope == "GIGACHAT_API_CORP"
    assert json.loads(metadata_text(config_dir))["presets"] == {"gigachat": {"scope": "GIGACHAT_API_CORP"}}


def test_a_legacy_top_level_preset_entry_is_absorbed(config_dir, secrets, settings):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "providers.json").write_text(
        json.dumps({"gigachat": {"scope": "GIGACHAT_API_B2B"}}), encoding="utf-8"
    )
    repository = ConnectionRepository(config_dir, secrets, presets=settings.presets, env_api_key=settings.env_api_key)
    assert repository.find("gigachat").scope == "GIGACHAT_API_B2B"


def test_corrupted_metadata_is_reported_as_a_storage_error(config_dir, secrets, settings):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "providers.json").write_text("не json", encoding="utf-8")
    repository = ConnectionRepository(config_dir, secrets, presets=settings.presets, env_api_key=settings.env_api_key)
    with pytest.raises(StorageError):
        repository.all()


def test_malformed_custom_entries_are_skipped(config_dir, secrets, settings):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "providers.json").write_text(
        json.dumps({"custom": [{"id": "a"}, {"id": "b", "name": "Без модели"}, "мусор"]}),
        encoding="utf-8",
    )
    repository = ConnectionRepository(config_dir, secrets, presets=settings.presets, env_api_key=settings.env_api_key)
    assert [item.id for item in repository.all()] == ["gigachat", "deepseek"]


def test_a_saved_key_wins_over_the_environment(config_dir, secrets, settings, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    repository = ConnectionRepository(config_dir, secrets, presets=settings.presets, env_api_key=settings.env_api_key)
    preset = repository.find("deepseek")
    repository.save(preset, "saved-key")

    assert repository.key("deepseek") == "saved-key"


def test_the_environment_fallback_applies_without_a_saved_key(config_dir, secrets, settings, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    repository = ConnectionRepository(config_dir, secrets, presets=settings.presets, env_api_key=settings.env_api_key)
    assert repository.key("deepseek") == "env-key"
    assert repository.key("gigachat") is None


def test_a_broken_store_still_uses_the_environment_fallback(config_dir, settings, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    secrets = MemorySecrets()
    secrets.fail = True
    repository = ConnectionRepository(config_dir, secrets, presets=settings.presets, env_api_key=settings.env_api_key)
    assert repository.key("deepseek") == "env-key"

    monkeypatch.delenv("DEEPSEEK_API_KEY")
    with pytest.raises(ConfigurationError):
        repository.key("deepseek")


def test_resetting_a_preset_without_a_saved_key_does_not_touch_the_store(config_dir, settings, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    secrets = StrictSecrets()
    repository = ConnectionRepository(config_dir, secrets, presets=settings.presets, env_api_key=settings.env_api_key)

    repository.delete("deepseek")

    assert repository.key("deepseek") == "env-key"
    assert secrets.values == {}


def test_find_returns_none_for_an_unknown_connection(config_dir, secrets, settings):
    repository = ConnectionRepository(config_dir, secrets, presets=settings.presets, env_api_key=settings.env_api_key)
    assert repository.find("nope") is None


def test_legacy_custom_connection_becomes_a_provider_group(config_dir, secrets):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "providers.json").write_text(json.dumps({
        "custom": [{"id": "old", "name": "Old", "kind": "openai", "endpoint": ENDPOINT, "model": "legacy-model"}],
        "presets": {},
    }), encoding="utf-8")
    secrets.set_password("ai-tracker", "old", SECRET)
    repository = ConnectionRepository(config_dir, secrets)

    group = repository.groups()[0]
    assert (group.id, group.models[0].id, group.models[0].model) == ("old", "old", "legacy-model")
    assert repository.group_key("old") == SECRET


def test_provider_group_round_trip_shares_one_key(config_dir, secrets):
    repository = ConnectionRepository(config_dir, secrets)
    group = ProviderGroup(
        id="group-1", name="Demo", endpoint=ENDPOINT,
        models=(ProviderModel(id="model-1", model="api-a", name="A"), ProviderModel(id="model-2", model="api-b", name="B")),
    )

    repository.save_group(group, SECRET)

    saved = ConnectionRepository(config_dir, secrets).groups()
    assert saved == [group]
    assert repository.group_key("group-1") == SECRET
    assert SECRET not in metadata_text(config_dir)
    assert json.loads(metadata_text(config_dir))["version"] == 2


def test_malformed_legacy_group_migration_leaves_file_untouched(config_dir, secrets):
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "providers.json"
    path.write_text(json.dumps({"custom": [{"id": "bad", "name": "Bad", "endpoint": ENDPOINT, "model": []}]}), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    repository = ConnectionRepository(config_dir, secrets)

    with pytest.raises(StorageError):
        repository.groups()
    assert path.read_text(encoding="utf-8") == before


def test_failed_group_write_restores_previous_key(config_dir, secrets, monkeypatch):
    repository = ConnectionRepository(config_dir, secrets)
    group = ProviderGroup(id="group-1", name="Demo", endpoint=ENDPOINT, models=(ProviderModel(id="model-1", model="api-a", name="A"),))
    repository.save_group(group, "old-key")
    before = metadata_text(config_dir)
    monkeypatch.setattr("app.db.connections.os.replace", lambda *_args: (_ for _ in ()).throw(OSError("disk")))

    with pytest.raises(StorageError):
        repository.save_group(replace(group, name="Changed"), "new-key")

    monkeypatch.undo()
    assert metadata_text(config_dir) == before
    assert repository.group_key("group-1") == "old-key"


def test_legacy_connection_methods_work_after_group_migration(config_dir, secrets):
    repository = ConnectionRepository(config_dir, secrets)
    group = ProviderGroup(id="group-1", name="Demo", endpoint=ENDPOINT, models=(ProviderModel(id="model-1", model="api-a", name="A"),))
    repository.save_group(group, SECRET)

    legacy_view = repository.find("model-1")
    assert legacy_view is not None
    repository.save(replace(legacy_view, model="api-b"), None)
    assert repository.groups()[0].models[0].model == "api-b"
    repository.delete("model-1")
    assert repository.groups() == []
