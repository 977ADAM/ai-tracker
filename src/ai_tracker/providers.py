"""Common contract for model answer providers."""

from typing import Protocol


class ProviderError(Exception):
    """A safe provider error message intended for the app user."""


class AnswerProvider(Protocol):
    def answer(self, prompt: str) -> str: ...

    def close(self) -> None: ...
