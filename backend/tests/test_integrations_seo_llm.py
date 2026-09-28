"""The async Chat Completions adapter for the SEO service LLM."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
import pytest

from app.core.errors import ProviderError
from app.integrations.seo_llm import READ_TIMEOUT, SeoLlmClient

ENDPOINT = "https://api.example.com/v1/chat/completions"


@asynccontextmanager
async def llm(handler):
    """A client over a mock transport, closed when the test leaves the block."""
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        yield SeoLlmClient(ENDPOINT, "test-key", "example-model", http)


@pytest.mark.anyio
async def test_sends_a_system_and_a_user_message_with_bearer_auth():
    def handler(request):
        assert request.method == "POST"
        assert str(request.url) == ENDPOINT
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.headers["Accept"] == "application/json"
        assert json.loads(request.content) == {
            "model": "example-model",
            "messages": [
                {"role": "system", "content": "Ты аналитик"},
                {"role": "user", "content": "Верни JSON"},
            ],
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    async with llm(handler) as client:
        assert await client.complete("Ты аналитик", "Верни JSON") == '{"ok": true}'


@pytest.mark.anyio
async def test_the_request_carries_a_bounded_timeout():
    seen: dict[str, object] = {}

    def handler(request):
        seen.update(request.extensions.get("timeout") or {})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    async with llm(handler) as client:
        await client.complete("system", "user")

    assert seen["read"] == READ_TIMEOUT
    assert seen["read"] > seen["connect"]


@pytest.mark.anyio
async def test_a_redirect_is_not_followed():
    requested: list[str] = []

    def handler(request):
        requested.append(str(request.url))
        if len(requested) == 1:
            return httpx.Response(302, headers={"location": "https://elsewhere.example.com/chat/completions"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "redirected"}}]})

    async with llm(handler) as client:
        with pytest.raises(ProviderError):
            await client.complete("system", "user")

    assert requested == [ENDPOINT]


@pytest.mark.parametrize(("status", "message"), [(401, "ключ"), (403, "ключ"), (429, "лимит"), (500, "недоступ")])
@pytest.mark.anyio
async def test_http_errors_are_fixed_safe_messages(status, message):
    def handler(request):
        return httpx.Response(status, text="private upstream detail")

    async with llm(handler) as client:
        with pytest.raises(ProviderError, match=message) as error:
            await client.complete("system", "user")

    assert "private upstream detail" not in str(error.value)
    assert "test-key" not in str(error.value)


@pytest.mark.parametrize(
    "body",
    [
        {"choices": []},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": "   "}}]},
        {"choices": [{"message": {"content": 42}}]},
        {"choices": [{"message": {}}]},
        {},
        {"error": {"message": "private upstream detail"}},
    ],
)
@pytest.mark.anyio
async def test_malformed_payloads_are_reported_safely(body):
    def handler(request):
        return httpx.Response(200, json=body)

    async with llm(handler) as client:
        with pytest.raises(ProviderError, match="ответ") as error:
            await client.complete("system", "user")

    assert "private upstream detail" not in str(error.value)


@pytest.mark.anyio
async def test_a_non_json_body_is_reported_safely():
    def handler(request):
        return httpx.Response(200, text="<html>private upstream detail</html>")

    async with llm(handler) as client:
        with pytest.raises(ProviderError, match="ответ") as error:
            await client.complete("system", "user")

    assert "private upstream detail" not in str(error.value)


@pytest.mark.anyio
async def test_a_transport_failure_is_reported_safely():
    def handler(request):
        raise httpx.ConnectTimeout("private-host timeout")

    async with llm(handler) as client:
        with pytest.raises(ProviderError, match="соединение") as error:
            await client.complete("system", "user")

    assert "private-host" not in str(error.value)
