"""Adapter for bearer-token Chat Completions APIs."""

from __future__ import annotations

import httpx

from app.core.errors import ProviderError

CONNECT_TIMEOUT = 20
READ_TIMEOUT = 60


class OpenAIChatClient:
    """Sends one user message and returns the assistant text."""

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        model: str,
        *,
        thinking_disabled: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.model = model
        self.thinking_disabled = thinking_disabled
        self.http = httpx.Client(
            transport=transport,
            follow_redirects=False,
            timeout=httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=CONNECT_TIMEOUT, pool=CONNECT_TIMEOUT),
        )

    def answer(self, prompt: str) -> str:
        body: dict[str, object] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self.thinking_disabled:
            body["thinking"] = {"type": "disabled"}
        try:
            response = self.http.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
                json=body,
            )
        except httpx.RequestError as exc:
            raise ProviderError("Не удалось установить соединение с API модели") from exc

        self._check_status(response)
        try:
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty answer")
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise ProviderError("Некорректный ответ API модели") from exc
        return content

    def close(self) -> None:
        self.http.close()

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            raise ProviderError("Ошибка авторизации: проверьте ключ API")
        if response.status_code == 429:
            raise ProviderError("Превышен лимит запросов API. Повторите позже")
        if not 200 <= response.status_code < 300:
            raise ProviderError("Сервис модели временно недоступен")
