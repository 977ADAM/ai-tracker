"""Adapter for the deferred Yandex Search API v2.

Deferred work can take from minutes to hours, so `submit` only starts an
operation and returns its ID; `result` reports whether that operation is
finished yet. Every failure becomes a fixed Russian message: upstream bodies may
carry the API key, so they never reach an exception or a log.
"""

from __future__ import annotations

import base64
import re
import xml.etree.ElementTree as ET

import httpx

from app.core.errors import ProviderError
from app.domain.search import TOP_RESULTS, SearchDocument

SEARCH_ASYNC_URL = "https://searchapi.api.cloud.yandex.net/v2/web/searchAsync"
OPERATIONS_URL = "https://operation.api.cloud.yandex.net/operations"

SEARCH_TYPE = "SEARCH_TYPE_RU"
RESPONSE_FORMAT = "FORMAT_XML"
GROUP_SPEC = {"groupMode": "GROUP_MODE_FLAT", "groupsOnPage": str(TOP_RESULTS), "docsInGroup": "1"}

CONNECT_TIMEOUT = 20
READ_TIMEOUT = 60

OPERATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

SUBMIT_FAILED = "Не удалось отправить запрос в Яндекс"
RESULT_FAILED = "Не удалось получить выдачу Яндекса"
OPERATION_FAILED = "Поиск Яндекса завершился ошибкой"
INVALID_OPERATION_ID = "Некорректный идентификатор операции Яндекса"


def safe_operation_id(value: object) -> str:
    """Return the operation ID when it is a safe path token, otherwise refuse it."""
    if not isinstance(value, str) or OPERATION_ID_PATTERN.fullmatch(value) is None:
        raise ProviderError(INVALID_OPERATION_ID)
    return value


def decode_raw_data(value: object) -> bytes:
    """Decode the Base64 `rawData` of a finished operation."""
    if not isinstance(value, str) or not value.strip():
        raise ProviderError(RESULT_FAILED)
    try:
        return base64.b64decode(value.strip(), validate=True)
    except ValueError as exc:
        raise ProviderError(RESULT_FAILED) from exc


def parse_documents(raw: bytes) -> tuple[SearchDocument, ...]:
    """Extract the first-page documents in order; an error document is a failure.

    Each document keeps its ``<url>`` and its ``<title>``; a document without a
    title element stores an empty string instead of a hostname or a guess.
    """
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ProviderError(RESULT_FAILED) from exc
    if root.find(".//error") is not None:
        raise ProviderError(OPERATION_FAILED)
    documents = []
    for element in root.iter("doc"):
        url = element.findtext("url")
        if not isinstance(url, str) or not url.strip():
            raise ProviderError(RESULT_FAILED)
        title = element.findtext("title")
        documents.append(
            SearchDocument(url=url.strip(), title=title.strip() if isinstance(title, str) else "")
        )
    return tuple(documents[:TOP_RESULTS])


class YandexSearchGateway:
    """The `SearchGateway` port over `/v2/web/searchAsync` and the Operation API."""

    def __init__(self, api_key: str, folder_id: str, client: httpx.AsyncClient) -> None:
        self.folder_id = folder_id
        self.client = client
        self.headers = {"Authorization": f"Api-Key {api_key}", "Content-Type": "application/json"}

    async def submit(self, prompt: str, region: int) -> str:
        """Start one deferred search and return its operation ID."""
        body = {
            "query": {"searchType": SEARCH_TYPE, "queryText": prompt, "page": 0},
            "folderId": self.folder_id,
            "responseFormat": RESPONSE_FORMAT,
            "region": str(region),
            "groupSpec": dict(GROUP_SPEC),
        }
        try:
            response = await self.client.post(SEARCH_ASYNC_URL, headers=self.headers, json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(SUBMIT_FAILED) from exc
        if response.status_code != 200:
            raise ProviderError(SUBMIT_FAILED)
        try:
            payload = response.json()
            operation_id = payload["id"]
        except (ValueError, TypeError, KeyError) as exc:
            raise ProviderError(SUBMIT_FAILED) from exc
        return safe_operation_id(operation_id)

    async def result(self, operation_id: str) -> tuple[SearchDocument, ...] | None:
        """Return the ordered documents, or None while the operation is still running."""
        url = f"{OPERATIONS_URL}/{safe_operation_id(operation_id)}"
        try:
            response = await self.client.get(url, headers=self.headers)
        except httpx.HTTPError as exc:
            raise ProviderError(RESULT_FAILED) from exc
        if response.status_code != 200:
            raise ProviderError(RESULT_FAILED)
        try:
            operation = response.json()
        except ValueError as exc:
            raise ProviderError(RESULT_FAILED) from exc
        if not isinstance(operation, dict):
            raise ProviderError(RESULT_FAILED)
        if not operation.get("done"):
            return None
        if operation.get("error"):
            raise ProviderError(OPERATION_FAILED)
        raw = operation.get("response")
        raw_data = raw.get("rawData") if isinstance(raw, dict) else None
        return parse_documents(decode_raw_data(raw_data))
