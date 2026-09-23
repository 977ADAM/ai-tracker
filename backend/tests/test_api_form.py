"""The form endpoint: limits, options, and the default selection."""

from __future__ import annotations

from tests.fakes import ENDPOINT


def test_form_publishes_the_limits_and_options(client):
    form = client.get("/api/form").json()
    assert form["limits"] == {
        "max_prompts": 20,
        "max_providers": 5,
        "max_prompt_length": 500,
        "max_brand_length": 100,
        "max_domain_length": 253,
    }
    assert form["new_provider_fields"] == ["name", "endpoint", "model", "api_key"]
    assert form["scope_options"][0] == {"value": "GIGACHAT_API_PERS", "label": "Персональный"}
    assert form["default_provider_ids"] == []


def test_default_selection_is_the_first_configured_connection(client):
    created = client.post(
        "/api/providers",
        json={"name": "Тест", "kind": "openai", "endpoint": ENDPOINT, "model": "m", "api_key": "k"},
    ).json()
    assert client.get("/api/form").json()["default_provider_ids"] == [created["id"]]


def test_form_reports_an_unreadable_configuration_as_unavailable(client, config_dir):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "providers.json").write_text("{", encoding="utf-8")
    response = client.get("/api/form")
    assert response.status_code == 503
    assert isinstance(response.json()["detail"], str)
