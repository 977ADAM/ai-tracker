"""The chat message scenario: a question, a proposal, and the only paid launch.

Every test scripts the service LLM with canned JSON answers and proves what the
server decided: which question reaches the feed, whether a proposal is pending,
whether the run started, and what a second confirmation can and cannot do. The
run itself is a `FakeChatSeoService`, so no test spends anything.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from app.core.errors import (
    ChatNotFound,
    ConfigurationError,
    ProviderError,
    ValidationError,
)
from app.db.chat import ChatRepository
from app.domain.chat import DEFAULT_TITLE
from app.domain.chat_prompts import (
    NOTHING_TO_RUN,
    PROPOSAL_HINT,
    RUN_IN_PROGRESS,
    question_for,
)
from app.domain.seo import GENERATED_QUERY_LIMIT
from app.domain.seo_llm import LLM_NOT_CONFIGURED
from app.domain.seo_tools import MAX_MODEL_ANSWERS, MAX_SEARCH_REQUESTS
from app.service.chat import ChatService
from app.service.connections import ConnectionService
from app.service.form import FormService
from tests.fakes import FailingChatClient, FakeChatClient, FakeChatSeoService

EMPTY_ANSWER = '{"reply": "", "intent": "message"}'
CONFIRM_ANSWER = '{"reply": "Запускаю", "intent": "confirm"}'
NEW_SPHERE_ANSWER = '{"reply": "Понял", "intent": "confirm", "params": {"sphere": "ремонт квартир"}}'
# The four extracted parameters plus the connection the form defaults to make
# the draft complete: connections are never part of a model answer.
FULL_ANSWER = json.dumps(
    {
        "reply": "Собрал параметры",
        "intent": "message",
        "params": {
            "url": "https://example.ru",
            "sphere": "доставка цветов",
            "seeds": ["букеты москва", "доставка цветов", "цветы с доставкой"],
            "services": ["букеты", "доставка"],
        },
    },
    ensure_ascii=False,
)
FULL_MESSAGE = (
    "Проверь https://example.ru, сфера — доставка цветов, запросы: букеты москва, "
    "доставка цветов, цветы с доставкой, услуги: букеты, доставка"
)
# The brief's queue: an empty reply first, then the full parameters, then the two
# confirmations. It is the script of the "asks one question" test.
ASKING_ANSWERS = (EMPTY_ANSWER, FULL_ANSWER, CONFIRM_ANSWER, NEW_SPHERE_ANSWER)


@pytest.fixture
def chats(tmp_path: Path) -> ChatRepository:
    repository = ChatRepository(tmp_path)
    repository.initialize()
    return repository


@pytest.fixture
def seo() -> FakeChatSeoService:
    return FakeChatSeoService()


@pytest.fixture
def connections(repository, settings) -> ConnectionService:
    service = ConnectionService(repository, settings)
    service.save({"api_key": "test-key"}, "openai")
    return service


@pytest.fixture
def form(connections: ConnectionService) -> FormService:
    return FormService(connections)


@pytest.fixture
def service_factory(
    chats: ChatRepository,
    seo: FakeChatSeoService,
    connections: ConnectionService,
    form: FormService,
) -> Callable[[Sequence[str]], ChatService]:
    """Build one chat service over the shared collaborators and a scripted model."""

    def build(answers: Sequence[str] = (FULL_ANSWER, CONFIRM_ANSWER)) -> ChatService:
        client = FakeChatClient(answers)
        return ChatService(chats, seo, connections, form, client_factory=lambda: client)

    return build


@pytest.fixture
def service(service_factory: Callable[[Sequence[str]], ChatService]) -> ChatService:
    return service_factory()


@pytest.fixture
def changing_service(service_factory: Callable[[Sequence[str]], ChatService]) -> ChatService:
    return service_factory((FULL_ANSWER, NEW_SPHERE_ANSWER))


@pytest.fixture
def asking_service(service_factory: Callable[[Sequence[str]], ChatService]) -> ChatService:
    return service_factory(ASKING_ANSWERS)


@pytest.fixture
def confirm_service(service_factory: Callable[[Sequence[str]], ChatService]) -> ChatService:
    return service_factory((CONFIRM_ANSWER,))


@pytest.fixture
def unconfigured_service(
    chats: ChatRepository,
    seo: FakeChatSeoService,
    connections: ConnectionService,
    form: FormService,
) -> ChatService:
    return ChatService(chats, seo, connections, form, client_factory=lambda: None)


@pytest.fixture
def failing_service(
    chats: ChatRepository,
    seo: FakeChatSeoService,
    connections: ConnectionService,
    form: FormService,
) -> ChatService:
    client = FailingChatClient(ProviderError("Сервис временно недоступен"))
    return ChatService(chats, seo, connections, form, client_factory=lambda: client)


@pytest.fixture
def chat_id(chats: ChatRepository) -> str:
    return chats.create_chat(DEFAULT_TITLE)


@pytest.mark.anyio
async def test_incomplete_message_asks_one_question(asking_service, chat_id):
    result = await asking_service.send_message(chat_id, "хочу узнать про свой сайт")
    kinds = [(item["role"], item["kind"]) for item in result["messages"]]
    assert kinds[0] == ("user", "text")
    assert result["messages"][1]["text"] == question_for("url")


@pytest.mark.anyio
async def test_complete_message_creates_a_pending_proposal(service, chat_id):
    result = await service.send_message(chat_id, FULL_MESSAGE)
    proposal = result["messages"][-1]
    assert proposal["kind"] == "proposal"
    assert proposal["payload"]["status"] == "pending"
    assert proposal["payload"]["url"] == "https://example.ru"
    assert service.chats.chat(chat_id)["pending_proposal_id"] == proposal["id"]


@pytest.mark.anyio
async def test_confirm_after_a_proposal_starts_the_run(service, chat_id, seo):
    await service.send_message(chat_id, FULL_MESSAGE)
    result = await service.send_message(chat_id, "да")
    assert seo.started, "прогон обязан начаться по подтверждению"
    assert [item["kind"] for item in result["messages"]] == ["text", "run"]
    assert result["messages"][-1]["payload"]["analysis_id"] == seo.analysis_id


@pytest.mark.anyio
async def test_confirm_does_not_start_after_the_params_changed(changing_service, chat_id, seo):
    await changing_service.send_message(chat_id, FULL_MESSAGE)
    result = await changing_service.send_message(chat_id, "нет, сфера — ремонт квартир, да")
    assert seo.started == []
    assert result["messages"][-1]["kind"] == "proposal"
    assert result["messages"][-1]["payload"]["sphere"] == "ремонт квартир"
    assert result["messages"][-1]["payload"]["status"] == "pending"


@pytest.mark.anyio
async def test_confirm_without_a_proposal_starts_nothing(confirm_service, chat_id, seo):
    result = await confirm_service.send_message(chat_id, "да")
    assert seo.started == []
    assert result["messages"][-1]["text"] == NOTHING_TO_RUN


@pytest.mark.anyio
async def test_two_messages_do_not_start_two_runs(service, chat_id, seo):
    await service.send_message(chat_id, FULL_MESSAGE)
    await service.send_message(chat_id, "да")
    result = await service.send_message(chat_id, "да")
    assert len(seo.started) == 1
    assert result["messages"][-1]["text"] == RUN_IN_PROGRESS


@pytest.mark.anyio
async def test_a_turn_that_lost_the_proposal_starts_no_run(
    chats: ChatRepository,
    seo: FakeChatSeoService,
    connections: ConnectionService,
    form: FormService,
    chat_id: str,
):
    """A turn that finds the proposal consumed mid-turn refuses instead of paying.

    The model call is the turn's only suspension point before the launch, so a
    concurrent turn can clear the pointer while this one is still being answered;
    the claim then loses and the run must not start.
    """
    await ChatService(
        chats, seo, connections, form, client_factory=lambda: FakeChatClient([FULL_ANSWER]),
    ).send_message(chat_id, FULL_MESSAGE)

    class StealingChatClient:
        """Clears the proposal during the model call, as a winning turn would."""

        async def complete(self, system: str, user: str) -> str:
            chats.set_pending_proposal(chat_id, None)
            return CONFIRM_ANSWER

    service = ChatService(chats, seo, connections, form, client_factory=StealingChatClient)
    result = await service.send_message(chat_id, "да")

    assert seo.started == []
    assert [item["kind"] for item in result["messages"]] == ["text", "text"]
    assert result["messages"][-1]["text"] == RUN_IN_PROGRESS


@pytest.mark.anyio
async def test_overlapping_confirmations_start_exactly_one_run(
    chats: ChatRepository,
    connections: ConnectionService,
    form: FormService,
    chat_id: str,
):
    """Two turns holding the same pending proposal cannot both fund a run.

    The gates build the real race deterministically: the fake model parks both
    turns inside `complete`, so each has read the same pre-launch snapshot of the
    chat, and the fake `seo.start` parks the winner inside its paid start, so the
    loser gets to claim while the winner is still there. One run, one winner.
    """
    await ChatService(
        chats, seo, connections, form, client_factory=lambda: FakeChatClient([FULL_ANSWER]),
    ).send_message(chat_id, FULL_MESSAGE)

    class BothTurnsChatClient:
        """Parks every turn in `complete` until both turns have arrived."""

        def __init__(self) -> None:
            self.calls = 0
            self.both_ready = asyncio.Event()
            self.release = asyncio.Event()

        async def complete(self, system: str, user: str) -> str:
            self.calls += 1
            if self.calls == 2:
                self.both_ready.set()
            await self.release.wait()
            return CONFIRM_ANSWER

    class ParkedStartSeo(FakeChatSeoService):
        """Parks the first paid start until the test lets it finish."""

        def __init__(self) -> None:
            super().__init__()
            self.release = asyncio.Event()

        async def start(self, payload: dict[str, object]) -> dict[str, object]:
            started = await super().start(payload)
            if len(self.started) == 1:
                await self.release.wait()
            return started

    client = BothTurnsChatClient()
    parked_seo = ParkedStartSeo()
    service = ChatService(chats, parked_seo, connections, form, client_factory=lambda: client)

    first = asyncio.create_task(service.send_message(chat_id, "да"))
    second = asyncio.create_task(service.send_message(chat_id, "да"))
    await client.both_ready.wait()
    client.release.set()

    # The winner is parked inside `seo.start`; the loser finishes its turn first.
    _, pending = await asyncio.wait({first, second}, return_when=asyncio.FIRST_COMPLETED)
    assert pending, "the winning turn must still be inside its paid start"
    parked_seo.release.set()
    results = list(await asyncio.gather(first, second))

    kinds = [item["kind"] for result in results for item in result["messages"]]
    answers = [
        item["text"]
        for result in results
        for item in result["messages"]
        if item["kind"] == "text" and item["role"] == "assistant"
    ]
    assert len(parked_seo.started) == 1
    assert kinds.count("run") == 1
    assert answers == [RUN_IN_PROGRESS]
    assert chats.chat(chat_id)["pending_proposal_id"] is None


@pytest.mark.anyio
async def test_first_message_becomes_the_title(service, chat_id):
    await service.send_message(chat_id, "  проверь flowers.ru  ")
    assert service.chats.chat(chat_id)["title"] == "проверь flowers.ru"


@pytest.mark.anyio
async def test_a_later_message_does_not_rename_the_chat(service_factory, chat_id):
    service = service_factory((EMPTY_ANSWER,))
    await service.send_message(chat_id, "проверь flowers.ru")
    await service.send_message(chat_id, "добавь услуги")
    assert service.chats.chat(chat_id)["title"] == "проверь flowers.ru"


@pytest.mark.anyio
async def test_the_next_gap_is_asked_once_the_first_one_is_filled(service_factory, chat_id):
    answer = '{"reply": "", "intent": "message", "params": {"url": "https://example.ru"}}'
    service = service_factory((answer,))
    result = await service.send_message(chat_id, "проверь https://example.ru")
    assert result["messages"][-1]["text"] == question_for("sphere")


@pytest.mark.anyio
async def test_the_model_reply_is_preferred_over_the_fixed_question(service_factory, chat_id):
    service = service_factory(('{"reply": "Какой у вас адрес?", "intent": "message"}',))
    result = await service.send_message(chat_id, "привет")
    assert result["messages"][-1]["text"] == "Какой у вас адрес?"


@pytest.mark.anyio
async def test_an_incomplete_message_resets_the_open_proposal(service_factory, chat_id):
    answer = '{"reply": "", "intent": "message", "params": {"url": "example"}}'
    service = service_factory((FULL_ANSWER, answer))
    proposal = (await service.send_message(chat_id, FULL_MESSAGE))["messages"][-1]
    assert service.chats.chat(chat_id)["pending_proposal_id"] == proposal["id"]
    result = await service.send_message(chat_id, "адрес — example")
    assert service.chats.chat(chat_id)["pending_proposal_id"] is None
    assert service.chats.message(proposal["id"])["payload"]["status"] == "superseded"
    assert result["messages"][-1]["text"] == question_for("url")


@pytest.mark.anyio
async def test_a_new_proposal_supersedes_the_old_one(changing_service, chat_id):
    first = (await changing_service.send_message(chat_id, FULL_MESSAGE))["messages"][-1]
    second = (await changing_service.send_message(chat_id, "сфера — ремонт квартир"))["messages"][-1]
    assert changing_service.chats.message(first["id"])["payload"]["status"] == "superseded"
    assert second["payload"]["status"] == "pending"
    assert changing_service.chats.chat(chat_id)["pending_proposal_id"] == second["id"]


@pytest.mark.anyio
async def test_the_proposal_carries_the_estimate_and_the_default_connections(service, chat_id):
    result = await service.send_message(chat_id, FULL_MESSAGE)
    payload = result["messages"][-1]["payload"]
    assert payload["search_upper"] == MAX_SEARCH_REQUESTS
    assert payload["model_upper"] == MAX_MODEL_ANSWERS
    assert payload["generated_limit"] == GENERATED_QUERY_LIMIT
    assert payload["connection_ids"] == ["openai"]
    assert service.chats.chat(chat_id)["draft"]["connection_ids"] == ["openai"]


@pytest.mark.anyio
async def test_the_proposal_hint_reaches_the_feed(service, chat_id):
    result = await service.send_message(chat_id, FULL_MESSAGE)
    kinds = [item["kind"] for item in result["messages"]]
    assert kinds == ["text", "text", "proposal"]
    assert result["messages"][0]["role"] == "user"
    assert PROPOSAL_HINT in result["messages"][1]["text"]


@pytest.mark.anyio
async def test_a_deleted_run_no_longer_blocks_the_chat(service, chat_id, seo):
    await service.send_message(chat_id, FULL_MESSAGE)
    await service.send_message(chat_id, "да")
    seo.snapshots.clear()
    result = await service.send_message(chat_id, "да")
    assert len(seo.started) == 1
    assert result["messages"][-1]["kind"] == "proposal"
    assert result["messages"][-1]["payload"]["status"] == "pending"


@pytest.mark.anyio
async def test_the_model_never_sees_a_plain_user_message(service, chat_id):
    await service.send_message(chat_id, "проверь flowers.ru")
    system, user = service.client_factory().calls[0]
    assert user.startswith("<<<MESSAGE")
    assert "проверь flowers.ru" in user
    assert "проверь flowers.ru" not in system


def test_reports_the_configured_and_default_connections(service):
    assert service.configured_connection_ids() == ("openai",)
    assert service.default_connection_ids() == ("openai",)


@pytest.mark.anyio
@pytest.mark.parametrize("text", ["   ", "я" * 4001], ids=["blank", "too-long"])
async def test_a_bad_message_is_refused_before_the_model_is_built(unconfigured_service, chat_id, text):
    with pytest.raises(ValidationError):
        await unconfigured_service.send_message(chat_id, text)
    assert unconfigured_service.chats.messages(chat_id)["items"] == []


@pytest.mark.anyio
async def test_an_unconfigured_llm_is_refused_before_the_chat_changes(unconfigured_service, chat_id):
    with pytest.raises(ConfigurationError) as error:
        await unconfigured_service.send_message(chat_id, FULL_MESSAGE)
    assert str(error.value) == LLM_NOT_CONFIGURED
    chat = unconfigured_service.chats.chat(chat_id)
    assert chat["draft"]["url"] == ""
    assert chat["pending_proposal_id"] is None
    assert unconfigured_service.chats.messages(chat_id)["items"] == []


@pytest.mark.anyio
async def test_a_provider_error_is_not_swallowed(failing_service, chat_id):
    with pytest.raises(ProviderError):
        await failing_service.send_message(chat_id, FULL_MESSAGE)
    chat = failing_service.chats.chat(chat_id)
    assert chat["draft"]["url"] == ""
    assert [item["text"] for item in failing_service.chats.messages(chat_id)["items"]] == [FULL_MESSAGE]


@pytest.mark.anyio
async def test_an_unknown_chat_is_not_found(service):
    with pytest.raises(ChatNotFound):
        await service.send_message("нет-такого", "привет")


@pytest.mark.anyio
async def test_a_parse_failure_leaves_the_draft_alone(service_factory, chat_id):
    service = service_factory(('{"reply": "Понял"',))
    with pytest.raises(ValidationError):
        await service.send_message(chat_id, "проверь https://example.ru")
    assert service.chats.chat(chat_id)["draft"]["url"] == ""
