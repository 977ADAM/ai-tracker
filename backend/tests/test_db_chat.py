"""Chat persistence: the version-5 migration, the message feed, and the cursor.

`ChatRepository` is the last owner of the shared `runs.sqlite3`: it adds the two
chat tables and raises `user_version` to 5, while `RunRepository` keeps reading
the legacy run tables of the same file. A database written by a newer
application version is refused without touching it.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.core.errors import ChatNotFound, StorageError
from app.db.chat import ChatRepository
from app.db.runs import RunRepository
from app.db.seo import SeoRepository

DB_FILE = "runs.sqlite3"
CHAT_TABLES = {"seo_chats", "seo_chat_messages"}


def _user_version(config_dir: Path) -> int:
    connection = sqlite3.connect(config_dir / DB_FILE)
    try:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])
    finally:
        connection.close()


def _repository(config_dir: Path) -> ChatRepository:
    repository = ChatRepository(config_dir)
    repository.initialize()
    return repository


def test_initialize_creates_chat_tables(tmp_path):
    repository = ChatRepository(tmp_path)
    repository.initialize()
    chat_id = repository.create_chat("Первый чат")
    assert repository.chat(chat_id)["title"] == "Первый чат"


def test_initialize_raises_version_to_five(tmp_path):
    RunRepository(tmp_path).initialize()
    SeoRepository(tmp_path).initialize()
    ChatRepository(tmp_path).initialize()
    assert _user_version(tmp_path) == 5


def test_messages_keep_sequence_and_cursor(tmp_path):
    repository = _repository(tmp_path)
    chat_id = repository.create_chat("Чат")
    for index in range(3):
        repository.append_message(chat_id, "user", "text", f"текст {index}", None)
    page = repository.messages(chat_id, limit=2)
    assert [item["seq"] for item in page["items"]] == [2, 3]
    assert page["next_cursor"] == 1
    older = repository.messages(chat_id, cursor=page["next_cursor"], limit=2)
    assert [item["seq"] for item in older["items"]] == [1]
    assert older["next_cursor"] is None


def test_unknown_chat_raises(tmp_path):
    with pytest.raises(ChatNotFound):
        _repository(tmp_path).chat("нет-такого")


def test_newer_schema_is_left_alone(tmp_path):
    _repository(tmp_path)  # создаёт файл
    with sqlite3.connect(tmp_path / "runs.sqlite3") as connection:
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(StorageError):
        ChatRepository(tmp_path).initialize()


# -- schema -------------------------------------------------------------


def test_migration_adds_chat_tables_beside_the_run_tables(tmp_path):
    RunRepository(tmp_path).initialize()
    repository = _repository(tmp_path)
    connection = sqlite3.connect(tmp_path / DB_FILE)
    try:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        connection.close()
    assert CHAT_TABLES <= names
    assert {"runs", "model_rows", "search_rows"} <= names
    assert repository.list_chats() == ()


def test_a_new_chat_starts_with_an_empty_draft(tmp_path):
    repository = _repository(tmp_path)
    chat_id = repository.create_chat("Новый чат")
    stored = repository.chat(chat_id)
    assert stored["draft"]["url"] == ""
    assert stored["pending_proposal_id"] is None
    assert stored["active_analysis_id"] is None
    assert stored["created_at"] == stored["updated_at"]


# -- chats --------------------------------------------------------------


def test_set_title_replaces_the_chat_title(tmp_path):
    repository = _repository(tmp_path)
    chat_id = repository.create_chat("Новый чат")
    repository.set_title(chat_id, "Проверь flowers.ru")
    assert repository.chat(chat_id)["title"] == "Проверь flowers.ru"


def test_set_title_refuses_an_unknown_chat(tmp_path):
    with pytest.raises(ChatNotFound):
        _repository(tmp_path).set_title("нет-такого", "Заголовок")


def test_list_chats_is_newest_updated_first(tmp_path):
    repository = _repository(tmp_path)
    first = repository.create_chat("Первый")
    second = repository.create_chat("Второй")
    assert [item["id"] for item in repository.list_chats()] == [second, first]
    repository.save_draft(first, {"url": "https://example.ru"})
    assert [item["id"] for item in repository.list_chats()] == [first, second]


def test_list_chats_honours_the_limit(tmp_path):
    repository = _repository(tmp_path)
    for index in range(3):
        repository.create_chat(f"Чат {index}")
    assert len(repository.list_chats(limit=2)) == 2
    assert repository.list_chats(limit=0) == ()


def test_delete_chat_removes_its_messages(tmp_path):
    repository = _repository(tmp_path)
    chat_id = repository.create_chat("Чат")
    keep_id = repository.create_chat("Другой")
    repository.append_message(chat_id, "user", "text", "привет", None)
    repository.delete_chat(chat_id)
    with pytest.raises(ChatNotFound):
        repository.chat(chat_id)
    with pytest.raises(ChatNotFound):
        repository.messages(chat_id)
    assert repository.chat(keep_id)["title"] == "Другой"
    connection = sqlite3.connect(tmp_path / DB_FILE)
    try:
        left = connection.execute(
            "SELECT count(*) FROM seo_chat_messages WHERE chat_id=?", (chat_id,),
        ).fetchone()[0]
    finally:
        connection.close()
    assert left == 0


def test_unknown_chat_writes_raise(tmp_path):
    repository = _repository(tmp_path)
    with pytest.raises(ChatNotFound):
        repository.delete_chat("нет-такого")
    with pytest.raises(ChatNotFound):
        repository.save_draft("нет-такого", {})
    with pytest.raises(ChatNotFound):
        repository.set_pending_proposal("нет-такого", None)
    with pytest.raises(ChatNotFound):
        repository.set_active_analysis("нет-такого", None)
    with pytest.raises(ChatNotFound):
        repository.append_message("нет-такого", "user", "text", "привет", None)


# -- messages -----------------------------------------------------------


def test_message_round_trips_text_and_payload(tmp_path):
    repository = _repository(tmp_path)
    chat_id = repository.create_chat("Чат")
    message = repository.append_message(
        chat_id, "assistant", "proposal", "Предложение", {"status": "pending", "url": "https://a.ru"},
    )
    assert message["seq"] == 1
    assert message["payload"] == {"status": "pending", "url": "https://a.ru"}
    assert repository.message(message["id"]) == message
    assert repository.messages(chat_id)["items"] == [message]
    assert repository.messages(chat_id)["next_cursor"] is None


def test_sequence_is_per_chat(tmp_path):
    repository = _repository(tmp_path)
    first = repository.create_chat("Первый")
    second = repository.create_chat("Второй")
    assert repository.append_message(first, "user", "text", "раз", None)["seq"] == 1
    assert repository.append_message(second, "user", "text", "раз", None)["seq"] == 1
    assert repository.append_message(first, "assistant", "text", "два", None)["seq"] == 2


def test_message_payload_can_be_updated(tmp_path):
    repository = _repository(tmp_path)
    chat_id = repository.create_chat("Чат")
    message = repository.append_message(chat_id, "assistant", "proposal", None, {"status": "pending"})
    updated = repository.update_message_payload(message["id"], {"status": "confirmed"})
    assert updated["payload"] == {"status": "confirmed"}
    assert repository.message(message["id"])["payload"] == {"status": "confirmed"}


def test_unknown_message_raises(tmp_path):
    repository = _repository(tmp_path)
    with pytest.raises(ChatNotFound):
        repository.message("нет-такого")
    with pytest.raises(ChatNotFound):
        repository.update_message_payload("нет-такого", {})


def test_cursor_walks_every_page_exactly_once(tmp_path):
    repository = _repository(tmp_path)
    chat_id = repository.create_chat("Чат")
    for index in range(5):
        repository.append_message(chat_id, "user", "text", f"текст {index}", None)
    collected: list[int] = []
    cursor = None
    while True:
        page = repository.messages(chat_id, cursor=cursor, limit=2)
        collected = [item["seq"] for item in page["items"]] + collected
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert collected == [1, 2, 3, 4, 5]


def test_sequences_stay_monotonic_under_concurrent_appends(tmp_path):
    repository = _repository(tmp_path)
    chat_id = repository.create_chat("Чат")
    per_worker = 20

    def append(indexes: list[int]) -> None:
        for _ in range(per_worker):
            message = repository.append_message(chat_id, "user", "text", "привет", None)
            indexes.append(message["seq"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        results: list[list[int]] = [[], [], [], []]
        futures = [pool.submit(append, indexes) for indexes in results]
        for future in futures:
            future.result(timeout=60)

    returned = sorted(index for indexes in results for index in indexes)
    assert returned == list(range(1, len(results) * per_worker + 1))
    page = repository.messages(chat_id, limit=200)
    assert [item["seq"] for item in page["items"]] == returned
