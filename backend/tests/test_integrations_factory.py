"""Choosing an adapter from a saved connection."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.domain.models import Connection
from app.integrations.factory import build_provider
from app.integrations.gigachat import GigaChatClient
from app.integrations.openai_chat import OpenAIChatClient

SETTINGS = Settings(default_scope="GIGACHAT_API_B2B")


def test_gigachat_kind_uses_the_connection_scope():
    connection = Connection(id="g", name="GigaChat", kind="gigachat", model="GigaChat", scope="GIGACHAT_API_CORP")
    provider = build_provider(connection, "key", SETTINGS)
    assert isinstance(provider, GigaChatClient)
    assert provider.scope == "GIGACHAT_API_CORP"
    provider.close()


def test_gigachat_kind_falls_back_to_the_default_scope():
    connection = Connection(id="g", name="GigaChat", kind="gigachat", model="GigaChat")
    provider = build_provider(connection, "key", SETTINGS)
    assert provider.scope == "GIGACHAT_API_B2B"
    provider.close()


def test_openai_kind_uses_the_endpoint_and_model():
    connection = Connection(
        id="d", name="DeepSeek", kind="openai", model="deepseek-flash",
        endpoint="https://api.deepseek.com/chat/completions", thinking_disabled=True,
    )
    provider = build_provider(connection, "key", SETTINGS)
    assert isinstance(provider, OpenAIChatClient)
    assert provider.endpoint == "https://api.deepseek.com/chat/completions"
    assert provider.model == "deepseek-flash"
    assert provider.thinking_disabled is True
    provider.close()


def test_openai_kind_without_an_endpoint_is_rejected():
    connection = Connection(id="d", name="Без адреса", kind="openai", model="m")
    with pytest.raises(ConfigurationError):
        build_provider(connection, "key", SETTINGS)


def test_an_unsupported_kind_is_rejected():
    connection = Connection(id="x", name="Прочее", kind="anthropic", model="m", endpoint="https://api.example.com")
    with pytest.raises(ConfigurationError):
        build_provider(connection, "key", SETTINGS)
