"""Public service-LLM settings and the live availability probe.

The public projection never contains the API key: it returns the resolved
endpoint, the model, ``has_api_key``, and the per-field source. The stored key
is used only by `build_client`, which returns the adapter the SEO orchestrator
calls, or `None` while endpoint, model, or key is missing.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from app.core.errors import AppError, ConfigurationError
from app.db.seo_settings import SeoSettingsRepository
from app.domain.seo_settings import SeoSettings
from app.integrations.seo_llm import SeoLlmClient

NOT_CONFIGURED = "Не настроена служебная LLM для SEO-анализа"
TEST_SYSTEM = "Проверка соединения. Отвечай ровно одним словом."
TEST_USER = "Ответь словом OK."


class SeoSettingsService:
    """Resolve, partially update, reset, and probe the service LLM settings."""

    def __init__(self, repository: SeoSettingsRepository, client: httpx.AsyncClient) -> None:
        self.repository = repository
        self.client = client

    def public(self) -> dict[str, object]:
        """Return the safe settings projection; the key is never included."""
        return self._public(self.repository.load())

    def update(self, payload: Mapping[str, object]) -> dict[str, object]:
        """Apply a partial update; absent fields keep their saved values."""
        return self._public(self.repository.update(payload))

    def reset_credentials(self) -> dict[str, object]:
        """Delete the stored key and the UI overrides, keeping the env fallbacks."""
        return self._public(self.repository.reset_credentials())

    async def test(self) -> dict[str, object]:
        """Make one real chat call and report only a safe result.

        A missing configuration is a safe `ConfigurationError`; a failed call
        returns the adapter's fixed message, never a key or an upstream body.
        """
        client = self.build_client()
        if client is None:
            raise ConfigurationError(NOT_CONFIGURED)
        try:
            await client.complete(TEST_SYSTEM, TEST_USER)
        except AppError as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True, "model": client.model}

    def build_client(self) -> SeoLlmClient | None:
        """Build the chat client over the shared HTTP client, or `None` if unset."""
        settings = self.repository.load()
        if not settings.configured or settings.api_key is None:
            return None
        return SeoLlmClient(settings.endpoint, settings.api_key, settings.model, self.client)

    @staticmethod
    def _public(settings: SeoSettings) -> dict[str, object]:
        return {
            "endpoint": settings.endpoint or None,
            "model": settings.model or None,
            "has_api_key": settings.has_api_key,
            "endpoint_source": settings.endpoint_source,
            "model_source": settings.model_source,
            "api_key_source": settings.api_key_source,
        }
