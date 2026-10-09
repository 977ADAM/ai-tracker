"""Exercise the real adapter against controlled HTTP responses."""

import asyncio
import json

import httpx
import pytest

from app.core.errors import ProviderError
from app.integrations.deepseek_web import DeepSeekWebClient


def response_body(results=None, citations=None, **extra):
    return {
        "model": "selected-model", "stop_reason": "end_turn",
        "content": [
            {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "цветы"}},
            {"type": "web_search_tool_result", "tool_use_id": "s1", "content": results or []},
            {"type": "text", "text": "Ответ", "citations": citations or []},
        ], **extra,
    }


def answer(body):
    with DeepSeekWebClient("secret", "selected-model", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=body),
    )) as client:
        return client.answer("Где заказать цветы?")


def test_request_uses_native_search_and_selected_model():
    def handler(request):
        assert str(request.url) == "https://api.deepseek.com/anthropic/v1/messages"
        assert request.headers["x-api-key"] == "secret"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(request.content)
        assert body["model"] == "selected-model"
        assert body["max_tokens"] == 4096
        assert body["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]
        assert "Где заказать цветы?" in body["messages"][0]["content"][0]["text"]
        assert "ровно один вызов" in body["messages"][0]["content"][0]["text"]
        return httpx.Response(200, json=response_body())
    with DeepSeekWebClient("secret", "selected-model", transport=httpx.MockTransport(handler)) as client:
        assert client.answer("Где заказать цветы?").text == "Ответ"


def test_maps_text_results_and_citations():
    body = response_body(
        results=[{"type": "web_search_result", "url": "https://example.com/a", "title": "Страница"}],
        citations=[{"type": "web_search_result_location", "url": "https://example.com/a", "cited_text": "Факт"}],
    )
    body["content"].append({"type": "text", "text": "Продолжение", "citations": [
        {"url": "https://example.com/a", "cited_text": "Ещё факт"},
    ]})
    result = answer(body)
    assert result.text == "Ответ\n\nПродолжение"
    assert result.answer_mode == "deepseek_web"
    assert result.search_status == "completed"
    assert len(result.search_results) == 1
    assert len(result.citations) == 2
    assert result.citations[0].title == "Страница"
    assert [c.block_index for c in result.citations] == [0, 1]
    assert result.search_calls == 1
    assert result.model == "selected-model"


def test_empty_successful_search():
    result = answer(response_body())
    assert result.search_status == "completed"
    assert result.search_results == ()
    assert result.citations == ()


def test_completed_search_without_citations():
    result = answer(response_body(results=[{"type": "web_search_result", "url": "https://example.com/"}]))
    assert result.search_status == "completed"
    assert len(result.search_results) == 1
    assert result.citations == ()


def test_links_in_prose_do_not_become_citations():
    body = response_body()
    body["content"][-1]["text"] = "Рекомендуем https://example.com/"
    assert answer(body).citations == ()


def test_search_error_in_list_is_reported_as_search_failure():
    body = response_body(results=[{"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}])
    with pytest.raises(ProviderError, match="не выполнил веб-поиск|поиск завершился ошибкой"):
        answer(body)


@pytest.mark.parametrize("body", [
    None, [], {}, {"content": None},
    {"content": [{"type": "text", "text": "secret"}], "stop_reason": "end_turn"},
    response_body(content=[]),
    response_body(stop_reason="pause_turn"), response_body(stop_reason="max_tokens"),
    response_body(content=[{"type": "web_search_tool_result", "content": {"type": "web_search_tool_result_error", "error_code": "secret"}}, {"type": "text", "text": "Answer"}]),
    response_body(content=[{"type": "web_search_tool_result", "content": [{"type": "web_search_result", "url": 42}]}, {"type": "text", "text": "Answer"}]),
    response_body(content=[{"type": "web_search_tool_result", "content": []}, {"type": "text", "text": "   "}]),
])
def test_incomplete_or_invalid_search_answer_is_error(body):
    with pytest.raises(ProviderError) as error:
        answer(body)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_http_errors_hide_body_and_are_not_retried(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="private-secret", headers={"location": "https://elsewhere.com/"})
    with DeepSeekWebClient("secret", "selected-model", transport=httpx.MockTransport(handler)) as client, pytest.raises(ProviderError) as error:
        client.answer("Вопрос")
    assert len(calls) == 1
    assert "private-secret" not in str(error.value)


def test_network_timeout_is_not_retried():
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret", request=request)
    with DeepSeekWebClient("secret", "selected-model", transport=httpx.MockTransport(handler)) as client, pytest.raises(ProviderError) as error:
        client.answer("Вопрос")
    assert len(calls) == 1
    assert "secret" not in str(error.value)


def test_total_timeout_is_shared_across_response_chunks(monkeypatch):
    monkeypatch.setattr("app.integrations.deepseek_web.TOTAL_TIMEOUT", 0.04)
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(0.025)
            yield b'{"content":'
            await asyncio.sleep(0.025)
            yield b'[]}'
    with DeepSeekWebClient("secret", "selected-model", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=Stream()),
    )) as client, pytest.raises(ProviderError, match="время|таймаут"):
        client.answer("Вопрос")
