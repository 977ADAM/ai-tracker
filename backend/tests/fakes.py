"""In-memory collaborators and presets shared by the test suite."""

from __future__ import annotations

from typing import Any

from app.core.config import ConnectionPreset
from app.core.errors import ProviderError
from app.domain.search import SearchDocument

MENTION_ANSWER = "Ромашка рекомендует этот вариант"
ABSENT_ANSWER = "Ничего не найдено"
FAILING_PROMPT = "ошибка"

ENDPOINT = "https://api.example.com/v1/chat/completions"

# The app ships no presets, so the tests inject their own to cover the
# built-in-template code paths.
GIGACHAT_PRESET = ConnectionPreset(
    id="gigachat",
    name="GigaChat",
    kind="gigachat",
    model="GigaChat",
    scope="GIGACHAT_API_PERS",
)
DEEPSEEK_PRESET = ConnectionPreset(
    id="deepseek",
    name="DeepSeek",
    kind="openai",
    endpoint="https://api.deepseek.com/chat/completions",
    model="deepseek-flash",
    thinking_disabled=True,
)
TEST_PRESETS = (GIGACHAT_PRESET, DEEPSEEK_PRESET)


class MemorySecrets:
    """A credential store that keeps everything in a dictionary."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.fail = False

    def get_password(self, service: str, username: str) -> str | None:
        if self.fail:
            raise RuntimeError("credential store unavailable")
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        if self.fail:
            raise RuntimeError("credential store unavailable")
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.fail:
            raise RuntimeError("credential store unavailable")
        self.values.pop((service, username), None)


class StrictSecrets(MemorySecrets):
    """Refuses to delete a key that was never saved."""

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.values:
            raise RuntimeError("missing key")
        super().delete_password(service, username)


class ToggleSecrets(MemorySecrets):
    """Works normally until it is switched to refusing every write."""

    def __init__(self) -> None:
        super().__init__()
        self.read_only = False

    def set_password(self, service: str, username: str, password: str) -> None:
        if self.read_only:
            raise RuntimeError("credential store is read-only")
        super().set_password(service, username, password)


class FakeProvider:
    """Mentions the brand on every prompt except the one reserved for failures."""

    def __init__(self, connection_id: str = "stub", answer: str = MENTION_ANSWER) -> None:
        self.connection_id = connection_id
        self.answer_text = answer
        self.prompts: list[str] = []
        self.closed = False

    def answer(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if prompt == FAILING_PROMPT:
            raise ProviderError("Сервис временно недоступен")
        return self.answer_text

    def close(self) -> None:
        self.closed = True


class ProviderFactorySpy:
    """Builds one recording provider per connection and remembers what it saw."""

    def __init__(
        self,
        failing_ids: tuple[str, ...] = (),
        explode_ids: tuple[str, ...] = (),
    ) -> None:
        self.failing_ids = set(failing_ids)
        self.explode_ids = set(explode_ids)
        self.keys: list[tuple[str, str]] = []
        self.prompts: list[tuple[str, str]] = []
        self.providers: dict[str, FakeProvider] = {}

    def __call__(self, connection: Any, key: str) -> FakeProvider:
        self.keys.append((connection.id, key))
        if connection.id in self.explode_ids:
            raise OSError("private path or key must not leak")
        answer = ABSENT_ANSWER if connection.id in self.failing_ids else MENTION_ANSWER
        provider = FakeProvider(connection_id=connection.id, answer=answer)
        self.providers[connection.id] = provider
        original = FakeProvider.answer

        def answer_and_record(prompt: str) -> str:
            self.prompts.append((connection.id, prompt))
            return original(provider, prompt)

        provider.answer = answer_and_record  # type: ignore[method-assign]
        return provider


class FakeSearchGateway:
    """A Yandex search gateway that records pairs and answers without any network.

    `outcome` maps a region ID to `found`, `absent`, or `error`; every other
    region is treated as found. `pending_polls` keeps an operation unfinished for
    its first N polls, so a test can observe a job that is still running.
    """

    def __init__(
        self,
        outcome: dict[int, str] | None = None,
        *,
        pending_polls: int = 0,
        message: str = "Поиск Яндекса завершился ошибкой",
    ) -> None:
        self.outcome = outcome or {}
        self.pending_polls = pending_polls
        self.message = message
        self.submitted: list[tuple[str, int]] = []
        self.polls: dict[str, int] = {}
        self.regions: dict[str, int] = {}

    async def submit(self, prompt: str, region: int) -> str:
        operation_id = f"yandex-operation-{len(self.submitted) + 1}"
        self.submitted.append((prompt, region))
        self.regions[operation_id] = region
        return operation_id

    async def result(self, operation_id: str) -> tuple[SearchDocument, ...] | None:
        self.polls[operation_id] = self.polls.get(operation_id, 0) + 1
        if self.polls[operation_id] <= self.pending_polls:
            return None
        outcome = self.outcome.get(self.regions[operation_id], "found")
        if outcome == "error":
            raise ProviderError(self.message)
        if outcome == "absent":
            return (SearchDocument("https://other.ru/"),)
        return (SearchDocument("https://other.ru/"), SearchDocument("https://example.ru/page"))
