"""The transport contract: schemas must neither leak nor drop a field.

`response_model` filters the payload through the schema, so a field added to a
service view but missing from its schema would silently disappear from the API
and break the browser BFF. These tests pin both directions.
"""

from __future__ import annotations

from app.api.schemas import CheckResponse, FormResponse, ProviderResponse
from tests.fakes import ENDPOINT, ProviderFactorySpy

CUSTOM_BODY = {"name": "Тест", "kind": "openai", "endpoint": ENDPOINT, "model": "m", "api_key": "k"}

# Fields the browser reads through the BFF projection in frontend/src/lib/server/python-api.ts.
BROWSER_PROVIDER_FIELDS = {
    "id", "name", "kind", "endpoint", "model", "configured",
    "editable_fields", "can_reset", "can_delete",
    "status_label", "delete_label", "delete_prompt", "delete_success",
}
BROWSER_FORM_FIELDS = {"limits", "new_provider_fields", "scope_options", "default_provider_ids"}
BROWSER_CHECK_FIELDS = {"brand", "domain", "checks", "summary", "rows"}


def test_provider_payload_carries_exactly_the_documented_fields(client):
    created = client.post("/api/providers", json=CUSTOM_BODY).json()
    listed = client.get("/api/providers").json()[0]

    for payload in (created, listed):
        assert BROWSER_PROVIDER_FIELDS <= set(payload)
        assert set(payload) <= set(ProviderResponse.model_fields)


def test_optional_fields_are_serialized_as_explicit_nulls(client):
    """A typed response keeps every declared key, so absent values arrive as null.

    The BFF reads them through `??`, so `null` and a missing key behave the same
    for the browser, while the API stays fully typed.
    """
    providers = client.get("/api/providers").json()

    assert set(providers[0]) == set(ProviderResponse.model_fields)
    assert set(providers[1]) == set(ProviderResponse.model_fields)
    assert providers[0]["endpoint"] is None
    assert providers[1]["scope"] is None


def test_form_payload_carries_exactly_the_documented_fields(client):
    form = client.get("/api/form").json()

    assert BROWSER_FORM_FIELDS <= set(form)
    assert set(form) == set(FormResponse.model_fields)
    assert set(form["limits"]) == set(FormResponse.model_fields["limits"].annotation.model_fields)
    assert set(form["scope_options"][0]) == {"value", "label"}


def test_check_payload_carries_exactly_the_documented_fields(make_client):
    client = make_client(provider_factory=ProviderFactorySpy())
    connection_id = client.post("/api/providers", json=CUSTOM_BODY).json()["id"]

    report = client.post(
        "/api/check",
        json={"brand": "Ромашка", "domain": "example.ru", "prompts": ["вопрос"], "provider_ids": [connection_id]},
    ).json()

    assert set(report) == set(CheckResponse.model_fields)
    assert set(report["summary"]) == set(CheckResponse.model_fields["summary"].annotation.model_fields)
    assert set(report["checks"][0]) == {"provider_id", "provider_name", "summary", "results"}
    assert set(report["checks"][0]["summary"]) == {"successful", "failed", "mentioned"}
    assert set(report["checks"][0]["results"][0]) == {"prompt", "answer", "mentioned", "error", "status"}
    assert set(report["rows"][0]) == {"prompt", "answer", "mentioned", "error", "status", "provider_name"}
    assert BROWSER_CHECK_FIELDS <= set(report)


def test_a_wrong_typed_body_is_rejected_as_400_not_422(client):
    response = client.post(
        "/api/check",
        json={"brand": "Ромашка", "prompts": "не список", "provider_ids": ["gigachat"]},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Некорректное поле «prompts»"}


def test_a_missing_required_field_is_rejected_as_400(client):
    response = client.post("/api/check", json={"prompts": ["вопрос"], "provider_ids": ["gigachat"]})

    assert response.status_code == 400
    assert response.json() == {"detail": "Некорректное поле «brand»"}


def test_a_missing_body_is_rejected_as_400(client):
    response = client.post("/api/check")

    assert response.status_code == 400
    assert response.json() == {"detail": "Некорректный запрос"}


def test_a_rejected_schema_never_reaches_the_service(make_client):
    spy = ProviderFactorySpy()
    client = make_client(provider_factory=spy)
    client.post("/api/providers", json=CUSTOM_BODY)

    client.post("/api/check", json={"prompts": ["вопрос"], "provider_ids": ["gigachat"]})

    assert spy.keys == []


def test_openapi_documents_every_operation(client):
    spec = client.get("/openapi.json").json()

    assert set(spec["paths"]) == {
        "/api/form", "/api/providers", "/api/providers/{connection_id}", "/api/check",
        "/api/providers/settings", "/api/providers/settings/{group_id}",
    }
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            assert operation["responses"]["200"]["content"]["application/json"]["schema"], (method, path)
            # Schema violations answer 400, so an advertised 422 would be a lie.
            assert "422" not in operation["responses"], (method, path)

    for name in ("CheckRequest", "CheckResponse", "ProviderWriteRequest", "ProviderResponse", "FormResponse", "ErrorResponse"):
        assert name in spec["components"]["schemas"]
