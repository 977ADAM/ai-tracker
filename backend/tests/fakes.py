"""In-memory collaborators and presets shared by the test suite."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from app.core.config import ConnectionPreset
from app.core.errors import ProviderError, StorageError
from app.domain.search import SearchDocument
from app.domain.seo import SeoInput
from app.domain.seo_llm import AgentMessage, AgentTurn, ToolCall, ToolSchema
from app.domain.site_fetch import FetchedPage
from app.integrations.yandex_search import RESULT_FAILED, SUBMIT_FAILED

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


# -- SEO fakes ---------------------------------------------------------------

SEO_MENTION_ANSWER = "«Ромашка» советует оформить заказ на https://example.ru/"
SEO_ABSENT_ANSWER = "Ничего не нашлось по этому запросу"
DEFAULT_SEO_PAGE = FetchedPage(
    url="https://example.ru/", title="Ромашка — букеты и доставка", text="Мы делаем букеты на заказ.",
)
DEFAULT_SEO_DOCUMENTS = (
    SearchDocument("https://rival.ru/page", "Соперник — букеты"),
    SearchDocument("https://example.ru/page", "Ромашка — букеты"),
)


class FakeSiteFetcher:
    """A `SiteFetcher` that returns scripted pages, or raises a scripted error."""

    def __init__(self, pages: Iterable[FetchedPage] | None = None, *, error: BaseException | None = None) -> None:
        self.pages = tuple(pages) if pages is not None else (DEFAULT_SEO_PAGE,)
        self.error = error
        self.hosts: list[str] = []

    async def fetch(self, host: str) -> tuple[FetchedPage, ...]:
        self.hosts.append(host)
        if self.error is not None:
            raise self.error
        return self.pages


class ScriptedSeoLlmClient:
    """A `SeoLlmClient` that answers one scripted response per call.

    A response may be a string or an exception instance, so a test can script
    invalid JSON, a domain error, or a provider failure at an exact stage. A
    run builds its own client, so `calls` may be shared by every client of a
    test to observe all calls of all runs.
    """

    def __init__(
        self,
        responses: Sequence[str | BaseException],
        calls: list[tuple[str, str]] | None = None,
    ) -> None:
        self.responses: list[str | BaseException] = list(responses)
        self.calls: list[tuple[str, str]] = calls if calls is not None else []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if not self.responses:
            raise AssertionError("unexpected service-LLM call")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class ScriptedSeoLlmFactory:
    """Builds one `ScriptedSeoLlmClient` per run over a shared script and call log."""

    def __init__(self, responses: Sequence[str | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def __call__(self) -> ScriptedSeoLlmClient:
        return ScriptedSeoLlmClient(self.responses, calls=self.calls)


class FakeAgentModel:
    """A scripted `AgentModel`: one turn or one error per `step` call.

    It records every dialogue it is asked to answer, including the offered tool
    schemas, so a test can prove what the caller sent without any network call.
    """

    def __init__(self, turn: AgentTurn | None = None, *, error: BaseException | None = None) -> None:
        self.turn = turn if turn is not None else AgentTurn(text="OK", tool_calls=())
        self.error = error
        self.steps: list[tuple[tuple[AgentMessage, ...], tuple[ToolSchema, ...]]] = []
        self.closed = False

    async def step(
        self, messages: Sequence[AgentMessage], tools: Sequence[ToolSchema],
    ) -> AgentTurn:
        self.steps.append((tuple(messages), tuple(tools)))
        if self.error is not None:
            raise self.error
        return self.turn

    async def aclose(self) -> None:
        self.closed = True


def tool_call_turn(
    name: str, arguments: dict[str, object] | None = None, call_id: str = "call_1",
) -> AgentTurn:
    """A turn that calls one tool: the shape a tool-supporting model returns."""
    return AgentTurn(
        text="",
        tool_calls=(ToolCall(id=call_id, name=name, arguments=dict(arguments or {})),),
    )


class ScriptedSeoGateway:
    """A `SearchGateway` that answers each prompt with scripted documents.

    `pending_polls` keeps an operation unfinished for its first N polls,
    `never_finishing` keeps scripted prompts unfinished forever, and the failure
    sets make one submit or one result fail without touching the others.
    """

    def __init__(
        self,
        documents: Sequence[SearchDocument] | Callable[[str], Sequence[SearchDocument]] | None = None,
        *,
        pending_polls: int = 0,
        fail_submits: Iterable[str] = (),
        fail_results: Iterable[str] = (),
        never_finishing: Iterable[str] = (),
        hook: Callable[[str, int], None] | None = None,
    ) -> None:
        self.documents = DEFAULT_SEO_DOCUMENTS if documents is None else documents
        self.pending_polls = pending_polls
        self.fail_submits = set(fail_submits)
        self.fail_results = set(fail_results)
        self.never_finishing = set(never_finishing)
        self.hook = hook
        self.submitted: list[tuple[str, int]] = []
        self.polls: dict[str, int] = {}
        self.operations: dict[str, str] = {}

    async def submit(self, prompt: str, region: int) -> str:
        if self.hook is not None:
            self.hook(prompt, region)
        if prompt in self.fail_submits:
            raise ProviderError(SUBMIT_FAILED)
        operation_id = f"seo-operation-{len(self.submitted) + 1}"
        self.submitted.append((prompt, region))
        self.operations[operation_id] = prompt
        return operation_id

    async def result(self, operation_id: str) -> tuple[SearchDocument, ...] | None:
        prompt = self.operations.get(operation_id, "")
        self.polls[operation_id] = self.polls.get(operation_id, 0) + 1
        if prompt in self.never_finishing or self.polls[operation_id] <= self.pending_polls:
            return None
        if prompt in self.fail_results:
            raise ProviderError(RESULT_FAILED)
        documents = self.documents(prompt) if callable(self.documents) else self.documents
        return tuple(documents)


class SeoProviderSpy:
    """Records the prompts of one SEO connection and answers with fixed text."""

    def __init__(self, connection_id: str, answer: str, error: str | None = None) -> None:
        self.connection_id = connection_id
        self.answer_text = answer
        self.error = error
        self.prompts: list[str] = []
        self.closed = False
        self.hook: Callable[[str, str], None] | None = None

    def answer(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.hook is not None:
            self.hook(self.connection_id, prompt)
        if self.error is not None:
            raise ProviderError(self.error)
        return self.answer_text

    def close(self) -> None:
        self.closed = True


class SeoProviderFactorySpy:
    """Builds one recording SEO provider per connection."""

    def __init__(
        self,
        answers: dict[str, str] | None = None,
        *,
        failing_ids: Iterable[str] = (),
        explode_ids: Iterable[str] = (),
        hook: Callable[[str, str], None] | None = None,
    ) -> None:
        self.answers = dict(answers or {})
        self.failing_ids = set(failing_ids)
        self.explode_ids = set(explode_ids)
        self.hook = hook
        self.keys: list[tuple[str, str]] = []
        self.providers: dict[str, SeoProviderSpy] = {}

    def __call__(self, connection: Any, key: str) -> SeoProviderSpy:
        self.keys.append((connection.id, key))
        if connection.id in self.explode_ids:
            raise OSError("private path or key must not leak")
        error = "Сервис временно недоступен" if connection.id in self.failing_ids else None
        provider = SeoProviderSpy(connection.id, self.answers.get(connection.id, SEO_MENTION_ANSWER), error)
        provider.hook = self.hook
        self.providers[connection.id] = provider
        return provider

    @property
    def calls(self) -> list[tuple[str, str]]:
        """Every `(connection_id, prompt)` pair that reached a provider."""
        return [
            (connection_id, prompt)
            for connection_id, provider in self.providers.items()
            for prompt in provider.prompts
        ]


class StorageFailingSeoRepository:
    """Delegates to a real `SeoRepository` but fails chosen writes.

    The optional `analysis_id` narrows the failure to one analysis, so a test can
    prove that a storage failure stops only that run.
    """

    def __init__(
        self,
        repository: Any,
        *,
        methods: Iterable[str] = (),
        analysis_id: str | None = None,
    ) -> None:
        self._repository = repository
        self.failing_methods = set(methods)
        self.analysis_id = analysis_id

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._repository, name)
        if name not in self.failing_methods or not callable(attribute):
            return attribute

        def failing(*args: Any, **kwargs: Any) -> Any:
            if self.analysis_id is None or (args and args[0] == self.analysis_id):
                raise StorageError("storage unavailable")
            return attribute(*args, **kwargs)

        return failing


# -- the agent runtime seam ---------------------------------------------------


class FakeSeoAgentRuntime:
    """A scripted `SeoAgentRuntime` for the service and API tests.

    One background `run` follows `mode`: `complete` closes the analysis as
    completed, `hold` keeps it running until the service cancels the task, and
    `crash` raises a storage error that must stay inside the task. Every call is
    recorded, so a test can prove what the service delegated without a graph.
    """

    def __init__(self, repository: Any = None, *, mode: str = "complete") -> None:
        self.repository = repository
        self.mode = mode
        self.runs: list[tuple[str, SeoInput]] = []
        self.resumes: list[str] = []
        self.cancels: list[str] = []
        # A held run waits here; the service cancels the task on `close`.
        self.hold = asyncio.Event()

    async def run(self, analysis_id: str, input: SeoInput) -> None:
        self.runs.append((analysis_id, input))
        if self.mode == "complete":
            self.repository.finish_analysis(analysis_id)
        elif self.mode == "crash":
            raise StorageError("storage unavailable")
        elif self.mode == "hold":
            await self.hold.wait()

    async def resume(self, analysis_id: str) -> bool:
        self.resumes.append(analysis_id)
        if self.mode == "complete" and self.repository is not None:
            self.repository.finish_analysis(analysis_id)
        return True

    def cancel(self, analysis_id: str) -> None:
        self.cancels.append(analysis_id)
        if self.repository is not None:
            self.repository.cancel(analysis_id)


class FakeSeoSettingsService:
    """A `SeoSettingsService` stand-in with one scripted agent model.

    `build_agent_model` answers `None` when `model` is `None`, which is exactly
    the "service LLM is not configured" case a run creation must refuse.
    """

    def __init__(self, model: Any = None, *, model_name: str = "seo-model") -> None:
        self.model = model
        self.model_name = model_name
        self.builds = 0

    def build_agent_model(self) -> Any:
        self.builds += 1
        return self.model

    def public(self) -> dict[str, object]:
        return {
            "endpoint": ENDPOINT,
            "model": self.model_name,
            "has_api_key": self.model is not None,
            "endpoint_source": "ui",
            "model_source": "ui",
            "api_key_source": "ui",
        }


def tool_calling_settings(model_name: str = "seo-model") -> FakeSeoSettingsService:
    """Settings whose model answers the tool probe with one tool call."""
    return FakeSeoSettingsService(
        FakeAgentModel(tool_call_turn("check_connection", {"status": "OK"})),
        model_name=model_name,
    )

