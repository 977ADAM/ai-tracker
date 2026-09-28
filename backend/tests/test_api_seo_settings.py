"""HTTP contract for the safe, partial SEO service-LLM settings."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.db.seo_settings import SeoSettingsRepository
from app.integrations.seo_llm import AUTHORIZATION_ERROR
from app.service.seo_settings import NOT_CONFIGURED, SeoSettingsService

ENDPOINT = "https://api.example.com/v1/chat/completions"
OTHER_ENDPOINT = "https://llm.example.com/v1/chat/completions"
MODEL = "seo-model"
KEY = "ui-secret-key-value"
ENV_KEY = "env-secret-key-value"
PUBLIC_FIELDS = {
    "endpoint", "model", "has_api_key",
    "endpoint_source", "model_source", "api_key_source",
}


def completion() -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})


def make_repository(settings, secrets, *, env_endpoint=None, env_model=None, env_api_key=None):
    return SeoSettingsRepository(
        settings.config_dir, secrets, env_endpoint=env_endpoint, env_model=env_model,
        env_api_key=env_api_key, service_name=settings.service_name,
    )


@pytest.fixture
def fake_settings_service(settings, secrets):
    """Build service-LLM settings services over a mock transport and close them."""
    services: list[SeoSettingsService] = []

    def build(handler=None, *, endpoint=None, model=None, api_key=None) -> SeoSettingsService:
        repository = make_repository(
            settings, secrets, env_endpoint=endpoint, env_model=model, env_api_key=api_key,
        )
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler or (lambda request: completion())),
            follow_redirects=False,
        )
        service = SeoSettingsService(repository, client)
        services.append(service)
        return service

    yield build
    for service in services:
        asyncio.run(service.client.aclose())


def test_get_returns_exact_safe_fields_for_mixed_sources(make_client, settings, secrets):
    repository = make_repository(
        settings, secrets, env_endpoint=ENDPOINT, env_model=MODEL, env_api_key=ENV_KEY,
    )
    repository.update({"endpoint": OTHER_ENDPOINT})
    with make_client(seo_settings_repository=repository) as client:
        response = client.get("/api/seo/settings")

    assert response.status_code == 200
    assert set(response.json()) == PUBLIC_FIELDS
    assert response.json() == {
        "endpoint": OTHER_ENDPOINT, "model": MODEL, "has_api_key": True,
        "endpoint_source": "ui", "model_source": "env", "api_key_source": "env",
    }
    assert ENV_KEY not in response.text


def test_partial_put_and_empty_values_preserve_saved_settings(make_client):
    with make_client() as client:
        created = client.put("/api/seo/settings", json={
            "endpoint": ENDPOINT, "model": MODEL, "api_key": KEY,
        })
        assert created.status_code == 200
        assert created.json() == {
            "endpoint": ENDPOINT, "model": MODEL, "has_api_key": True,
            "endpoint_source": "ui", "model_source": "ui", "api_key_source": "ui",
        }

        partial = client.put("/api/seo/settings", json={"model": "other-model"})
        assert partial.status_code == 200
        assert partial.json()["endpoint"] == ENDPOINT
        assert partial.json()["model"] == "other-model"
        assert partial.json()["has_api_key"] is True

        unchanged = client.put("/api/seo/settings", json={
            "endpoint": "", "model": "", "api_key": "",
        })
        assert unchanged.status_code == 200
        assert unchanged.json() == partial.json()
        assert KEY not in unchanged.text
        assert client.get("/api/seo/settings").json() == partial.json()


def test_put_rejects_null_wrong_type_unknown_fields_and_unsafe_endpoints(make_client):
    with make_client() as client:
        for payload in (
            {"endpoint": None}, {"model": None}, {"api_key": None}, {"model": 5},
            {"other": "value", "api_key": KEY},
            {"endpoint": "http://remote.example.com/v1/chat/completions"},
            {"endpoint": f"https://user:{KEY}@api.example.com/v1/chat/completions"},
        ):
            response = client.put("/api/seo/settings", json=payload)
            assert response.status_code == 400, payload
            assert isinstance(response.json()["detail"], str)
            assert KEY not in response.text


def test_delete_resets_overrides_and_preserves_environment_fallbacks(
    make_client, settings, secrets,
):
    repository = make_repository(
        settings, secrets, env_endpoint=ENDPOINT, env_model=MODEL, env_api_key=ENV_KEY,
    )
    with make_client(seo_settings_repository=repository) as client:
        client.put("/api/seo/settings", json={
            "endpoint": OTHER_ENDPOINT, "model": "ui-model", "api_key": KEY,
        })
        response = client.delete("/api/seo/settings/credentials")

        assert response.status_code == 200
        assert response.json() == {
            "endpoint": ENDPOINT, "model": MODEL, "has_api_key": True,
            "endpoint_source": "env", "model_source": "env", "api_key_source": "env",
        }
        assert KEY not in response.text
        assert ENV_KEY not in response.text


def test_delete_without_saved_values_is_a_safe_noop(make_client):
    with make_client() as client:
        response = client.delete("/api/seo/settings/credentials")

    assert response.status_code == 200
    assert response.json() == {
        "endpoint": None, "model": None, "has_api_key": False,
        "endpoint_source": "none", "model_source": "none", "api_key_source": "none",
    }


def test_settings_test_reports_success_without_the_key(make_client, fake_settings_service):
    service = fake_settings_service(endpoint=ENDPOINT, model=MODEL, api_key=KEY)
    with make_client(seo_settings_service=service) as client:
        response = client.post("/api/seo/settings/test")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "model": MODEL}
    assert KEY not in response.text


def test_settings_test_reports_a_safe_error_without_the_upstream_body(
    make_client, fake_settings_service,
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "upstream-secret-detail"})

    service = fake_settings_service(
        handler, endpoint=ENDPOINT, model=MODEL, api_key=KEY,
    )
    with make_client(seo_settings_service=service) as client:
        response = client.post("/api/seo/settings/test")

    assert response.status_code == 200
    assert response.json() == {"ok": False, "error": AUTHORIZATION_ERROR}
    assert "upstream-secret-detail" not in response.text
    assert KEY not in response.text


def test_settings_test_requires_a_configuration(make_client, fake_settings_service):
    service = fake_settings_service()
    with make_client(seo_settings_service=service) as client:
        response = client.post("/api/seo/settings/test")

    assert response.status_code == 400
    assert response.json() == {"detail": NOT_CONFIGURED}


def test_the_settings_resource_lives_under_the_api_prefix(make_client):
    with make_client() as client:
        assert client.get("/api/seo/settings").status_code == 200
        assert client.get("/seo/settings").status_code == 404


def test_the_container_builds_the_settings_service_over_the_shared_client(settings, secrets):
    from app.api.deps import build_container

    container = build_container(settings, secrets=secrets)
    try:
        assert isinstance(container.seo_settings, SeoSettingsService)
        assert container.seo_settings.client is container.search_client
        assert container.seo_settings.build_client() is None
    finally:
        asyncio.run(container.search_client.aclose())
