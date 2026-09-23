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
