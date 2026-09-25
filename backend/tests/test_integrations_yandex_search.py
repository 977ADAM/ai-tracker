"""The deferred Yandex Search API v2 adapter."""

from __future__ import annotations

import base64
import json
from contextlib import asynccontextmanager

import httpx
import pytest

from app.core.errors import ProviderError
from app.integrations.yandex_search import YandexSearchGateway, parse_documents

SEARCH_URL = "https://searchapi.api.cloud.yandex.net/v2/web/searchAsync"
OPERATIONS_URL = "https://operation.api.cloud.yandex.net/operations"


def raw_data(documents: int) -> str:
    """Base64 XML of `documents` results in order, as the Operation API returns it."""
    docs = "".join(f"<doc><url>https://site{index}.ru/page</url></doc>" for index in range(1, documents + 1))
    xml = f"<yandexsearch><response><results><grouping>{docs}</grouping></results></response></yandexsearch>"
    return base64.b64encode(xml.encode("utf-8")).decode("ascii")


@asynccontextmanager
async def gateway(handler, *, api_key: str = "test-key"):
    """A gateway over a mock transport, closed when the test leaves the block."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        yield YandexSearchGateway(api_key, "folder-1", client)
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_submits_a_deferred_search_request():
    def handler(request):
        assert request.method == "POST"
        assert str(request.url) == SEARCH_URL
        assert request.headers["Authorization"] == "Api-Key test-key"
        assert json.loads(request.content) == {
            "query": {"searchType": "SEARCH_TYPE_RU", "queryText": "цветы", "page": 0},
            "folderId": "folder-1",
            "responseFormat": "FORMAT_XML",
            "region": "1",
            "groupSpec": {"groupMode": "GROUP_MODE_FLAT", "groupsOnPage": "10", "docsInGroup": "1"},
        }
        return httpx.Response(200, json={"id": "operation-1", "done": False})

    async with gateway(handler) as client_gateway:
        assert await client_gateway.submit("цветы", 1) == "operation-1"


@pytest.mark.anyio
async def test_reads_the_operation_until_it_is_done():
    def handler(request):
        assert request.method == "GET"
        assert str(request.url) == f"{OPERATIONS_URL}/operation-1"
        assert request.headers["Authorization"] == "Api-Key test-key"
        return httpx.Response(200, json={"done": True, "response": {"rawData": raw_data(2)}})

    async with gateway(handler) as client_gateway:
        documents = await client_gateway.result("operation-1")
    assert [document.url for document in documents] == ["https://site1.ru/page", "https://site2.ru/page"]


@pytest.mark.anyio
async def test_an_unfinished_operation_has_no_result_yet():
    def handler(request):
        return httpx.Response(200, json={"id": "operation-1", "done": False})

    async with gateway(handler) as client_gateway:
        assert await client_gateway.result("operation-1") is None


@pytest.mark.anyio
async def test_keeps_only_the_first_ten_documents_in_order():
    def handler(request):
        return httpx.Response(200, json={"done": True, "response": {"rawData": raw_data(12)}})

    async with gateway(handler) as client_gateway:
        documents = await client_gateway.result("operation-1")
    assert len(documents) == 10
    assert documents[0].url == "https://site1.ru/page"
    assert documents[-1].url == "https://site10.ru/page"


def test_a_document_without_a_url_is_a_malformed_result():
    raw = b"<yandexsearch><doc><title>First</title></doc><doc><url>https://example.ru</url></doc></yandexsearch>"
    with pytest.raises(ProviderError, match="Не удалось получить выдачу Яндекса"):
        parse_documents(raw)


@pytest.mark.anyio
async def test_upstream_error_does_not_echo_credentials():
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "invalid key secret-value"}})

    async with gateway(handler, api_key="secret-value") as client_gateway:
        with pytest.raises(ProviderError) as raised:
            await client_gateway.submit("цветы", 1)
    assert "secret-value" not in str(raised.value)
    assert str(raised.value) == "Не удалось отправить запрос в Яндекс"


@pytest.mark.anyio
async def test_a_failed_operation_is_reported_without_upstream_details():
    def handler(request):
        return httpx.Response(200, json={"done": True, "error": {"message": "quota secret-value exhausted"}})

    async with gateway(handler, api_key="secret-value") as client_gateway:
        with pytest.raises(ProviderError) as raised:
            await client_gateway.result("operation-1")
    assert str(raised.value) == "Поиск Яндекса завершился ошибкой"


@pytest.mark.anyio
async def test_a_missing_raw_data_is_reported_safely():
    def handler(request):
        return httpx.Response(200, json={"done": True, "response": {}})

    async with gateway(handler) as client_gateway:
        with pytest.raises(ProviderError) as raised:
            await client_gateway.result("operation-1")
    assert str(raised.value) == "Не удалось получить выдачу Яндекса"


@pytest.mark.anyio
async def test_invalid_base64_or_xml_is_reported_safely():
    payloads = ["not base64 !", base64.b64encode(b"<broken").decode("ascii")]

    for payload in payloads:
        def handler(request, payload=payload):
            return httpx.Response(200, json={"done": True, "response": {"rawData": payload}})

        async with gateway(handler) as client_gateway:
            with pytest.raises(ProviderError) as raised:
                await client_gateway.result("operation-1")
        assert str(raised.value) == "Не удалось получить выдачу Яндекса"


@pytest.mark.anyio
async def test_an_error_document_in_the_xml_is_reported_safely():
    xml = base64.b64encode(b'<yandexsearch><error code="15">secret-value</error></yandexsearch>').decode("ascii")

    def handler(request):
        return httpx.Response(200, json={"done": True, "response": {"rawData": xml}})

    async with gateway(handler, api_key="secret-value") as client_gateway:
        with pytest.raises(ProviderError) as raised:
            await client_gateway.result("operation-1")
    assert str(raised.value) == "Поиск Яндекса завершился ошибкой"


@pytest.mark.anyio
async def test_a_transport_failure_is_reported_safely():
    def handler(request):
        raise httpx.ConnectTimeout("secret-value timeout")

    async with gateway(handler, api_key="secret-value") as client_gateway:
        with pytest.raises(ProviderError) as raised:
            await client_gateway.submit("цветы", 1)
        assert str(raised.value) == "Не удалось отправить запрос в Яндекс"


@pytest.mark.anyio
async def test_an_unsafe_operation_id_never_reaches_the_network():
    requests: list[httpx.Request] = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"done": True})

    async with gateway(handler) as client_gateway:
        for identifier in ["", "../../admin", "a/b", "x" * 200, "id with space"]:
            with pytest.raises(ProviderError) as raised:
                await client_gateway.result(identifier)
            assert str(raised.value) == "Некорректный идентификатор операции Яндекса"
    assert requests == []


@pytest.mark.anyio
async def test_an_operation_response_that_is_not_json_is_reported_safely():
    def handler(request):
        return httpx.Response(200, text="<html>secret-value</html>")

    async with gateway(handler, api_key="secret-value") as client_gateway:
        with pytest.raises(ProviderError) as raised:
            await client_gateway.result("operation-1")
    assert str(raised.value) == "Не удалось получить выдачу Яндекса"
