"""SQLite history: ordinal rows, restart recovery, paging, and guarded deletion."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from app.core.errors import RunConflict, RunNotFound, StorageError, ValidationError
from app.db.runs import RunRepository
from app.domain.models import PromptResult
from app.domain.runs import RunInput
from app.service.run_export import render_run_csv
from app.service.search import SearchRow


@pytest.fixture
def run_input() -> RunInput:
    return RunInput(
        brand="Ромашка", domain="example.ru", prompts=("цветы", "цветы"),
        provider_ids=("p",), regions=(1,), search_host="example.ru", region_engines=("yandex",),
    )


def repo(tmp_path: Path) -> RunRepository:
    repository = RunRepository(tmp_path)
    repository.initialize()
    return repository


def test_create_seeds_one_row_per_question_and_source(tmp_path, run_input):
    repository = repo(tmp_path)
    repository.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")

    saved = repository.get("run-1")
    assert saved["status"] == "pending"
    assert [(r["prompt_index"], r["status"]) for r in saved["models"]] == [(0, "pending"), (1, "pending")]
    assert [(r["prompt_index"], r["status"]) for r in saved["search"]] == [(0, "submitting"), (1, "submitting")]
    assert len(saved["summary_rows"]) == 4
    assert (tmp_path / "runs.sqlite3").stat().st_mode & 0o777 == 0o600
    assert tmp_path.stat().st_mode & 0o077 == 0


def test_saved_duplicate_prompt_answers_remain_distinct_after_reopen(tmp_path, run_input):
    first = repo(tmp_path)
    first.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    first.save_model("run-1", "p", 0, PromptResult("цветы", "Ромашка", True, None, "mentioned"))
    first.save_search("run-1", 1, SearchRow("цветы", 1, "Москва", "found", 2, "https://shop.example.ru", None))

    second = repo(tmp_path)
    saved = second.get("run-1")
    assert [r["status"] for r in saved["models"]] == ["mentioned", "pending"]
    assert [r["status"] for r in saved["search"]] == ["submitting", "found"]
    assert saved["search"][1]["position"] == 2
    assert saved["search"][1]["engine"] == "yandex"
    assert "operation_id" not in str(saved)
    assert "api_key" not in str(saved)


def test_restart_keeps_finished_rows_and_interrupts_only_pending(tmp_path, run_input):
    first = repo(tmp_path)
    first.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    first.save_model("run-1", "p", 0, PromptResult("цветы", "Ромашка", True, None, "mentioned"))
    first.save_search("run-1", 0, SearchRow("цветы", 1, "Москва", "absent"))

    second = repo(tmp_path)
    second.recover_unfinished()
    saved = second.get("run-1")
    assert [r["status"] for r in saved["models"]] == ["mentioned", "interrupted"]
    assert [r["status"] for r in saved["search"]] == ["absent", "interrupted"]
    assert saved["status"] == "interrupted"
    assert saved["finished_at"] is not None
    second.recover_unfinished()
    assert second.get("run-1")["models"][0]["answer"] == "Ромашка"


def test_delete_refuses_active_run_and_removes_a_terminal_one(tmp_path, run_input):
    repository = repo(tmp_path)
    repository.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    with pytest.raises(RunConflict):
        repository.delete("run-1")
    repository.fail_pending_branch("run-1", "model", "Ошибка модели")
    repository.interrupt_search("run-1")
    assert repository.get("run-1")["status"] == "interrupted"
    repository.delete("run-1")
    with pytest.raises(RunNotFound):
        repository.get("run-1")


def test_full_completion_and_search_expiry_are_terminal(tmp_path, run_input):
    repository = repo(tmp_path)
    repository.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    for i in range(2):
        repository.save_model("run-1", "p", i, PromptResult("цветы", "нет", False, None, "absent"))
    repository.interrupt_search("run-1")
    assert repository.get("run-1")["status"] == "interrupted"
    assert repository.get("run-1")["finished_at"] is not None


def test_cursor_page_is_stable_and_rejects_bad_cursors(tmp_path, run_input):
    repository = repo(tmp_path)
    for index in range(23):
        repository.create(
            f"run-{index:02d}", run_input, {"p": "ChatGPT"},
            f"2026-09-25T14:{index:02d}:00Z",
        )
    first = repository.list_page()
    second = repository.list_page(cursor=first["next_cursor"])
    assert len(first["items"]) == 20
    assert len(second["items"]) == 3
    assert first["items"][0]["id"] == "run-22"
    assert second["items"][-1]["id"] == "run-00"
    assert second["next_cursor"] is None
    with pytest.raises(ValidationError):
        repository.list_page(cursor="../bad")
    with pytest.raises(ValidationError):
        repository.list_page(cursor="a" * 257)


def test_unusable_database_fails_safely(tmp_path):
    path = tmp_path / "runs.sqlite3"
    path.mkdir()
    with pytest.raises(StorageError) as raised:
        repo(tmp_path)
    assert str(path) not in str(raised.value)


def test_version_one_database_migrates_existing_search_rows_to_yandex(tmp_path):
    import sqlite3

    path = tmp_path / "runs.sqlite3"
    tmp_path.mkdir(exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE runs (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, finished_at TEXT,
            brand TEXT NOT NULL, domain TEXT NOT NULL, prompts_json TEXT NOT NULL,
            provider_ids_json TEXT NOT NULL, regions_json TEXT NOT NULL);
        CREATE TABLE model_rows (run_id TEXT, provider_id TEXT, prompt_index INTEGER,
            provider_name TEXT, prompt TEXT, status TEXT, answer TEXT, mentioned INTEGER, error TEXT,
            PRIMARY KEY (run_id, provider_id, prompt_index));
        CREATE TABLE search_rows (run_id TEXT, search_index INTEGER, prompt_index INTEGER,
            region_index INTEGER, prompt TEXT, region_id INTEGER, region_name TEXT, status TEXT,
            position INTEGER, url TEXT, error TEXT, PRIMARY KEY (run_id, search_index));
        PRAGMA user_version=1;
    """)
    connection.execute(
        "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("legacy-run", "2026-09-25T14:00:00Z", "2026-09-25T14:01:00Z",
         "Ромашка", "example.ru", '["цветы"]', '["p"]', '[1]'),
    )
    connection.execute(
        "INSERT INTO model_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("legacy-run", "p", 0, "ChatGPT", "цветы", "mentioned", "Ромашка", 1, None),
    )
    connection.execute(
        "INSERT INTO search_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("legacy-run", 0, 0, 0, "цветы", 1, "Москва и Московская область",
         "found", 2, "https://example.ru/flowers", None),
    )
    connection.commit()
    connection.close()

    migrated = repo(tmp_path)
    connection = sqlite3.connect(path)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    columns = {row[1] for row in connection.execute("PRAGMA table_info(search_rows)")}
    connection.close()
    assert version == 2
    assert "engine" in columns
    saved = migrated.get("legacy-run")
    assert saved["status"] == "done"
    assert saved["brand"] == "Ромашка"
    assert saved["prompts"] == ["цветы"]
    assert saved["models"][0]["answer"] == "Ромашка"
    assert saved["search"] == [{
        "search_index": 0, "prompt_index": 0, "region_index": 0,
        "prompt": "цветы", "region_id": 1, "region_name": "Москва и Московская область",
        "engine": "yandex", "status": "found", "position": 2,
        "url": "https://example.ru/flowers", "error": None,
    }]
    assert saved["summary_rows"][0] == {
        "prompt": "цветы", "source": "Яндекс", "language": "ru",
        "region": "Москва и Московская область", "ai_answer": "—",
        "site_found": "Да", "position": "2", "brand_found": "—", "status": "Готово",
    }


