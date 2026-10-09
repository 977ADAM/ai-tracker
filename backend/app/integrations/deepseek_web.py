"""DeepSeek's native search through its Anthropic-compatible Messages API."""

from __future__ import annotations

import asyncio
import json
from typing import Self

import httpx

from app.core.errors import ProviderError
from app.domain.seo_answer import Citation, SearchResult, SeoAnswer, normalize_sources

SEARCH_ENDPOINT = "https://api.deepseek.com/anthropic/v1/messages"
TOTAL_TIMEOUT = 120.0
INVALID_ANSWER = "Некорректный ответ API поиска DeepSeek"
SEARCH_FAILED = "DeepSeek не выполнил веб-поиск или поиск завершился ошибкой"
INCOMPLETE_ANSWER = "DeepSeek не завершил ответ с веб-поиском"
TIMEOUT_ERROR = "Превышено время ожидания ответа DeepSeek"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class DeepSeekWebClient:
    def __init__(self, api_key: str, model: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.transport = transport

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Each answer closes its own HTTP client before returning."""

    def answer(self, prompt: str) -> SeoAnswer:
        # SEO calls this synchronous contract in a worker thread. A per-call
        # client avoids sharing connection pools across those threads/loops.
        return asyncio.run(self._answer(prompt))

    async def _answer(self, prompt: str) -> SeoAnswer:
        body = {
            "model": self.model, "max_tokens": 4096,
            "messages": [{"role": "user", "content": [{"type": "text", "text": (
                "Выполни веб-поиск по следующему запросу и ответь на него, цитируя использованные "
                "источники. Не добавляй заранее заданные бренды в запрос.\n\n" + prompt
            )}]}],
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}],
        }
        try:
            async with asyncio.timeout(TOTAL_TIMEOUT), httpx.AsyncClient(
                transport=self.transport, follow_redirects=False, timeout=TOTAL_TIMEOUT,
            ) as client, client.stream("POST", SEARCH_ENDPOINT, headers={
                "x-api-key": self.api_key, "Authorization": f"Bearer {self.api_key}",
                "anthropic-version": "2023-06-01", "Accept": "application/json",
            }, json=body) as response:
                self._check_status(response.status_code)
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE_BYTES:
                        raise ProviderError(INVALID_ANSWER)
                return parse_search_answer(json.loads(data), self.model)
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ProviderError(TIMEOUT_ERROR) from exc
        except httpx.RequestError as exc:
            raise ProviderError("Не удалось установить соединение с API поиска DeepSeek") from exc
        except (ValueError, UnicodeError) as exc:
            raise ProviderError(INVALID_ANSWER) from exc

    @staticmethod
    def _check_status(status: int) -> None:
        if status in (401, 403):
            raise ProviderError("Ошибка авторизации: проверьте ключ API DeepSeek")
        if status == 429:
            raise ProviderError("Превышен лимит запросов API DeepSeek")
        if status == 400:
            raise ProviderError("DeepSeek отклонил запрос: проверьте поддержку веб-поиска выбранной моделью")
        if not 200 <= status < 300:
            raise ProviderError("Сервис поиска DeepSeek временно недоступен")


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def parse_search_answer(payload: object, requested_model: str) -> SeoAnswer:
    """Keep text, searched pages and actual structured citations separate."""
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
        raise ProviderError(INVALID_ANSWER)
    if payload.get("stop_reason") != "end_turn":
        raise ProviderError(INCOMPLETE_ANSWER)
    texts: list[str] = []
    results: list[SearchResult] = []
    citations: list[Citation] = []
    search_completed = False
    search_ids: set[str] = set()
    for block in payload["content"]:
        if not isinstance(block, dict):
            raise ProviderError(INVALID_ANSWER)
        kind = block.get("type")
        if kind == "server_tool_use" and block.get("name") == "web_search":
            identifier = block.get("id")
            if isinstance(identifier, str):
                search_ids.add(identifier)
        elif kind == "web_search_tool_result":
            items = block.get("content")
            if not isinstance(items, list):
                raise ProviderError(SEARCH_FAILED)
            search_completed = True
            for item in items:
                if not isinstance(item, dict) or item.get("type") != "web_search_result" or not isinstance(item.get("url"), str):
                    raise ProviderError(INVALID_ANSWER)
                results.append(SearchResult(item["url"], _optional_text(item.get("title"))))
        elif kind == "text":
            text = block.get("text")
            if not isinstance(text, str):
                raise ProviderError(INVALID_ANSWER)
            block_index = len(texts)
            texts.append(text)
            refs = block.get("citations") or []
            if not isinstance(refs, list):
                raise ProviderError(INVALID_ANSWER)
            for ref in refs:
                if not isinstance(ref, dict) or not isinstance(ref.get("url"), str):
                    raise ProviderError(INVALID_ANSWER)
                citations.append(Citation(ref["url"], _optional_text(ref.get("title")),
                                          _optional_text(ref.get("cited_text")), block_index, len(citations) + 1))
    if not search_completed:
        raise ProviderError(SEARCH_FAILED)
    text = "\n\n".join(texts)
    if not text.strip():
        raise ProviderError(INVALID_ANSWER)
    pages, refs = normalize_sources(results, citations)
    return SeoAnswer(text, "deepseek_web", "completed", pages, refs,
                     _optional_text(payload.get("model")) or requested_model,
                     len(search_ids) if search_ids else None)
