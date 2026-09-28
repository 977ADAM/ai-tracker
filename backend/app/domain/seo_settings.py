"""Resolved SEO service-LLM settings and their endpoint guardrails.

A remote endpoint must use HTTPS. HTTP and IP literals are allowed only for a
loopback address the user configured locally, so this validator is deliberately
separate from `domain.endpoints.validate_endpoint`, which forbids both.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

from app.core.errors import ValidationError
from app.domain.limits import MAX_ENDPOINT_LENGTH

CredentialSource = Literal["ui", "env", "none"]

REQUIRED_PATH_SUFFIX = "/chat/completions"
LOOPBACK_HOSTS = frozenset({"localhost"})


def validate_seo_endpoint(value: object) -> str:
    """Return a Chat Completions URL that is HTTPS unless it points at loopback."""
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_ENDPOINT_LENGTH:
        raise ValidationError("Укажите адрес Chat Completions API")
    try:
        url = urlsplit(value)
        hostname = url.hostname
        # Reading the port here turns a malformed port into a validation error.
        _port = url.port
    except ValueError as exc:
        raise ValidationError("Некорректный адрес API") from exc
    if (
        url.scheme not in ("http", "https")
        or not hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or not url.path.endswith(REQUIRED_PATH_SUFFIX)
        or "//" in url.path
        or "\\" in value
        or any(character.isspace() for character in value)
    ):
        raise ValidationError("Нужен HTTPS-адрес, заканчивающийся на /chat/completions")

    host = hostname.rstrip(".").lower()
    address = _parse_address(host)
    loopback = host in LOOPBACK_HOSTS or (address is not None and address.is_loopback)
    if not loopback:
        if url.scheme == "http":
            raise ValidationError("HTTP разрешён только для локального адреса")
        if address is not None:
            raise ValidationError("IP-адрес разрешён только для локального адреса")
    return value


def _parse_address(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _value(ui_value: str | None, env_value: str | None) -> tuple[str | None, CredentialSource]:
    if isinstance(ui_value, str) and ui_value.strip():
        return ui_value.strip(), "ui"
    if isinstance(env_value, str) and env_value.strip():
        return env_value.strip(), "env"
    return None, "none"


@dataclass(frozen=True)
class SeoSettings:
    """Effective settings; ``api_key`` is internal and must never be serialized."""

    endpoint: str
    model: str
    api_key: str | None = field(repr=False)
    endpoint_source: CredentialSource
    model_source: CredentialSource
    api_key_source: CredentialSource

    @classmethod
    def resolve(
        cls,
        *,
        ui_endpoint: str | None = None,
        ui_model: str | None = None,
        ui_api_key: str | None = None,
        env_endpoint: str | None = None,
        env_model: str | None = None,
        env_api_key: str | None = None,
    ) -> SeoSettings:
        endpoint, endpoint_source = _value(ui_endpoint, env_endpoint)
        model, model_source = _value(ui_model, env_model)
        api_key, api_key_source = _value(ui_api_key, env_api_key)
        if endpoint is not None:
            validate_seo_endpoint(endpoint)
        return cls(
            endpoint=endpoint or "",
            model=model or "",
            api_key=api_key,
            endpoint_source=endpoint_source,
            model_source=model_source,
            api_key_source=api_key_source,
        )

    @property
    def has_api_key(self) -> bool:
        """Whether the effective key exists, without exposing it."""
        return self.api_key is not None

    @property
    def configured(self) -> bool:
        """All three values a chat call needs are present."""
        return bool(self.endpoint and self.model and self.api_key)
