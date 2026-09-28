"""HTTP contract for safe, partial Yandex settings."""

from __future__ import annotations

from app.db.search_settings import SearchSettingsRepository


def test_get_returns_exact_safe_fields_for_mixed_sources(make_client, settings, secrets):
    repository = SearchSettingsRepository(
        settings.config_dir, secrets, env_api_key="env-secret",
        env_folder_id="env-folder", service_name=settings.service_name,
    )
    repository.update({"api_key": "ui-secret"})
    with make_client(search_settings_repository=repository) as client:
        response = client.get("/api/search/settings")
    assert response.status_code == 200
    assert response.json() == {"yandex": {
        "enabled": True, "folder_id": "env-folder", "has_api_key": True,
        "api_key_source": "ui", "folder_id_source": "env",
    }}
    assert "secret" not in response.text


def test_partial_put_and_empty_credentials_preserve_saved_values(make_client):
    with make_client() as client:
        assert client.put("/api/search/settings", json={"api_key": "hidden-key", "folder_id": "saved-folder"}).status_code == 200
        response = client.put("/api/search/settings", json={"enabled": False, "api_key": "", "folder_id": ""})
        assert response.status_code == 200
        assert response.json() == {"yandex": {
            "enabled": False, "folder_id": "saved-folder", "has_api_key": True,
            "api_key_source": "ui", "folder_id_source": "ui",
        }}
        assert "hidden-key" not in response.text
        assert client.get("/api/search/settings").json() == response.json()


def test_put_rejects_null_wrong_type_and_unknown_fields(make_client):
    with make_client() as client:
        for payload in ({"api_key": None}, {"folder_id": None}, {"enabled": None},
                        {"enabled": "false"}, {"other": "value"}):
            response = client.put("/api/search/settings", json=payload)
            assert response.status_code == 400, payload
            assert isinstance(response.json()["detail"], str)


def test_delete_resets_both_overrides_and_preserves_enabled(make_client, settings, secrets):
    repository = SearchSettingsRepository(
        settings.config_dir, secrets, env_api_key="env-secret",
        env_folder_id="env-folder", service_name=settings.service_name,
    )
    with make_client(search_settings_repository=repository) as client:
        client.put("/api/search/settings", json={"enabled": False, "api_key": "ui-secret", "folder_id": "ui-folder"})
        response = client.delete("/api/search/settings/credentials")
        assert response.status_code == 200
        assert response.json() == {"yandex": {
            "enabled": False, "folder_id": "env-folder", "has_api_key": True,
            "api_key_source": "env", "folder_id_source": "env",
        }}
        assert "secret" not in response.text


def test_delete_noop_reports_no_environment_sources(make_client):
    with make_client() as client:
        response = client.delete("/api/search/settings/credentials")
        assert response.status_code == 200
        assert response.json() == {"yandex": {
            "enabled": True, "folder_id": None, "has_api_key": False,
            "api_key_source": "none", "folder_id_source": "none",
        }}
