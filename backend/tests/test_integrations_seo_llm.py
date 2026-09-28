"""The SEO service-LLM adapters: the manual chat client and the tool-calling one."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
import httpx2
import pytest

from app.core.errors import ProviderError
from app.domain.seo_llm import AgentMessage, AgentTurn, ToolCall, ToolSchema
from app.domain.seo_settings import SeoSettings
from app.integrations.seo_llm import (
    AUTHORIZATION_ERROR,
    CONNECTION_ERROR,
    PAYLOAD_ERROR,
    RATE_LIMIT_ERROR,
    READ_TIMEOUT,
    UNAVAILABLE_ERROR,
    LangChainSeoLlmClient,
    SeoLlmClient,
    chat_completions_base_url,
)

ENDPOINT = "https://api.example.com/v1/chat/completions"
MODEL = "example-model"
KEY = "test-key"
TOOL = ToolSchema(
    name="lookup",
    description="Найти домен в выдаче",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
)
OTHER_TOOL = ToolSchema(
    name="save_facts",
    description="Сохранить услуги",
    parameters={"type": "object", "properties": {"services": {"type": "array"}}},
)


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


def seo_settings(endpoint: str = ENDPOINT, model: str = MODEL, key: str = KEY) -> SeoSettings:
    return SeoSettings.resolve(ui_endpoint=endpoint, ui_model=model, ui_api_key=key)


def completion(message: dict) -> dict:
    """One OpenAI-compatible completion body around one assistant message."""
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": MODEL,
        "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
    }


def answer(text: str = "OK") -> dict:
    return completion({"role": "assistant", "content": text})


def calls_answer(*calls: dict, text: str | None = None) -> dict:
    return completion({"role": "assistant", "content": text, "tool_calls": list(calls)})


def tool_json(name: str = "lookup", arguments: str = '{"query": "доставка"}', call_id: str = "call_1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


@asynccontextmanager
async def agent(handler, *, endpoint: str = ENDPOINT, key: str = KEY, timeout: float = 120.0):
    """A tool-calling client over the mock transport the OpenAI SDK really uses."""
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler), follow_redirects=False)
    try:
        yield LangChainSeoLlmClient(
            seo_settings(endpoint=endpoint, key=key), timeout=timeout, http_async_client=http,
        )
    finally:
        await http.aclose()


def test_the_chat_completions_url_becomes_the_api_root_the_sdk_needs():
    assert chat_completions_base_url(ENDPOINT) == "https://api.example.com/v1"
    assert chat_completions_base_url("http://127.0.0.1:8080/v1/chat/completions") == (
        "http://127.0.0.1:8080/v1"
    )


def test_a_url_without_the_suffix_is_kept_as_the_api_root():
    assert chat_completions_base_url("https://api.example.com/v1/") == "https://api.example.com/v1"
    assert chat_completions_base_url("https://api.example.com/v1") == "https://api.example.com/v1"


@pytest.mark.anyio
async def test_the_client_uses_a_fixed_zero_temperature_model_with_the_given_timeout():
    client = LangChainSeoLlmClient(seo_settings(), timeout=45.0)
    try:
        model = client.chat_model
        assert model.openai_api_base == "https://api.example.com/v1"
        assert model.model_name == MODEL
        assert model.temperature == 0
        assert model.request_timeout == 45.0
        # One model call is one paid call: the SDK must not retry behind our back.
        assert model.max_retries == 0
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_step_posts_the_dialogue_to_the_configured_url_with_bearer_auth():
    seen: dict[str, object] = {}

    def handler(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=answer("Готово"))

    async with agent(handler) as client:
        turn = await client.step(
            (
                AgentMessage(role="system", content="Ты аналитик"),
                AgentMessage(role="user", content="Верни OK"),
            ),
            (),
        )

    assert seen["method"] == "POST"
    assert seen["url"] == ENDPOINT
    assert seen["authorization"] == f"Bearer {KEY}"
    assert seen["body"]["model"] == MODEL
    assert seen["body"]["temperature"] == 0
    assert seen["body"]["messages"] == [
        {"content": "Ты аналитик", "role": "system"},
        {"content": "Верни OK", "role": "user"},
    ]
    assert "tools" not in seen["body"]
    assert turn == AgentTurn(text="Готово", tool_calls=())


@pytest.mark.anyio
async def test_step_sends_the_tool_schemas_unchanged():
    seen: dict[str, object] = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx2.Response(200, json=answer("ok"))

    async with agent(handler) as client:
        await client.step((AgentMessage(role="user", content="прочитай сайт"),), (TOOL, OTHER_TOOL))

    assert seen["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Найти домен в выдаче",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "save_facts",
                "description": "Сохранить услуги",
                "parameters": {"type": "object", "properties": {"services": {"type": "array"}}},
            },
        },
    ]


@pytest.mark.anyio
async def test_one_tool_call_is_mapped_with_its_arguments():
    def handler(request):
        return httpx2.Response(
            200, json=calls_answer(tool_json(arguments='{"query": "доставка", "limit": 3}')),
        )

    async with agent(handler) as client:
        turn = await client.step((AgentMessage(role="user", content="найди"),), (TOOL,))

    assert turn == AgentTurn(
        text="",
        tool_calls=(
            ToolCall(id="call_1", name="lookup", arguments={"query": "доставка", "limit": 3}),
        ),
    )


@pytest.mark.anyio
async def test_several_tool_calls_keep_their_order_ids_and_names():
    def handler(request):
        return httpx2.Response(
            200,
            json=calls_answer(
                tool_json(arguments='{"query": "первый"}', call_id="call_1"),
                tool_json(name="save_facts", arguments='{"services": ["доставка"]}', call_id="call_2"),
                text="Сейчас проверю",
            ),
        )

    async with agent(handler) as client:
        turn = await client.step((AgentMessage(role="user", content="проверь"),), (TOOL, OTHER_TOOL))

    assert turn.text == "Сейчас проверю"
    assert turn.tool_calls == (
        ToolCall(id="call_1", name="lookup", arguments={"query": "первый"}),
        ToolCall(id="call_2", name="save_facts", arguments={"services": ["доставка"]}),
    )


@pytest.mark.anyio
async def test_text_without_tool_calls_is_a_turn_without_calls():
    def handler(request):
        return httpx2.Response(200, json=answer("Инструменты не нужны"))

    async with agent(handler) as client:
        turn = await client.step((AgentMessage(role="user", content="ответь"),), (TOOL,))

    assert turn == AgentTurn(text="Инструменты не нужны", tool_calls=())


@pytest.mark.anyio
async def test_empty_text_with_a_tool_call_keeps_the_call():
    def handler(request):
        return httpx2.Response(
            200, json=calls_answer(tool_json(arguments="{}"), text=None),
        )

    async with agent(handler) as client:
        turn = await client.step((AgentMessage(role="user", content="вызови"),), (TOOL,))

    assert turn.text == ""
    assert turn.tool_calls == (ToolCall(id="call_1", name="lookup", arguments={}),)


@pytest.mark.anyio
async def test_the_dialogue_history_is_mapped_to_openai_messages():
    seen: dict[str, object] = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx2.Response(200, json=answer("ok"))

    history = (
        AgentMessage(role="system", content="Ты аналитик"),
        AgentMessage(role="user", content="найди"),
        AgentMessage(
            role="assistant",
            content="",
            tool_calls=(ToolCall(id="call_1", name="lookup", arguments={"query": "доставка"}),),
        ),
        AgentMessage(role="tool", content='{"found": true}', tool_call_id="call_1"),
    )
    async with agent(handler) as client:
        await client.step(history, ())

    messages = seen["messages"]
    assert messages[:2] == [
        {"content": "Ты аналитик", "role": "system"},
        {"content": "найди", "role": "user"},
    ]
    assistant = messages[2]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"][0]["id"] == "call_1"
    assert assistant["tool_calls"][0]["function"]["name"] == "lookup"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"query": "доставка"}
    assert messages[3] == {"content": '{"found": true}', "role": "tool", "tool_call_id": "call_1"}


@pytest.mark.anyio
async def test_malformed_tool_arguments_are_a_safe_provider_error():
    def handler(request):
        return httpx2.Response(
            200, json=calls_answer(tool_json(arguments="{not json")),
        )

    async with agent(handler) as client:
        with pytest.raises(ProviderError) as error:
            await client.step((AgentMessage(role="user", content="вызови"),), (TOOL,))

    assert str(error.value) == PAYLOAD_ERROR
    assert "not json" not in str(error.value)


@pytest.mark.anyio
async def test_arguments_that_are_not_an_object_are_a_safe_provider_error():
    def handler(request):
        return httpx2.Response(200, json=calls_answer(tool_json(arguments="[1, 2]")))

    async with agent(handler) as client:
        with pytest.raises(ProviderError) as error:
            await client.step((AgentMessage(role="user", content="вызови"),), (TOOL,))

    assert str(error.value) == PAYLOAD_ERROR


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, AUTHORIZATION_ERROR),
        (403, AUTHORIZATION_ERROR),
        (429, RATE_LIMIT_ERROR),
        (500, UNAVAILABLE_ERROR),
        (503, UNAVAILABLE_ERROR),
    ],
)
@pytest.mark.anyio
async def test_status_errors_are_fixed_safe_messages(status, message):
    requested: list[str] = []

    def handler(request):
        requested.append(str(request.url))
        return httpx2.Response(status, json={"error": {"message": "private upstream detail"}})

    async with agent(handler) as client:
        with pytest.raises(ProviderError) as error:
            await client.step((AgentMessage(role="user", content="ответь"),), ())

    assert str(error.value) == message
    assert "private upstream detail" not in str(error.value)
    assert KEY not in str(error.value)
    # One step is one paid call, so a failed status must not be retried.
    assert requested == [ENDPOINT]


@pytest.mark.parametrize(
    "body",
    [
        {"choices": []},
        {"choices": [{"message": {"content": 42}}]},
        {},
    ],
)
@pytest.mark.anyio
async def test_tool_call_malformed_payloads_are_reported_safely(body):
    def handler(request):
        return httpx2.Response(200, json=body)

    async with agent(handler) as client:
        with pytest.raises(ProviderError) as error:
            await client.step((AgentMessage(role="user", content="ответь"),), ())

    assert str(error.value) == PAYLOAD_ERROR


@pytest.mark.anyio
async def test_tool_call_non_json_body_is_reported_safely():
    def handler(request):
        return httpx2.Response(200, text="<html>private upstream detail</html>")

    async with agent(handler) as client:
        with pytest.raises(ProviderError) as error:
            await client.step((AgentMessage(role="user", content="ответь"),), ())

    assert str(error.value) == PAYLOAD_ERROR
    assert "private upstream detail" not in str(error.value)


@pytest.mark.parametrize("failure", [httpx2.ConnectError("private-host"), httpx2.ReadTimeout("private-host")])
@pytest.mark.anyio
async def test_transport_failures_are_reported_safely(failure):
    def handler(request):
        raise failure

    async with agent(handler) as client:
        with pytest.raises(ProviderError) as error:
            await client.step((AgentMessage(role="user", content="ответь"),), ())

    assert str(error.value) == CONNECTION_ERROR
    assert "private-host" not in str(error.value)

