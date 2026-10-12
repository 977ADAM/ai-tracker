"""Observe real PostgreSQL lock waits, then test terminal-state protection."""

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.errors import RunConflict
from app.db.measurements import MeasurementRepository
from app.db.projects import ProjectRepository
from app.domain.projects import normalize_project
from app.domain.seo_answer import SeoAnswer
from tests.test_projects_measurements import project, snapshot


def waits_for_lock(db, future):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not future.done():
        blocked = db.execute(
            "SELECT 1 FROM pg_stat_activity WHERE cardinality(pg_blocking_pids(pid))>0 AND ?=ANY(pg_blocking_pids(pid))",
            (db.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"],),
        ).fetchone()
        if blocked:
            return True
        time.sleep(0.01)
    return False


@pytest.mark.parametrize(
    "operation",
    [
        "send",
        "answer",
        "sentiment",
        "search_operation",
        "search_result",
        "finish",
        "delete",
    ],
)
def test_mutations_wait_for_terminal_measurement_transaction(database_dsn, operation):
    projects, runs = (
        ProjectRepository(database_dsn),
        MeasurementRepository(database_dsn),
    )
    p = projects.create(normalize_project(project(yandex_enabled=True)))
    m = runs.create(p["id"], snapshot(project(yandex_enabled=True)), {})
    answer = SeoAnswer("Додопицца", "text", "not_requested", (), (), "test", None)
    if operation == "sentiment":
        runs.save_answer(m, (0, "m1"), answer)
    actions = {
        "send": lambda: runs.mark_sent(m, "model", (0, "m1")),
        "answer": lambda: runs.save_answer(m, (0, "m1"), answer),
        "sentiment": lambda: runs.save_sentiment(m, (0, "m1"), None),
        "search_operation": lambda: runs.save_search_operation(m, 0, "operation"),
        "search_result": lambda: runs.save_search_result(m, 0, []),
        "finish": lambda: runs.finish(m, "completed"),
        "delete": lambda: runs.delete(m),
    }
    with ThreadPoolExecutor(max_workers=1) as executor:
        with runs.connection(True) as db:
            db.execute(
                "SELECT id FROM project_measurements WHERE id=? FOR UPDATE", (m,)
            )
            future = executor.submit(actions[operation])
            try:
                assert waits_for_lock(db, future), (
                    "Mutation did not serialize with the measurement transaction"
                )
                db.execute(
                    "UPDATE project_measurements SET status='cancelled' WHERE id=?",
                    (m,),
                )
            finally:
                db.commit()
        result = future.result(timeout=5)
    if operation in (
        "send",
        "answer",
        "sentiment",
        "search_operation",
        "search_result",
    ):
        assert result is False
    if operation != "delete":
        assert runs.get(m)["status"] == "cancelled"


def test_start_serializes_with_project_deletion(database_dsn):
    projects, runs = (
        ProjectRepository(database_dsn),
        MeasurementRepository(database_dsn),
    )
    p = projects.create(normalize_project(project()))
    with ThreadPoolExecutor(max_workers=1) as executor:
        with projects.connection(True) as db:
            db.execute("SELECT id FROM projects WHERE id=? FOR UPDATE", (p["id"],))
            future = executor.submit(runs.create, p["id"], snapshot(), {})
            try:
                assert waits_for_lock(db, future)
            finally:
                db.commit()
        assert runs.get(future.result(timeout=5))["status"] == "running"


def test_delete_rechecks_active_measurements_after_project_lock(database_dsn):
    projects = ProjectRepository(database_dsn)
    p = projects.create(normalize_project(project()))
    with ThreadPoolExecutor(max_workers=1) as executor:
        with projects.connection(True) as db:
            db.execute("SELECT id FROM projects WHERE id=? FOR UPDATE", (p["id"],))
            future = executor.submit(projects.delete, p["id"])
            try:
                assert waits_for_lock(db, future)
                db.execute(
                    "INSERT INTO project_measurements VALUES(?,?,?,?,?,?,?,?)",
                    ("concurrent", p["id"], "{}", "key", "{}", "running", "now", None),
                )
            finally:
                db.commit()
        with pytest.raises(RunConflict):
            future.result(timeout=5)
    assert projects.get(p["id"])["id"] == p["id"]
