"""Endpoint guardrails for user-added connections."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.domain.endpoints import validate_endpoint


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v1/chat/completions",
        "https://127.0.0.1/v1/chat/completions",
        "https://localhost/v1/chat/completions",
        "https://foo.local/v1/chat/completions",
        "https://intranet/v1/chat/completions",
        "https://u:p@api.example.com/v1/chat/completions",
        "https://api.example.com/v1/chat/completions?x=1",
        "https://api.example.com/v1/chat/completions#x",
        "https://api.example.com/v1/other",
        "https://api.example.com:8443/v1/chat/completions",
    ],
)
def test_rejects_unsafe_endpoint(url):
    with pytest.raises(ValidationError):
        validate_endpoint(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com/v1/chat/completions",
        "https://api.example.com/api/v1/chat/completions",
    ],
)
def test_accepts_chat_endpoint(url):
    assert validate_endpoint(url) == url


@pytest.mark.parametrize("value", [None, 42, "https://api.example.com/v1/chat/completions" + "x" * 2048])
def test_rejects_non_string_or_oversized_endpoint(value):
    with pytest.raises(ValidationError):
        validate_endpoint(value)
