"""PostgreSQL history: ordinal rows, restart recovery, paging, and guarded deletion."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from app.core import database
from app.core.errors import RunConflict, RunNotFound, StorageError, ValidationError
from app.db.projects import ProjectRepository
from app.db.runs import RunRepository
from app.domain.models import PromptResult
from app.domain.runs import RunInput
from app.service.run_export import render_run_csv
from app.service.search import SearchRow


@pytest.fixture
def project_id(database_dsn: str) -> str:
    """Every run belongs to a project, so each test starts with one."""
    project = ProjectRepository(database_dsn).create({"domain": "example.ru"})
    return str(project["id"])


@pytest.fixture
def run_input(project_id: str) -> RunInput:
    return RunInput(
        project_id=project_id,
        brand="Ромашка", domain="example.ru", prompts=("цветы", "цветы"),
        provider_ids=("p",), regions=(1,), search_host="example.ru", region_engines=("yandex",),
    )


def repo(dsn: str) -> RunRepository:
    return RunRepository(dsn)


def test_create_seeds_one_row_per_question_and_source(database_dsn, run_input):
    repository = repo(database_dsn)
    repository.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")

    saved = repository.get("run-1")
    assert saved["status"] == "pending"
    assert saved["project_id"] == run_input.project_id
    assert [(r["prompt_index"], r["status"]) for r in saved["models"]] == [(0, "pending"), (1, "pending")]
    assert [(r["prompt_index"], r["status"]) for r in saved["search"]] == [(0, "submitting"), (1, "submitting")]
    assert len(saved["summary_rows"]) == 4
    with database.connect(database_dsn) as connection:
        stored = connection.execute("SELECT count(*) AS n FROM model_rows WHERE run_id='run-1'").fetchone()
    assert stored["n"] == 2


def test_a_run_without_an_existing_project_is_refused(database_dsn, run_input):
    orphan = RunInput(
        project_id="missing-project",
        brand=run_input.brand, domain=run_input.domain, prompts=run_input.prompts,
        provider_ids=run_input.provider_ids, regions=run_input.regions,
        search_host=run_input.search_host, region_engines=run_input.region_engines,
    )
    with pytest.raises(RunNotFound):
        repo(database_dsn).create("run-1", orphan, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")


def test_deleting_a_project_removes_its_runs(database_dsn, run_input):
    repository = repo(database_dsn)
    repository.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    ProjectRepository(database_dsn).delete(run_input.project_id)
    with database.connect(database_dsn) as connection:
        remaining = connection.execute("SELECT count(*) AS n FROM runs").fetchone()
    assert remaining["n"] == 0


def test_saved_duplicate_prompt_answers_remain_distinct_after_reopen(database_dsn, run_input):
    first = repo(database_dsn)
    first.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    first.save_model("run-1", "p", 0, PromptResult("цветы", "Ромашка", True, None, "mentioned"))
    first.save_search("run-1", 1, SearchRow("цветы", 1, "Москва", "found", 2, "https://shop.example.ru", None))

    second = repo(database_dsn)
    saved = second.get("run-1")
    assert [r["status"] for r in saved["models"]] == ["mentioned", "pending"]
    assert [r["status"] for r in saved["search"]] == ["submitting", "found"]
    assert saved["search"][1]["position"] == 2
    assert saved["search"][1]["engine"] == "yandex"
    assert "operation_id" not in str(saved)
    assert "api_key" not in str(saved)


def test_restart_keeps_finished_rows_and_interrupts_only_pending(database_dsn, run_input):
    first = repo(database_dsn)
    first.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    first.save_model("run-1", "p", 0, PromptResult("цветы", "Ромашка", True, None, "mentioned"))
    first.save_search("run-1", 0, SearchRow("цветы", 1, "Москва", "absent"))

    second = repo(database_dsn)
    second.recover_unfinished()
    saved = second.get("run-1")
    assert [r["status"] for r in saved["models"]] == ["mentioned", "interrupted"]
    assert [r["status"] for r in saved["search"]] == ["absent", "interrupted"]
    assert saved["status"] == "interrupted"
    assert saved["finished_at"] is not None
    second.recover_unfinished()
    assert second.get("run-1")["models"][0]["answer"] == "Ромашка"


def test_delete_refuses_active_run_and_removes_a_terminal_one(database_dsn, run_input):
    repository = repo(database_dsn)
    repository.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    with pytest.raises(RunConflict):
        repository.delete("run-1")
    repository.fail_pending_branch("run-1", "model", "Ошибка модели")
    repository.interrupt_search("run-1")
    assert repository.get("run-1")["status"] == "interrupted"
    repository.delete("run-1")
    with pytest.raises(RunNotFound):
        repository.get("run-1")


def test_full_completion_and_search_expiry_are_terminal(database_dsn, run_input):
    repository = repo(database_dsn)
    repository.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    for i in range(2):
        repository.save_model("run-1", "p", i, PromptResult("цветы", "нет", False, None, "absent"))
    repository.interrupt_search("run-1")
    assert repository.get("run-1")["status"] == "interrupted"
    assert repository.get("run-1")["finished_at"] is not None


def test_cursor_page_is_stable_and_rejects_bad_cursors(database_dsn, run_input):
    repository = repo(database_dsn)
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


def test_history_can_be_scoped_to_one_project(database_dsn, run_input):
    other = ProjectRepository(database_dsn).create({"domain": "other.ru"})
    repository = repo(database_dsn)
    repository.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    other_input = RunInput(
        project_id=str(other["id"]), brand="Другой", domain="other.ru", prompts=("цветы",),
        provider_ids=("p",), regions=(1,), search_host="other.ru", region_engines=("yandex",),
    )
    repository.create("run-2", other_input, {"p": "ChatGPT"}, "2026-09-25T15:00:00Z")

    scoped = repository.list_page(project_id=run_input.project_id)
    assert [item["id"] for item in scoped["items"]] == ["run-1"]


def test_storage_failure_is_reported_without_the_connection_url():
    with pytest.raises(StorageError) as raised:
        repo("postgresql://nobody@127.0.0.1:1/absent").recover_unfinished()
    assert "postgresql://" not in str(raised.value)


def test_snapshot_and_deletion_are_independent_under_concurrency(database_dsn, run_input):
    """A reader keeps a complete snapshot while another session deletes the run."""
    reader = repo(database_dsn)
    reader.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    reader.fail_pending_branch("run-1", "model", "Ошибка")
    reader.fail_pending_branch("run-1", "search", "Ошибка")
    deleter = repo(database_dsn)
    snapshot_read = Event()
    original = reader._require_run

    def note_header(connection, run_id):
        row = original(connection, run_id)
        snapshot_read.set()
        return row

    reader._require_run = note_header

    with ThreadPoolExecutor(max_workers=2) as pool:
        snapshot_future = pool.submit(reader.get, "run-1")
        assert snapshot_read.wait(5)
        deletion_future = pool.submit(deleter.delete, "run-1")
        snapshot = snapshot_future.result(timeout=5)
        deletion_future.result(timeout=5)

    assert snapshot["status"] == "done"
    assert len(snapshot["summary_rows"]) == 4
    with pytest.raises(RunNotFound):
        deleter.get("run-1")


def test_history_page_survives_concurrent_terminal_deletion(database_dsn, run_input):
    reader = repo(database_dsn)
    reader.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    reader.fail_pending_branch("run-1", "model", "Ошибка")
    reader.fail_pending_branch("run-1", "search", "Ошибка")
    deleter = repo(database_dsn)

    with ThreadPoolExecutor(max_workers=2) as pool:
        page_future = pool.submit(reader.list_page)
        deletion_future = pool.submit(deleter.delete, "run-1")
        page = page_future.result(timeout=5)
        deletion_future.result(timeout=5)

    assert page["items"]
    with pytest.raises(RunNotFound):
        deleter.get("run-1")


def test_export_and_delete_keep_each_other_consistent(database_dsn, project_id):
    repository = repo(database_dsn)
    request = RunInput(project_id, "Ромашка", "", ("цветы",), ("p",), (), None)
    repository.create("run-1", request, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    row_written, release_finish = Event(), Event()
    original = repository._finish_if_terminal

    def pause_before_finish(connection, run_id):
        row_written.set()
        assert release_finish.wait(5)
        return original(connection, run_id)

    repository._finish_if_terminal = pause_before_finish
    deleter = repo(database_dsn)

    def delete() -> None:
        deleter.delete("run-1")

    with ThreadPoolExecutor(max_workers=2) as pool:
        save_future = pool.submit(
            repository.save_model, "run-1", "p", 0,
            PromptResult("цветы", "Ромашка", True, None, "mentioned"),
        )
        assert row_written.wait(5)
        pending_snapshot = deleter.get("run-1")
        assert pending_snapshot["status"] == "pending"
        with pytest.raises(RunConflict):
            render_run_csv(pending_snapshot)
        delete_future = pool.submit(delete)
        release_finish.set()
        save_future.result(timeout=5)
        delete_future.result(timeout=5)
    with pytest.raises(RunNotFound):
        deleter.get("run-1")
