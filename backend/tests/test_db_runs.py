"""SQLite history: ordinal rows, restart recovery, paging, and guarded deletion."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import RunConflict, RunNotFound, StorageError, ValidationError
from app.db.runs import RunRepository
from app.domain.models import PromptResult
from app.domain.runs import RunInput
from app.service.search import SearchRow


@pytest.fixture
def run_input() -> RunInput:
    return RunInput(
        brand="Ромашка", domain="example.ru", prompts=("цветы", "цветы"),
        provider_ids=("p",), regions=(1,), search_host="example.ru",
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
