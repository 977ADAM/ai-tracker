"""Endpoint rules for user-added connections.

This is a guardrail for a local single-user app, not a complete SSRF defense.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from app.core.errors import ValidationError
from app.domain.limits import MAX_ENDPOINT_LENGTH

BLOCKED_SUFFIXES = (".local", ".internal", ".localhost", ".test", ".invalid")
BLOCKED_HOSTS = frozenset({"localhost", "local"})
REQUIRED_PATH_SUFFIX = "/chat/completions"


def validate_endpoint(value: object) -> str:
    """Return a safe public HTTPS Chat Completions URL or raise ValidationError."""
    if not isinstance(value, str) or len(value) > MAX_ENDPOINT_LENGTH:
        raise ValidationError("Укажите HTTPS-адрес Chat Completions API")
    try:
        url = urlsplit(value)
        hostname = url.hostname
        port = url.port
    except ValueError as exc:
        raise ValidationError("Некорректный адрес API") from exc
    if (
        url.scheme != "https"
        or not hostname
        or port is not None
        or url.username
        or url.password
        or url.query
        or url.fragment
        or not url.path.endswith(REQUIRED_PATH_SUFFIX)
        or "//" in url.path
        or "\\" in value
        or any(character.isspace() for character in value)
    ):
        raise ValidationError("Нужен публичный HTTPS-адрес, заканчивающийся на /chat/completions")

    host = hostname.rstrip(".").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValidationError("IP-адрес нельзя использовать для подключения")

    labels = host.split(".")
    if (
        len(labels) < 2
        or any(
            not label
            or not all(character.isascii() and (character.isalnum() or character == "-") for character in label)
            or label.startswith("-")
            or label.endswith("-")
            for label in labels
        )
        or host.endswith(BLOCKED_SUFFIXES)
        or host in BLOCKED_HOSTS
        or url.netloc.endswith(".")
    ):
        raise ValidationError("Укажите публичный домен API")
    return value
