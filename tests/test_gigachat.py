import json
from uuid import UUID

import httpx
import pytest

from ai_tracker.gigachat import GigaChatClient, ProviderError


def test_authenticates_once_and_sends_prompts_unchanged():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/api/v2/oauth":
            assert request.headers["authorization"] == "Basic key"
            UUID(request.headers["rquid"])
            assert request.content == b"scope=GIGACHAT_API_PERS"
            return httpx.Response(200, json={"access_token": "token", "expires_at": 4102444800000})
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer token"
        body = json.loads(request.content)
        assert body["model"] == "GigaChat"
        assert body["messages"] == [{"role": "user", "content": "Первый вопрос" if len(requests) == 2 else "Второй вопрос"}]
        return httpx.Response(200, json={"choices": [{"message": {"content": "Ромашка"}}]})

    client = GigaChatClient("key", "GIGACHAT_API_PERS", transport=httpx.MockTransport(handler))
    assert client.answer("Первый вопрос") == "Ромашка"
    assert client.answer("Второй вопрос") == "Ромашка"
    assert sum(r.url.path == "/api/v2/oauth" for r in requests) == 1


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "авторизац"), (429, "лимит"), (500, "недоступ")],
)
def test_completion_errors_are_safe(status, message):
    def handler(request):
        if request.url.path == "/api/v2/oauth":
            return httpx.Response(200, json={"access_token": "token", "expires_at": 4102444800})
        return httpx.Response(status, text="secret-response-body")

    client = GigaChatClient("key", "GIGACHAT_API_PERS", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match=message) as error:
        client.answer("вопрос")
    assert "secret-response-body" not in str(error.value)


@pytest.mark.parametrize("response", [httpx.Response(200, text="not json"), httpx.Response(200, json={"choices": []}), httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})])
def test_bad_completion_response_is_error(response):
    def handler(request):
        if request.url.path == "/api/v2/oauth":
            return httpx.Response(200, json={"access_token": "token", "expires_at": 4102444800})
        return response

    client = GigaChatClient("key", "GIGACHAT_API_PERS", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="ответ"):
        client.answer("вопрос")


def test_timeout_is_safe_error():
    def handler(request):
        raise httpx.ConnectTimeout("hidden-address")

    client = GigaChatClient("key", "GIGACHAT_API_PERS", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="соединение") as error:
        client.answer("вопрос")
    assert "hidden-address" not in str(error.value)