def test_snapshot_remains_complete_while_terminal_run_is_deleted(tmp_path, run_input):
    reader = repo(tmp_path)
    reader.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    reader.fail_pending_branch("run-1", "model", "Ошибка")
    reader.fail_pending_branch("run-1", "search", "Ошибка")
    deleter = repo(tmp_path)
    header_read, release_read, delete_started, delete_done = Event(), Event(), Event(), Event()
    original = reader._require_run

    def pause_after_header(connection, run_id):
        row = original(connection, run_id)
        header_read.set()
        assert release_read.wait(2)
        return row

    reader._require_run = pause_after_header

    def delete() -> None:
        delete_started.set()
        deleter.delete("run-1")
        delete_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        snapshot_future = pool.submit(reader.get, "run-1")
        assert header_read.wait(2)
        deletion_future = pool.submit(delete)
        assert delete_started.wait(2)
        assert not delete_done.wait(0.05)
        release_read.set()
        snapshot = snapshot_future.result(timeout=2)
        deletion_future.result(timeout=2)
    assert snapshot["status"] == "done"
    assert len(snapshot["summary_rows"]) == 4
    assert delete_done.is_set()


def test_history_page_survives_concurrent_terminal_deletion(tmp_path, run_input):
    reader = repo(tmp_path)
    reader.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    reader.fail_pending_branch("run-1", "model", "Ошибка")
    reader.fail_pending_branch("run-1", "search", "Ошибка")
    deleter = repo(tmp_path)
    selected, release_read, delete_started, delete_done = Event(), Event(), Event(), Event()
    original = reader._require_run

    def pause_snapshot(connection, run_id):
        selected.set()
        assert release_read.wait(2)
        return original(connection, run_id)

    reader._require_run = pause_snapshot

    def delete() -> None:
        delete_started.set()
        deleter.delete("run-1")
        delete_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        page_future = pool.submit(reader.list_page)
        assert selected.wait(2)
        deletion_future = pool.submit(delete)
        assert delete_started.wait(2)
        assert not delete_done.wait(0.05)
        release_read.set()
        page = page_future.result(timeout=2)
        deletion_future.result(timeout=2)
    assert page["items"][0]["id"] == "run-1"
    assert delete_done.is_set()


