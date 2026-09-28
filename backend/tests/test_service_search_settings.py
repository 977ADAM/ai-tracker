"""Resolved search settings immediately configure new Yandex jobs."""

from __future__ import annotations

import httpx

from app.db.search_settings import SearchSettingsRepository
from app.service.search import SearchService
from app.service.search_settings import SearchSettingsService
from tests.fakes import MemorySecrets


def make_service(tmp_path, *, env_api_key=None, env_folder_id=None):
    secrets = MemorySecrets()
    repository = SearchSettingsRepository(
        tmp_path, secrets, env_api_key=env_api_key,
        env_folder_id=env_folder_id, service_name="test",
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    search = SearchService(None)
    settings = SearchSettingsService(repository, search, client)
    return settings, search, client


def test_public_projects_mixed_sources_without_exposing_key(tmp_path):
    settings, search, _client = make_service(tmp_path, env_api_key="env-secret", env_folder_id="env-folder")
    settings.update({"api_key": "ui-secret"})
    assert settings.public() == {"yandex": {
        "enabled": True, "folder_id": "env-folder", "has_api_key": True,
        "api_key_source": "ui", "folder_id_source": "env",
    }}
    assert search.gateway is not None


def test_partial_update_and_empty_credentials_preserve_existing_values(tmp_path):
    settings, search, _client = make_service(tmp_path)
    settings.update({"api_key": "private", "folder_id": "folder"})
    assert settings.update({"enabled": False, "api_key": "", "folder_id": ""}) == {"yandex": {
        "enabled": False, "folder_id": "folder", "has_api_key": True,
        "api_key_source": "ui", "folder_id_source": "ui",
    }}
    assert search.enabled is False


def test_reset_removes_both_overrides_and_keeps_enabled(tmp_path):
    settings, search, _client = make_service(tmp_path, env_api_key="fallback-key", env_folder_id="fallback-folder")
    settings.update({"enabled": False, "api_key": "saved-key", "folder_id": "saved-folder"})
    assert settings.reset_credentials() == {"yandex": {
        "enabled": False, "folder_id": "fallback-folder", "has_api_key": True,
        "api_key_source": "env", "folder_id_source": "env",
    }}
    assert search.enabled is False


def test_reset_noop_and_no_environment_sources(tmp_path):
    settings, search, _client = make_service(tmp_path)
    expected = {"yandex": {
        "enabled": True, "folder_id": None, "has_api_key": False,
        "api_key_source": "none", "folder_id_source": "none",
    }}
    assert settings.public() == expected
    assert settings.reset_credentials() == expected
    assert search.gateway is None
