"""The transport contract: schemas must neither leak nor drop a field.

`response_model` filters the payload through the schema, so a field added to a
service view but missing from its schema would silently disappear from the API
and break the browser BFF. These tests pin both directions.
"""

from __future__ import annotations

from app.api.schemas import ProviderResponse
from tests.fakes import ENDPOINT, ProviderFactorySpy

CUSTOM_BODY = {"name": "Тест", "kind": "openai", "endpoint": ENDPOINT, "model": "m", "api_key": "k"}

# Fields the browser reads through the BFF projection in frontend/src/lib/server/python-api.ts.
BROWSER_PROVIDER_FIELDS = {
    "id", "name", "kind", "endpoint", "model", "configured",
    "editable_fields", "can_reset", "can_delete",
    "status_label", "delete_label", "delete_prompt", "delete_success",
}
INVALID_PROJECT_BODY = {
    "brand": "Ромашка",
    "site_url": "https://example.com",
    "queries": "не список",
}


def test_provider_payload_carries_exactly_the_documented_fields(client):
    created = client.post("/api/providers", json=CUSTOM_BODY).json()
    listed = client.get("/api/providers").json()[0]

    for payload in (created, listed):
        assert BROWSER_PROVIDER_FIELDS <= set(payload)
        assert set(payload) <= set(ProviderResponse.model_fields)


def test_a_provider_payload_carries_every_declared_key(client):
    """A typed response keeps every declared key, and never one that was dropped.

    The BFF reads the payload field by field, so a key that left the schema must
    leave the payload with it, and a declared one must always arrive.
    """
    providers = client.get("/api/providers").json()

    assert set(providers[0]) == set(ProviderResponse.model_fields)
    assert set(providers[1]) == set(ProviderResponse.model_fields)
    assert "scope" not in providers[0]
    assert providers[0]["endpoint"] == ENDPOINT


def test_a_wrong_typed_body_is_rejected_as_400_not_422(client):
    response = client.post("/api/projects", json=INVALID_PROJECT_BODY)

    assert response.status_code == 400
    assert response.json() == {"detail": "Некорректное поле «queries»"}


def test_a_missing_required_field_is_rejected_as_400(client):
    response = client.post("/api/projects", json={"site_url": "https://example.com"})

    assert response.status_code == 400
    assert response.json() == {"detail": "Некорректное поле «brand»"}


def test_a_missing_body_is_rejected_as_400(client):
    response = client.post("/api/projects")

    assert response.status_code == 400
    assert response.json() == {"detail": "Некорректный запрос"}


def test_a_rejected_schema_never_reaches_the_service(make_client):
    spy = ProviderFactorySpy()
    client = make_client(provider_factory=spy)
    client.post("/api/providers", json=CUSTOM_BODY)

    client.post("/api/projects", json=INVALID_PROJECT_BODY)

    assert spy.keys == []


def test_openapi_documents_every_operation(client):
    spec = client.get("/openapi.json").json()

    assert set(spec["paths"]) == {
        "/api/projects", "/api/projects/{id}", "/api/projects/{id}/measurements", "/api/projects/{id}/generate", "/api/projects/import-prompts",
        "/api/measurements/{id}", "/api/measurements/{id}/rows", "/api/measurements/{id}/cancel",
        "/api/config", "/api/version",
        "/api/providers", "/api/providers/{connection_id}",
        "/api/providers/settings", "/api/providers/settings/{group_id}",
        "/api/search/settings", "/api/search/settings/credentials",
        "/api/seo/settings", "/api/seo/settings/credentials", "/api/seo/settings/test",
    }
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            # One documented success status per operation: 200 for a result,
            # 202 for a job that keeps running in the background.
            success = [status for status in ("200", "201", "202", "204") if status in operation["responses"]]
            assert len(success) == 1, (method, path)
            if success[0] != "204":
                assert operation["responses"][success[0]]["content"]["application/json"]["schema"], (method, path)
            # Schema violations answer 400, so an advertised 422 would be a lie.
            assert "422" not in operation["responses"], (method, path)

    for name in ("ProviderWriteRequest", "ProviderResponse", "ErrorResponse",
                 "SearchSettingsWriteRequest", "SearchSettingsResponse", "YandexSettingsResponse",
                 "SeoSettingsWriteRequest", "SeoSettingsResponse", "SeoSettingsTestResponse"):
        assert name in spec["components"]["schemas"]
