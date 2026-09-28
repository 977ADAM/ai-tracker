"""Public service-LLM settings and the live availability probe.

The public projection never contains the API key: it returns the resolved
endpoint, the model, ``has_api_key``, and the per-field source. The stored key
is used only by `build_client` and `build_agent_model`, which return the
adapters the fixed pipeline and the agent runtime call, or `None` while the
endpoint, model, or key is missing.

`test()` makes two real calls: a plain chat completion and a tool probe with one
trivial schema. A model that answers the probe without any tool call does not
support native tool calling, and the run must be refused before it costs money.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import httpx

from app.core.errors import AppError, ConfigurationError
from app.db.seo_settings import SeoSettingsRepository
from app.domain.seo_llm import AgentMessage, AgentModel, AgentTurn, ToolSchema
from app.domain.seo_settings import SeoSettings
from app.integrations.seo_llm import LangChainSeoLlmClient, SeoLlmClient

NOT_CONFIGURED = "Не настроена служебная LLM для SEO-анализа"
TOOLS_UNSUPPORTED = "Модель не поддерживает вызов инструментов"
TEST_SYSTEM = "Проверка соединения. Отвечай ровно одним словом."
TEST_USER = "Ответь словом OK."
TOOL_TEST_SYSTEM = "Проверка вызова инструментов. Вызови инструмент, не отвечай текстом."
TOOL_TEST_USER = "Проверь соединение: вызови инструмент."
TOOL_TEST_SCHEMA = ToolSchema(
    name="check_connection",
    description="Проверяет соединение со служебной LLM",
    parameters={
        "type": "object",
        "properties": {"status": {"type": "string", "description": "Короткий статус"}},
    },
)

AgentModelFactory = Callable[[SeoSettings], AgentModel]


def default_agent_model(settings: SeoSettings) -> AgentModel:
    """Build the tool-calling adapter over freshly resolved settings."""
    return LangChainSeoLlmClient(settings)


class SeoSettingsService:
    """Resolve, partially update, reset, and probe the service LLM settings."""

    def __init__(
        self,
        repository: SeoSettingsRepository,
        client: httpx.AsyncClient,
        *,
        agent_model_factory: AgentModelFactory | None = None,
    ) -> None:
        self.repository = repository
        self.client = client
        self._agent_model_factory = agent_model_factory or default_agent_model

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
        """Probe the model twice and report only a safe result.

        A missing configuration is a safe `ConfigurationError`; a failed probe
        returns the adapter's fixed message, never a key or an upstream body.
        """
        client = self.build_client()
        if client is None:
            raise ConfigurationError(NOT_CONFIGURED)
        try:
            await client.complete(TEST_SYSTEM, TEST_USER)
        except AppError as error:
            return {"ok": False, "error": str(error)}
        try:
            turn = await self._tool_probe()
        except AppError as error:
            return {"ok": False, "error": str(error)}
        if not turn.tool_calls:
            return {"ok": False, "error": TOOLS_UNSUPPORTED}
        return {"ok": True, "model": client.model, "tools": True}

    async def _tool_probe(self) -> AgentTurn:
        """Ask the model to call one trivial tool and close the probe client."""
        model = self.build_agent_model()
        if model is None:
            raise ConfigurationError(NOT_CONFIGURED)
        try:
            return await model.step(
                (
                    AgentMessage(role="system", content=TOOL_TEST_SYSTEM),
                    AgentMessage(role="user", content=TOOL_TEST_USER),
                ),
                (TOOL_TEST_SCHEMA,),
            )
        finally:
            aclose = getattr(model, "aclose", None)
            if callable(aclose):
                await aclose()

    def build_client(self) -> SeoLlmClient | None:
        """Build the chat client over the shared HTTP client, or `None` if unset."""
        settings = self.repository.load()
        if not settings.configured or settings.api_key is None:
            return None
        return SeoLlmClient(settings.endpoint, settings.api_key, settings.model, self.client)

    def build_agent_model(self) -> AgentModel | None:
        """Build the tool-calling adapter, or `None` while settings are incomplete."""
        settings = self.repository.load()
        if not settings.configured or settings.api_key is None:
            return None
        return self._agent_model_factory(settings)

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
