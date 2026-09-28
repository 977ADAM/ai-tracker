"""Adapter for the OpenAI-compatible Chat Completions API of the SEO service LLM.

The request and the error mapping mirror `integrations.openai_chat`, but the
client is asynchronous and reuses a shared `httpx.AsyncClient` owned by the app.
"""

from __future__ import annotations

import httpx

from app.core.errors import ProviderError

CONNECT_TIMEOUT = 20.0
READ_TIMEOUT = 60.0
REQUEST_TIMEOUT = httpx.Timeout(
    connect=CONNECT_TIMEOUT,
    read=READ_TIMEOUT,
    write=CONNECT_TIMEOUT,
    pool=CONNECT_TIMEOUT,
)

AUTHORIZATION_ERROR = "Ошибка авторизации: проверьте ключ API"
RATE_LIMIT_ERROR = "Превышен лимит запросов API. Повторите позже"
UNAVAILABLE_ERROR = "Сервис модели временно недоступен"
CONNECTION_ERROR = "Не удалось установить соединение с API модели"
PAYLOAD_ERROR = "Некорректный ответ API модели"


class SeoLlmClient:
    """Sends one system and one user message and returns the assistant text."""

    def __init__(self, endpoint: str, api_key: str, model: str, client: httpx.AsyncClient) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.client = client

    async def complete(self, system: str, user: str) -> str:
        body: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            response = await self.client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
                json=body,
                timeout=REQUEST_TIMEOUT,
                follow_redirects=False,
            )
        except httpx.RequestError as exc:
            raise ProviderError(CONNECTION_ERROR) from exc

        self._check_status(response)
        try:
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty answer")
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise ProviderError(PAYLOAD_ERROR) from exc
        return content

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            raise ProviderError(AUTHORIZATION_ERROR)
        if response.status_code == 429:
            raise ProviderError(RATE_LIMIT_ERROR)
        if not 200 <= response.status_code < 300:
            raise ProviderError(UNAVAILABLE_ERROR)
