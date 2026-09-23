"""Small client for the official GigaChat API."""

import time
from uuid import uuid4

import httpx


AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL = "https://api.giga.chat/v1/chat/completions"


class ProviderError(Exception):
    """A safe error message intended for the app user."""


class GigaChatClient:
    def __init__(
        self,
        auth_key: str,
        scope: str,
        model: str = "GigaChat",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.auth_key = auth_key
        self.scope = scope
        self.model = model
        self.http = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(connect=20, read=60, write=20, pool=20),
        )
        self._token: str | None = None
        self._token_expiry = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token

        try:
            response = self.http.post(
                AUTH_URL,
                headers={
                    "Authorization": f"Basic {self.auth_key}",
                    "RqUID": str(uuid4()),
                    "Accept": "application/json",
                },
                data={"scope": self.scope},
            )
        except httpx.RequestError as exc:
            raise ProviderError("Не удалось установить соединение с GigaChat") from exc
        self._check_status(response)
        try:
            body = response.json()
            token = body["access_token"]
            expiry = float(body["expires_at"])
            if expiry > 10_000_000_000:
                expiry /= 1000
            if not isinstance(token, str) or not token:
                raise ValueError("empty token")
        except (ValueError, TypeError, KeyError) as exc:
            raise ProviderError("Некорректный ответ авторизации GigaChat") from exc
        self._token = token
        self._token_expiry = expiry
        return token

    def answer(self, prompt: str) -> str:
        token = self._access_token()
        try:
            response = self.http.post(
                CHAT_URL,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        except httpx.RequestError as exc:
            raise ProviderError("Не удалось установить соединение с GigaChat") from exc
        self._check_status(response)
        try:
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty answer")
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise ProviderError("Некорректный ответ GigaChat") from exc
        return content

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            raise ProviderError("Ошибка авторизации GigaChat. Проверьте ключ и scope")
        if response.status_code == 429:
            raise ProviderError("Превышен лимит запросов GigaChat. Повторите позже")
        if response.status_code >= 400:
            raise ProviderError("Сервис GigaChat временно недоступен")