def test_export_and_delete_wait_for_last_row_commit(tmp_path):
    repository = repo(tmp_path)
    request = RunInput("Ромашка", "", ("цветы",), ("p",), (), None)
    repository.create("run-1", request, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    row_written, release_finish, delete_started, delete_done = Event(), Event(), Event(), Event()
    original = repository._finish_if_terminal

    def pause_before_finish(connection, run_id):
        row_written.set()
        assert release_finish.wait(2)
        return original(connection, run_id)

    repository._finish_if_terminal = pause_before_finish
    deleter = repo(tmp_path)

    def delete() -> None:
        delete_started.set()
        deleter.delete("run-1")
        delete_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        save_future = pool.submit(
            repository.save_model, "run-1", "p", 0,
            PromptResult("цветы", "Ромашка", True, None, "mentioned"),
        )
        assert row_written.wait(2)
        pending_snapshot = deleter.get("run-1")
        assert pending_snapshot["status"] == "pending"
        with pytest.raises(RunConflict):
            render_run_csv(pending_snapshot)
        delete_future = pool.submit(delete)
        assert delete_started.wait(2)
        assert not delete_done.wait(0.05)
        release_finish.set()
        save_future.result(timeout=2)
        delete_future.result(timeout=2)
    assert delete_done.is_set()


def test_version_three_database_from_the_seo_migration_stays_readable(tmp_path, run_input):
    """The SEO repository raises `user_version` to 3; runs must still open."""
    import sqlite3

    repository = repo(tmp_path)
    repository.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    connection = sqlite3.connect(tmp_path / "runs.sqlite3")
    connection.execute("PRAGMA user_version=3")
    connection.commit()
    connection.close()

    reopened = repo(tmp_path)
    reopened.recover_unfinished()
    saved = reopened.get("run-1")
    assert saved["status"] == "interrupted"
    assert [row["status"] for row in saved["models"]] == ["interrupted", "interrupted"]
    assert [row["status"] for row in saved["search"]] == ["interrupted", "interrupted"]
    version = sqlite3.connect(tmp_path / "runs.sqlite3")
    try:
        assert version.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        version.close()


def test_version_four_database_from_the_agent_migration_stays_readable(tmp_path, run_input):
    """The SEO repository raises `user_version` to 4; runs must still open it."""
    import sqlite3

    repository = repo(tmp_path)
    repository.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    connection = sqlite3.connect(tmp_path / "runs.sqlite3")
    connection.execute("PRAGMA user_version=4")
    connection.commit()
    connection.close()

    reopened = repo(tmp_path)
    reopened.recover_unfinished()
    saved = reopened.get("run-1")
    assert saved["status"] == "interrupted"
    assert [row["status"] for row in saved["models"]] == ["interrupted", "interrupted"]
    version = sqlite3.connect(tmp_path / "runs.sqlite3")
    try:
        assert version.execute("PRAGMA user_version").fetchone()[0] == 4
    finally:
        version.close()


def test_version_five_database_from_the_chat_migration_stays_readable(tmp_path, run_input):
    """The chat repository raises `user_version` to 5; runs must still open it."""
    import sqlite3

    repository = repo(tmp_path)
    repository.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    connection = sqlite3.connect(tmp_path / "runs.sqlite3")
    connection.execute("PRAGMA user_version=5")
    connection.commit()
    connection.close()

    reopened = repo(tmp_path)
    reopened.recover_unfinished()
    saved = reopened.get("run-1")
    assert saved["status"] == "interrupted"
    assert [row["status"] for row in saved["models"]] == ["interrupted", "interrupted"]
    version = sqlite3.connect(tmp_path / "runs.sqlite3")
    try:
        assert version.execute("PRAGMA user_version").fetchone()[0] == 5
    finally:
        version.close()


def test_a_newer_database_version_is_refused(tmp_path):
    import sqlite3

    path = tmp_path / "runs.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version=7")
    connection.commit()
    connection.close()

    with pytest.raises(StorageError) as raised:
        repo(tmp_path)
    assert str(path) not in str(raised.value)

    fresh = sqlite3.connect(path)
    try:
        assert fresh.execute("PRAGMA user_version").fetchone()[0] == 7
    finally:
        fresh.close()
