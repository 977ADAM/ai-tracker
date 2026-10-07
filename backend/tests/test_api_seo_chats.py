"""HTTP contract for the chat: create, list, read, write, and delete.

Every collaborator is a fake injected through the container: the chat's model is
a `FakeChatClient` scripted with canned JSON, and `SeoService` is a
`FakeChatSeoService`, so the suite proves the routes, the strict schemas, and
"no test spends a paid call" without ever reaching a paid API.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import build_container
from app.db.chat import ChatRepository
from app.domain.chat import DEFAULT_TITLE
from app.domain.chat_prompts import NO_ACTIVE_PROPOSAL
from app.service.chat import ChatService
from app.service.connections import ConnectionService
from app.service.form import FormService
from tests.fakes import FakeChatClient, FakeChatSeoService

EMPTY_ANSWER = '{"reply": "", "intent": "message"}'
CONFIRM_ANSWER = '{"reply": "Запускаю", "intent": "confirm"}'
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
ANSWERS = (FULL_ANSWER, CONFIRM_ANSWER, EMPTY_ANSWER)
# The fake key makes the "no response carries a secret" tests mean something.
API_KEY = "sk-chat-secret"
SUMMARY_FIELDS = {"id", "title", "updated_at", "running"}
MESSAGE_FIELDS = {"id", "seq", "role", "kind", "text", "payload", "created_at"}


def _user_version(path: Path) -> int:
    with sqlite3.connect(path) as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


def test_container_starts_twice_over_the_migrated_file(settings, secrets):
    build_container(settings, secrets=secrets).chats.initialize()
    build_container(settings, secrets=secrets)  # второй старт не должен падать
    assert _user_version(settings.config_dir / "runs.sqlite3") == 5


@pytest.fixture
def chat_service(settings, repository) -> ChatService:
    """One chat service over the test doubles, with a model that never dials out.

    The client is built once and shared by every turn, exactly like a real
    dialogue: `FakeChatClient` takes the next scripted answer per call and keeps
    the last one afterwards.
    """
    connections = ConnectionService(repository, settings)
    connections.save({"api_key": API_KEY}, "openai")
    connections.save({"api_key": f"{API_KEY}-second"}, "deepseek")
    chats = ChatRepository(settings.config_dir)
    chats.initialize()
    client = FakeChatClient(ANSWERS)
    return ChatService(
        chats, FakeChatSeoService(), connections, FormService(connections),
        client_factory=lambda: client,
    )


@pytest.fixture
def client(make_client, chat_service: ChatService) -> TestClient:
    """The app over the container that holds the fake chat service."""
    return make_client(
        chats=chat_service.chats,
        chat_service=chat_service,
        seo_service=chat_service.seo,
    )


@pytest.fixture
def chat_id(client: TestClient) -> str:
    return client.post("/api/seo/chats", json={}).json()["chat"]["id"]


def test_create_and_read_a_chat(client):
    created = client.post("/api/seo/chats", json={})
    assert created.status_code == 201
    chat_id = created.json()["chat"]["id"]
    detail = client.get(f"/api/seo/chats/{chat_id}")
    assert detail.status_code == 200
    assert detail.json()["messages"] == []
    assert client.get("/api/seo/chats").json()["items"][0]["id"] == chat_id


def test_a_created_chat_carries_exactly_the_summary_fields(client, chat_id):
    listed = client.get("/api/seo/chats").json()

    assert set(listed) == {"items"}
    assert set(listed["items"][0]) == SUMMARY_FIELDS
    assert listed["items"][0]["title"] == DEFAULT_TITLE
    assert listed["items"][0]["running"] is False


def test_message_rejects_empty_and_too_long_text(client, chat_id):
    assert client.post(f"/api/seo/chats/{chat_id}/messages", json={"text": "  "}).status_code == 400
    too_long = {"text": "я" * 4001}
    assert client.post(f"/api/seo/chats/{chat_id}/messages", json=too_long).status_code == 400


def test_message_rejects_an_unknown_field(client, chat_id):
    response = client.post(f"/api/seo/chats/{chat_id}/messages", json={"text": "привет", "url": "x"})
    assert response.status_code == 400


def test_message_rejects_a_missing_body(client, chat_id):
    assert client.post(f"/api/seo/chats/{chat_id}/messages").status_code == 400


def test_dialogue_reaches_a_proposal_and_a_run(client, chat_id):
    client.post(f"/api/seo/chats/{chat_id}/messages", json={"text": FULL_MESSAGE})
    proposal = client.post(f"/api/seo/chats/{chat_id}/messages", json={"text": "да"}).json()
    kinds = [item["kind"] for item in proposal["messages"]]
    assert kinds == ["text", "run"]


def test_a_message_carries_exactly_the_documented_fields(client, chat_id):
    body = client.post(f"/api/seo/chats/{chat_id}/messages", json={"text": FULL_MESSAGE}).json()

    assert set(body) == {"chat", "messages"}
    assert [item["seq"] for item in body["messages"]] == [1, 2, 3]
    user = body["messages"][0]
    assert set(user) == MESSAGE_FIELDS
    assert (user["role"], user["kind"], user["text"], user["payload"]) == (
        "user", "text", FULL_MESSAGE, None,
    )
    proposal = body["messages"][-1]
    assert set(proposal) == MESSAGE_FIELDS
    assert (proposal["role"], proposal["kind"]) == ("assistant", "proposal")
    assert set(proposal["payload"]) == {
        "status", "url", "sphere", "seeds", "services", "connection_ids",
        "search_upper", "model_upper", "generated_limit",
    }


def test_the_first_message_sets_the_title(client, chat_id):
    client.post(f"/api/seo/chats/{chat_id}/messages", json={"text": FULL_MESSAGE})

    items = client.get("/api/seo/chats").json()["items"]
    assert items[0]["title"] == FULL_MESSAGE[:80]


def test_an_older_page_is_read_by_seq(client, chat_id):
    client.post(f"/api/seo/chats/{chat_id}/messages", json={"text": FULL_MESSAGE})

    full = client.get(f"/api/seo/chats/{chat_id}").json()
    assert set(full) == {"chat", "messages", "next_cursor"}
    assert [item["seq"] for item in full["messages"]] == [1, 2, 3]
    assert full["next_cursor"] is None

    older = client.get(f"/api/seo/chats/{chat_id}", params={"before": 2}).json()
    assert [item["seq"] for item in older["messages"]] == [1, 2]


def test_a_non_numeric_before_is_rejected_as_400(client, chat_id):
    response = client.get(f"/api/seo/chats/{chat_id}", params={"before": "вчера"})

    assert response.status_code == 400
    assert response.json() == {"detail": "Некорректное поле «before»"}


def test_the_list_reports_a_running_chat(client, chat_id):
    client.post(f"/api/seo/chats/{chat_id}/messages", json={"text": FULL_MESSAGE})
    client.post(f"/api/seo/chats/{chat_id}/messages", json={"text": "да"})

    assert client.get("/api/seo/chats").json()["items"][0]["running"] is True


def test_proposal_connections_can_be_replaced(client, chat_id):
    posted = client.post(f"/api/seo/chats/{chat_id}/messages", json={"text": FULL_MESSAGE}).json()
    assert posted["messages"][-1]["payload"]["connection_ids"] == ["openai"]

    response = client.put(f"/api/seo/chats/{chat_id}/proposal", json={"connection_ids": ["deepseek"]})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"chat", "message"}
    assert body["message"]["payload"]["connection_ids"] == ["deepseek"]
    assert body["message"]["payload"]["status"] == "pending"
    assert set(body["chat"]) == SUMMARY_FIELDS


def test_proposal_rejects_an_unknown_connection(client, chat_id):
    client.post(f"/api/seo/chats/{chat_id}/messages", json={"text": FULL_MESSAGE})

    response = client.put(f"/api/seo/chats/{chat_id}/proposal", json={"connection_ids": ["нет-такого"]})

    assert response.status_code == 400


def test_proposal_without_an_open_proposal_is_a_conflict(client, chat_id):
    response = client.put(f"/api/seo/chats/{chat_id}/proposal", json={"connection_ids": ["openai"]})

    assert response.status_code == 409
    assert response.json() == {"detail": NO_ACTIVE_PROPOSAL}


def test_unknown_chat_is_not_found(client):
    assert client.get("/api/seo/chats/нет").status_code == 404


def test_delete_conflicts_while_a_run_is_active(client, chat_id):
    client.post(f"/api/seo/chats/{chat_id}/messages", json={"text": FULL_MESSAGE})
    client.post(f"/api/seo/chats/{chat_id}/messages", json={"text": "да"})
    assert client.delete(f"/api/seo/chats/{chat_id}").status_code == 409


def test_delete_removes_the_chat_and_its_feed(client, chat_id):
    client.post(f"/api/seo/chats/{chat_id}/messages", json={"text": "привет"})

    assert client.delete(f"/api/seo/chats/{chat_id}").status_code == 204
    assert client.get("/api/seo/chats").json()["items"] == []
    assert client.get(f"/api/seo/chats/{chat_id}").status_code == 404


def test_answers_never_contain_keys(client, chat_id):
    body = client.get(f"/api/seo/chats/{chat_id}").text
    assert "api_key" not in body and "sk-" not in body


def test_no_chat_response_ever_carries_the_configured_key(client, chat_id):
    client.post(f"/api/seo/chats/{chat_id}/messages", json={"text": FULL_MESSAGE})

    bodies = [
        client.get("/api/seo/chats").text,
        client.get(f"/api/seo/chats/{chat_id}").text,
        client.post(f"/api/seo/chats/{chat_id}/messages", json={"text": "да"}).text,
    ]

    assert all(API_KEY not in body and "api_key" not in body for body in bodies)
