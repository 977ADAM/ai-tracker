"""The connection settings endpoints."""

from __future__ import annotations

from tests.fakes import ENDPOINT

CUSTOM_BODY = {"name": "Тест", "kind": "openai", "endpoint": ENDPOINT, "model": "m", "api_key": "secret-value"}


def test_creating_a_connection_never_returns_the_key(client):
    created = client.post("/api/providers", json=CUSTOM_BODY)
    assert created.status_code == 200
    assert "secret-value" not in created.text
    assert created.json()["configured"] is True
    assert "secret-value" not in client.get("/api/providers").text


def test_listing_starts_with_the_unconfigured_presets(client):
    providers = client.get("/api/providers").json()
    assert [item["id"] for item in providers] == ["gigachat", "deepseek"]
    assert providers[0]["editable_fields"] == ["scope", "api_key"]
    assert providers[0]["can_reset"] is True
    assert providers[1]["editable_fields"] == ["api_key"]
    assert providers[1]["can_reset"] is True


def test_updating_a_connection_keeps_the_saved_key(client):
    created = client.post("/api/providers", json=CUSTOM_BODY).json()
    updated = client.put(f"/api/providers/{created['id']}", json={"name": "Новое имя"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Новое имя"
    assert updated.json()["configured"] is True


def test_rejects_an_unsafe_endpoint(client):
    response = client.post(
        "/api/providers",
        json={**CUSTOM_BODY, "endpoint": "http://localhost/chat/completions"},
    )
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)


def test_rejects_editing_an_unknown_connection(client):
    response = client.put("/api/providers/nope", json={"name": "Тест", "endpoint": ENDPOINT, "model": "m"})
    assert response.status_code == 400


def test_deletes_a_connection(client):
    created = client.post("/api/providers", json=CUSTOM_BODY).json()
    response = client.delete(f"/api/providers/{created['id']}")
    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    assert [item["id"] for item in client.get("/api/providers").json()] == ["gigachat", "deepseek"]


def test_configuring_a_preset_keeps_its_metadata(client):
    response = client.put("/api/providers/gigachat", json={"api_key": "abc", "scope": "GIGACHAT_API_CORP"})
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "GigaChat"
    assert body["scope"] == "GIGACHAT_API_CORP"
    assert "abc" not in response.text


def test_resetting_a_preset_keeps_it_listed(client):
    client.put("/api/providers/gigachat", json={"api_key": "abc"})
    assert client.delete("/api/providers/gigachat").status_code == 200
    providers = client.get("/api/providers").json()
    assert [item["id"] for item in providers] == ["gigachat", "deepseek"]
    assert all(item["configured"] is False for item in providers)


def test_an_unreadable_configuration_is_reported_as_unavailable(client, config_dir):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "providers.json").write_text("{", encoding="utf-8")
    assert client.get("/api/providers").status_code == 503


SETTINGS_BODY = {
    "name": "Demo", "endpoint": ENDPOINT, "api_key": "shared-secret",
    "models": [{"model": "api-a", "name": "A"}, {"model": "api-b", "name": "B"}],
}


def test_settings_routes_create_update_list_and_delete_a_group(client):
    created = client.post("/api/providers/settings", json=SETTINGS_BODY)
    assert created.status_code == 200
    group = created.json()
    assert len(group["models"]) == 2
    assert group["configured"] is True
    assert "shared-secret" not in created.text

    listed = client.get("/api/providers/settings")
    assert listed.status_code == 200
    assert listed.json() == [group]
    assert "shared-secret" not in listed.text

    updated = client.put(f"/api/providers/settings/{group['id']}", json={
        "name": "Demo renamed", "endpoint": ENDPOINT, "api_key": "",
        "models": [{**group["models"][0], "name": "A renamed"}, group["models"][1]],
    })
    assert updated.status_code == 200
    assert updated.json()["models"][0]["name"] == "A renamed"
    assert updated.json()["configured"] is True
    assert client.delete(f"/api/providers/settings/{group['id']}").json() == {"deleted": True}
    assert client.get("/api/providers/settings").json() == []


def test_settings_rejects_empty_and_duplicate_model_lists(client):
    assert client.post("/api/providers/settings", json={**SETTINGS_BODY, "models": []}).status_code == 400
    duplicate = [{"id": "same", "model": "api-a", "name": "A"}, {"id": "same", "model": "api-b", "name": "B"}]
    assert client.post("/api/providers/settings", json={**SETTINGS_BODY, "models": duplicate}).status_code == 400


def test_settings_rejects_model_id_from_another_group(client):
    first = client.post("/api/providers/settings", json=SETTINGS_BODY).json()
    response = client.post("/api/providers/settings", json={
        **SETTINGS_BODY, "name": "Another", "models": [{**first["models"][0]}],
    })
    assert response.status_code == 400


def test_settings_rejects_invalid_endpoint_and_long_name(client):
    assert client.post("/api/providers/settings", json={**SETTINGS_BODY, "endpoint": "http://localhost/chat/completions"}).status_code == 400
    assert client.post("/api/providers/settings", json={**SETTINGS_BODY, "name": "x" * 101}).status_code == 400


def test_configuration_file_shows_metadata_without_the_key(client, config_dir):
    missing = client.get("/api/providers/settings/file")
    assert missing.status_code == 200
    assert missing.json() == {"path": str(config_dir / "providers.json"), "exists": False, "content": None}

    assert client.post("/api/providers/settings", json=SETTINGS_BODY).status_code == 200
    shown = client.get("/api/providers/settings/file")
    assert shown.status_code == 200
    body = shown.json()
    assert body["path"] == str(config_dir / "providers.json")
    assert body["exists"] is True
    assert "shared-secret" not in body["content"]
    assert "groups" in body["content"]


def test_configuration_file_shows_broken_json_as_text(client, config_dir):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "providers.json").write_text("{", encoding="utf-8")
    shown = client.get("/api/providers/settings/file")
    assert shown.status_code == 200
    assert shown.json() == {"path": str(config_dir / "providers.json"), "exists": True, "content": "{"}


def test_settings_delete_drops_shared_key(client, secrets):
    group_id = client.post("/api/providers/settings", json=SETTINGS_BODY).json()["id"]
    assert secrets.get_password("ai-tracker", group_id) == "shared-secret"
    assert client.delete(f"/api/providers/settings/{group_id}").status_code == 200
    assert secrets.get_password("ai-tracker", group_id) is None
