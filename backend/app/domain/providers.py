"""The contract every model adapter implements."""

from __future__ import annotations

from typing import Protocol

from app.domain.models import Connection


class AnswerProvider(Protocol):
    """One configured connection, ready to answer prompts."""

    def answer(self, prompt: str) -> str: ...

    def close(self) -> None: ...


class ProviderFactory(Protocol):
    """Builds an adapter from a saved connection and its API key."""

    def __call__(self, connection: Connection, key: str) -> AnswerProvider: ...
