"""The connection settings use case."""

from __future__ import annotations

import pytest

from app.core.errors import ConfigurationError, StorageError, ValidationError
from app.service.connections import ConnectionService
from tests.fakes import ENDPOINT

CUSTOM_PAYLOAD = {
    "name": "Тест",
    "kind": "openai",
    "endpoint": ENDPOINT,
    "model": "example-model",
    "api_key": "secret-value",
}


@pytest.fixture
def service(repository, settings) -> ConnectionService:
    return ConnectionService(repository, settings)


def test_lists_presets_as_unconfigured(service):
    public = service.list_public()
    assert [item["id"] for item in public] == ["gigachat", "deepseek"]
    assert all(item["configured"] is False for item in public)
    assert all(item["status_label"] == "Нужен API-ключ" for item in public)


def test_creates_a_custom_connection_without_echoing_the_key(service):
    created = service.save(CUSTOM_PAYLOAD)
    assert created["configured"] is True
    assert created["name"] == "Тест"
    assert created["can_delete"] is True
    assert "api_key" not in created
    assert "secret-value" not in str(created)
    assert [item["id"] for item in service.list_public()] == ["gigachat", "deepseek", created["id"]]


def test_configures_a_preset_key_and_scope(service):
    configured = service.save({"api_key": "abc", "scope": "GIGACHAT_API_CORP"}, "gigachat")
    assert configured["scope"] == "GIGACHAT_API_CORP"
    assert configured["configured"] is True
    assert configured["can_reset"] is True


def test_preset_rejects_fields_it_does_not_own(service):
    with pytest.raises(ValidationError):
        service.save({"name": "Другое", "api_key": "abc"}, "gigachat")


def test_rejects_a_non_object_payload(service):
    with pytest.raises(ValidationError):
        service.save(["не объект"])


def test_rejects_an_unknown_connection_on_update(service):
    with pytest.raises(ValidationError):
        service.save({"name": "Тест", "endpoint": ENDPOINT, "model": "m"}, "nope")


def test_deletes_a_connection(service):
    created = service.save(CUSTOM_PAYLOAD)
    service.delete(created["id"])
    assert [item["id"] for item in service.list_public()] == ["gigachat", "deepseek"]


def test_deleting_an_unknown_connection_is_rejected(service):
    with pytest.raises(ValidationError):
        service.delete("nope")


def test_a_read_failure_surfaces_as_a_storage_error(service, config_dir):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "providers.json").write_text("{", encoding="utf-8")
    with pytest.raises(StorageError):
        service.list_public()


def test_a_write_failure_becomes_a_configuration_error(service, repository, monkeypatch):
    def explode(*_args, **_kwargs):
        raise StorageError("Не удалось сохранить настройки подключения")

    monkeypatch.setattr(repository, "save", explode)
    with pytest.raises(ConfigurationError):
        service.save(CUSTOM_PAYLOAD)


def test_a_key_lookup_failure_marks_the_connection_unconfigured(service, secrets):
    secrets.fail = True
    assert service.is_configured("gigachat") is False
    with pytest.raises(ConfigurationError):
        service.api_key("gigachat")
