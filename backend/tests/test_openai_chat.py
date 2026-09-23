import json

import httpx
import pytest

from ai_tracker.openai_chat import OpenAIChatClient
from ai_tracker.providers import ProviderError


def test_deepseek_request_uses_current_model_and_no_thinking():
    def handler(request):
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {
            "model": "deepseek-flash",
            "messages": [{"role": "user", "content": "Где заказать цветы?"}],
            "thinking": {"type": "disabled"},
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": "Ромашка"}}]})

    provider = OpenAIChatClient(
        "test-key", "https://api.deepseek.com/chat/completions", "deepseek-flash",
        thinking_disabled=True, transport=httpx.MockTransport(handler),
    )
    assert provider.answer("Где заказать цветы?") == "Ромашка"


def test_generic_connection_has_no_vendor_options():
    def handler(request):
        assert json.loads(request.content) == {
            "model": "example-model", "messages": [{"role": "user", "content": "Вопрос"}]
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": "Ответ"}}]})

    provider = OpenAIChatClient(
        "key", "https://api.example.com/v1/chat/completions", "example-model",
        transport=httpx.MockTransport(handler),
    )
    assert provider.answer("Вопрос") == "Ответ"


@pytest.mark.parametrize(
    ("status", "message"), [(401, "ключ"), (429, "лимит"), (500, "недоступ")]
)
def test_http_errors_hide_provider_body(status, message):
    provider = OpenAIChatClient(
        "key", "https://api.example.com/chat/completions", "model",
        transport=httpx.MockTransport(lambda request: httpx.Response(status, text="private-detail")),
    )
    with pytest.raises(ProviderError, match=message) as error:
        provider.answer("Вопрос")
    assert "private-detail" not in str(error.value)


@pytest.mark.parametrize("body", [{"choices": []}, {"choices": [{"message": {"content": ""}}]}])
def test_empty_or_malformed_answer_is_error(body):
    provider = OpenAIChatClient(
        "key", "https://api.example.com/chat/completions", "model",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)),
    )
    with pytest.raises(ProviderError, match="ответ"):
        provider.answer("Вопрос")


def test_network_timeout_is_safe_error():
    def handler(request):
        raise httpx.ReadTimeout("private-host")

    provider = OpenAIChatClient(
        "key", "https://api.example.com/chat/completions", "model",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError, match="соединение") as error:
        provider.answer("Вопрос")
    assert "private-host" not in str(error.value)


def test_close_releases_http_client():
    provider = OpenAIChatClient("key", "https://api.example.com/chat/completions", "model")
    provider.close()
    assert provider.http.is_closed
