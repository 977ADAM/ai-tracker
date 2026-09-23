"""Chooses the adapter for a saved connection."""

from __future__ import annotations

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.domain.models import KIND_GIGACHAT, KIND_OPENAI, Connection
from app.domain.providers import AnswerProvider
from app.integrations.gigachat import GigaChatClient
from app.integrations.openai_chat import OpenAIChatClient


def build_provider(connection: Connection, key: str, settings: Settings) -> AnswerProvider:
    """Build the adapter that matches the connection kind."""
    if connection.kind == KIND_GIGACHAT:
        return GigaChatClient(key, connection.scope or settings.default_scope, connection.model)
    if connection.kind == KIND_OPENAI:
        if not connection.endpoint:
            raise ConfigurationError("В подключении не указан адрес API")
        return OpenAIChatClient(
            key,
            connection.endpoint,
            connection.model,
            thinking_disabled=connection.thinking_disabled,
        )
    raise ConfigurationError("Поддерживается только OpenAI-совместимый API")
