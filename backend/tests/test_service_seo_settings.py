"""The SEO service-LLM settings service: public shape, partial update, probe.

The plain probe is answered by `httpx.MockTransport` and the tool probe by a
scripted `FakeAgentModel`, so the suite proves both probe shapes without
reaching a paid API and the key never leaves the service.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from app.core.errors import ConfigurationError, ProviderError, ValidationError
from app.db.seo_settings import SeoSettingsRepository
from app.domain.seo_llm import AgentModel, AgentTurn
from app.integrations.seo_llm import (
    AUTHORIZATION_ERROR,
    PAYLOAD_ERROR,
    LangChainSeoLlmClient,
    SeoLlmClient,
)
from app.service.seo_settings import (
    NOT_CONFIGURED,
    TOOL_TEST_SCHEMA,
    TOOL_TEST_SYSTEM,
    TOOL_TEST_USER,
    TOOLS_UNSUPPORTED,
    SeoSettingsService,
)
from tests.fakes import FakeAgentModel, MemorySecrets, tool_call_turn

ENDPOINT = "https://api.example.com/v1/chat/completions"
OTHER_ENDPOINT = "https://llm.example.com/v1/chat/completions"
MODEL = "seo-model"
KEY = "seo-secret-key"
PUBLIC_FIELDS = {
    "endpoint", "model", "has_api_key",
    "endpoint_source", "model_source", "api_key_source",
}


def completion(text: str = "OK") -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def make_service(
    config_dir: Path,
    secrets: MemorySecrets,
    *,
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
    agent_model: AgentModel | None = None,
    env_endpoint: str | None = None,
    env_model: str | None = None,
    env_api_key: str | None = None,
) -> SeoSettingsService:
    repository = SeoSettingsRepository(
        config_dir, secrets, env_endpoint=env_endpoint, env_model=env_model,
        env_api_key=env_api_key, service_name="test",
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler or (lambda request: completion())),
        follow_redirects=False,
    )
    factory = None if agent_model is None else (lambda settings: agent_model)
    return SeoSettingsService(repository, client, agent_model_factory=factory)


def close(service: SeoSettingsService) -> None:
    asyncio.run(service.client.aclose())


def test_public_projection_returns_exact_safe_fields_and_never_the_key(config_dir, secrets):
    service = make_service(
        config_dir, secrets, env_endpoint=ENDPOINT, env_model=MODEL, env_api_key=KEY,
    )
    try:
        public = service.public()
    finally:
        close(service)

    assert set(public) == PUBLIC_FIELDS
    assert public == {
        "endpoint": ENDPOINT, "model": MODEL, "has_api_key": True,
        "endpoint_source": "env", "model_source": "env", "api_key_source": "env",
    }
    assert KEY not in json.dumps(public)


def test_public_projection_reports_unset_values_without_sources(config_dir, secrets):
    service = make_service(config_dir, secrets)
    try:
        public = service.public()
    finally:
        close(service)

    assert public == {
        "endpoint": None, "model": None, "has_api_key": False,
        "endpoint_source": "none", "model_source": "none", "api_key_source": "none",
    }


def test_update_is_partial_and_keeps_absent_fields(config_dir, secrets):
    service = make_service(config_dir, secrets)
    try:
        first = service.update({"endpoint": ENDPOINT, "model": MODEL})
        assert first == {
            "endpoint": ENDPOINT, "model": MODEL, "has_api_key": False,
            "endpoint_source": "ui", "model_source": "ui", "api_key_source": "none",
        }
        second = service.update({"api_key": KEY})
        assert second == {
            "endpoint": ENDPOINT, "model": MODEL, "has_api_key": True,
            "endpoint_source": "ui", "model_source": "ui", "api_key_source": "ui",
        }
        assert KEY not in json.dumps(second)
        assert service.public() == second
    finally:
        close(service)


def test_an_empty_key_and_empty_strings_never_clear_saved_values(config_dir, secrets):
    service = make_service(config_dir, secrets)
    try:
        service.update({"endpoint": ENDPOINT, "model": MODEL, "api_key": KEY})
        public = service.update({"endpoint": "", "model": "", "api_key": ""})
    finally:
        close(service)

    assert public == {
        "endpoint": ENDPOINT, "model": MODEL, "has_api_key": True,
        "endpoint_source": "ui", "model_source": "ui", "api_key_source": "ui",
    }


def test_update_validates_the_endpoint_before_writing(config_dir, secrets):
    service = make_service(config_dir, secrets)
    try:
        with pytest.raises(ValidationError):
            service.update({"endpoint": "http://remote.example.com/v1/chat/completions"})
        assert service.public()["endpoint"] is None
    finally:
        close(service)


@pytest.mark.parametrize(
    "payload",
    [{"endpoint": None}, {"model": None}, {"api_key": None}, {"model": 5}, {"other": "value"}],
)
def test_update_rejects_null_unknown_and_non_string_fields(config_dir, secrets, payload):
    service = make_service(config_dir, secrets)
    try:
        with pytest.raises(ValidationError):
            service.update(payload)
    finally:
        close(service)


def test_reset_credentials_falls_back_to_the_environment_and_is_idempotent(config_dir, secrets):
    service = make_service(
        config_dir, secrets, env_endpoint=ENDPOINT, env_model=MODEL, env_api_key=KEY,
    )
    try:
        service.update({"endpoint": OTHER_ENDPOINT, "model": "ui-model", "api_key": "ui-key"})
        reset = service.reset_credentials()
        assert reset == {
            "endpoint": ENDPOINT, "model": MODEL, "has_api_key": True,
            "endpoint_source": "env", "model_source": "env", "api_key_source": "env",
        }
        assert service.reset_credentials() == reset
        assert "ui-key" not in json.dumps(reset)
    finally:
        close(service)


def test_reset_credentials_without_saved_values_is_a_safe_noop(config_dir, secrets):
    service = make_service(config_dir, secrets)
    try:
        assert service.reset_credentials() == {
            "endpoint": None, "model": None, "has_api_key": False,
            "endpoint_source": "none", "model_source": "none", "api_key_source": "none",
        }
    finally:
        close(service)


def test_build_client_is_none_until_every_value_is_set(config_dir, secrets):
    service = make_service(config_dir, secrets)
    try:
        assert service.build_client() is None
        service.update({"endpoint": ENDPOINT, "model": MODEL})
        assert service.build_client() is None
        service.update({"api_key": KEY})
        client = service.build_client()
    finally:
        close(service)

    assert isinstance(client, SeoLlmClient)
    assert client.endpoint == ENDPOINT
    assert client.model == MODEL
    assert client.api_key == KEY


def test_build_client_reuses_the_shared_http_client(config_dir, secrets):
    service = make_service(
        config_dir, secrets, env_endpoint=ENDPOINT, env_model=MODEL, env_api_key=KEY,
    )
    try:
        client = service.build_client()
    finally:
        close(service)

    assert client is not None
    assert client.client is service.client


def test_build_agent_model_is_none_until_every_value_is_set(config_dir, secrets):
    service = make_service(config_dir, secrets)
    try:
        assert service.build_agent_model() is None
        service.update({"endpoint": ENDPOINT, "model": MODEL})
        assert service.build_agent_model() is None
        service.update({"api_key": KEY})
        model = service.build_agent_model()
    finally:
        close(service)

    assert isinstance(model, LangChainSeoLlmClient)
    assert model.settings.endpoint == ENDPOINT
    assert model.settings.model == MODEL


def test_build_agent_model_uses_the_injected_factory(config_dir, secrets):
    fake = FakeAgentModel()
    service = make_service(
        config_dir, secrets, agent_model=fake,
        env_endpoint=ENDPOINT, env_model=MODEL, env_api_key=KEY,
    )
    try:
        assert service.build_agent_model() is fake
    finally:
        close(service)


@pytest.mark.anyio
async def test_test_makes_a_plain_call_and_a_tool_probe(config_dir, secrets):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return completion("OK")

    fake = FakeAgentModel(tool_call_turn(TOOL_TEST_SCHEMA.name))
    service = make_service(
        config_dir, secrets, handler=handler, agent_model=fake,
        env_endpoint=ENDPOINT, env_model=MODEL, env_api_key=KEY,
    )
    try:
        result = await service.test()
    finally:
        await service.client.aclose()

    assert result == {"ok": True, "model": MODEL, "tools": True}
    assert KEY not in json.dumps(result)
    # The plain probe is one real chat call; the tool probe stays on the fake.
    assert len(seen) == 1
    assert seen[0].url == ENDPOINT
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"
    assert len(fake.steps) == 1
    messages, tools = fake.steps[0]
    assert [(message.role, message.content) for message in messages] == [
        ("system", TOOL_TEST_SYSTEM),
        ("user", TOOL_TEST_USER),
    ]
    assert tools == (TOOL_TEST_SCHEMA,)
    assert fake.closed is True


@pytest.mark.anyio
async def test_test_reports_a_model_that_answers_without_a_tool_call(config_dir, secrets):
    fake = FakeAgentModel(AgentTurn(text="OK"))
    service = make_service(
        config_dir, secrets, agent_model=fake,
        env_endpoint=ENDPOINT, env_model=MODEL, env_api_key=KEY,
    )
    try:
        result = await service.test()
    finally:
        await service.client.aclose()

    assert result == {"ok": False, "error": TOOLS_UNSUPPORTED}
    assert KEY not in json.dumps(result)
    assert len(fake.steps) == 1
    assert fake.closed is True


@pytest.mark.anyio
async def test_test_reports_a_failed_tool_probe_with_a_safe_error(config_dir, secrets):
    fake = FakeAgentModel(error=ProviderError(PAYLOAD_ERROR))
    service = make_service(
        config_dir, secrets, agent_model=fake,
        env_endpoint=ENDPOINT, env_model=MODEL, env_api_key=KEY,
    )
    try:
        result = await service.test()
    finally:
        await service.client.aclose()

    assert result == {"ok": False, "error": PAYLOAD_ERROR}
    assert KEY not in json.dumps(result)
    assert fake.closed is True


@pytest.mark.anyio
async def test_test_reports_the_safe_adapter_error_without_the_upstream_body(config_dir, secrets):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "upstream-secret-detail"})

    fake = FakeAgentModel()
    service = make_service(
        config_dir, secrets, handler=handler, agent_model=fake,
        env_endpoint=ENDPOINT, env_model=MODEL, env_api_key=KEY,
    )
    try:
        result = await service.test()
    finally:
        await service.client.aclose()

    assert result == {"ok": False, "error": AUTHORIZATION_ERROR}
    assert "upstream-secret-detail" not in json.dumps(result)
    assert KEY not in json.dumps(result)
    # A failed plain probe stops the check before the tool probe.
    assert fake.steps == []


@pytest.mark.anyio
async def test_test_answers_are_always_secret_free(config_dir, secrets):
    for fake in (FakeAgentModel(tool_call_turn(TOOL_TEST_SCHEMA.name)), FakeAgentModel()):
        service = make_service(
            config_dir, secrets, agent_model=fake,
            env_endpoint=ENDPOINT, env_model=MODEL, env_api_key=KEY,
        )
        try:
            result = await service.test()
        finally:
            await service.client.aclose()

        assert KEY not in json.dumps(result)
        assert set(result) <= {"ok", "model", "tools", "error"}


@pytest.mark.anyio
async def test_test_requires_a_complete_configuration(config_dir, secrets):
    service = make_service(config_dir, secrets)
    try:
        with pytest.raises(ConfigurationError) as error:
            await service.test()
    finally:
        await service.client.aclose()

    assert str(error.value) == NOT_CONFIGURED


def test_native_search_uses_only_direct_deepseek_settings(config_dir, secrets):
    service = make_service(config_dir, secrets, env_endpoint='https://api.deepseek.com/chat/completions', env_model='deepseek-flash', env_api_key=KEY)
    try:
        client = service.build_search_client()
        assert client.model == 'deepseek-flash'
        assert client.api_key == KEY
    finally:
        asyncio.run(service.client.aclose())


def test_native_search_refuses_to_forward_another_providers_key(config_dir, secrets):
    service = make_service(config_dir, secrets, env_endpoint=ENDPOINT, env_model=MODEL, env_api_key=KEY)
    try:
        with pytest.raises(ConfigurationError, match='DeepSeek') as error:
            service.build_search_client()
        assert KEY not in str(error.value)
    finally:
        asyncio.run(service.client.aclose())
