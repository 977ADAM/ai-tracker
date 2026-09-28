"""SEO persistence: schema migration, durable rows, lifecycle reads, and concurrency.

`SeoRepository` shares the existing `runs.sqlite3` with `RunRepository`: the
version-3 migration must add the SEO tables without touching the legacy run
tables, and every saved row must survive a second repository instance.
"""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.core.errors import RunConflict, RunNotFound, StorageError, ValidationError
from app.db.runs import RunRepository
from app.db.seo import ResumePlan, SeoRepository
from app.domain.seo import (
    Candidate,
    CandidateHit,
    GeneratedQuery,
    QueryFlags,
    SeoInput,
)

DB_FILE = "runs.sqlite3"
LEGACY_TABLES = {"runs", "model_rows", "search_rows"}
SEO_TABLES = {
    "seo_analyses",
    "seo_stages",
    "seo_pages",
    "seo_candidates",
    "seo_queries",
    "seo_search_rows",
    "seo_candidate_hits",
    "seo_model_rows",
    "seo_seed_rows",
}
LEGACY_SCHEMA = """
CREATE TABLE runs (
    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, finished_at TEXT,
    brand TEXT NOT NULL, domain TEXT NOT NULL, prompts_json TEXT NOT NULL,
    provider_ids_json TEXT NOT NULL, regions_json TEXT NOT NULL
);
CREATE TABLE model_rows (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL, prompt_index INTEGER NOT NULL,
    provider_name TEXT NOT NULL, prompt TEXT NOT NULL, status TEXT NOT NULL,
    answer TEXT, mentioned INTEGER, error TEXT,
    PRIMARY KEY (run_id, provider_id, prompt_index)
);
CREATE TABLE search_rows (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    search_index INTEGER NOT NULL, prompt_index INTEGER NOT NULL,
    region_index INTEGER NOT NULL, prompt TEXT NOT NULL, region_id INTEGER NOT NULL,
    region_name TEXT NOT NULL, engine TEXT NOT NULL DEFAULT 'yandex',
    status TEXT NOT NULL, position INTEGER, url TEXT, error TEXT,
    PRIMARY KEY (run_id, search_index)
);
"""


# -- helpers -----------------------------------------------------------------


def seo_repo(config_dir: Path) -> SeoRepository:
    repository = SeoRepository(config_dir)
    repository.initialize()
    return repository


def seo_input(**overrides: object) -> SeoInput:
    values: dict[str, object] = {
        "url": "https://example.ru/",
        "host": "example.ru",
        "sphere": "Цветочный магазин",
        "seeds": ("букет цветов", "доставка цветов", "розы"),
        "services": ("Букеты", "Доставка"),
        "connection_ids": ("chatgpt", "claude"),
    }
    values.update(overrides)
    return SeoInput(**values)  # type: ignore[arg-type]


def create(repository: SeoRepository, **overrides: object) -> str:
    return repository.create_analysis(seo_input(**overrides), {"search": 23, "model": 40})


def query(text: str, index: int, *, category: str = "commercial", service: str | None = "Букеты") -> GeneratedQuery:
    return GeneratedQuery(
        text=text,
        category=category,
        service=service,
        flags=QueryFlags(
            mentions_company_name=index % 2 == 0,
            mentions_company_host=False,
            mentions_candidate_host=index % 3 == 0,
            branded=index % 2 == 0,
        ),
    )


CANDIDATES = (
    Candidate("rival.ru", "Соперник", 3, 2.33, (0, 1, 2), True),
    Candidate("other.ru", "", 1, 7.0, (1,), False),
)


def user_version(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])
    finally:
        connection.close()


def table_names(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        connection.close()


def create_legacy_database(path: Path) -> None:
    """Write a populated version-2 database exactly as `RunRepository` leaves it."""
    connection = sqlite3.connect(path)
    try:
        connection.executescript(LEGACY_SCHEMA)
        connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy-run", "2026-09-25T14:00:00Z", "2026-09-25T14:01:00Z", "Ромашка",
             "example.ru", '["цветы"]', '["p"]', '[1]'),
        )
        connection.execute(
            "INSERT INTO model_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy-run", "p", 0, "ChatGPT", "цветы", "mentioned", "Ромашка", 1, None),
        )
        connection.execute(
            "INSERT INTO search_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy-run", 0, 0, 0, "цветы", 1, "Москва и Московская область",
             "yandex", "found", 2, "https://example.ru/flowers", None),
        )
        connection.execute("PRAGMA user_version=2")
        connection.commit()
    finally:
        connection.close()


# -- step 1: migration -------------------------------------------------------


def test_initialize_creates_seo_tables_and_reaches_version_three(tmp_path):
    repository = seo_repo(tmp_path)

    assert user_version(tmp_path / DB_FILE) == 3
    assert table_names(tmp_path / DB_FILE) == SEO_TABLES
    assert (tmp_path / DB_FILE).stat().st_mode & 0o777 == 0o600
    assert tmp_path.stat().st_mode & 0o077 == 0
    raw = sqlite3.connect(tmp_path / DB_FILE)
    try:
        assert raw.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        raw.close()
    with repository._connection() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    repository.initialize()
    assert user_version(tmp_path / DB_FILE) == 3


def test_initialize_adds_the_seed_table_to_an_existing_version_three_file(tmp_path):
    path = tmp_path / DB_FILE
    seo_repo(tmp_path)
    raw = sqlite3.connect(path)
    try:
        raw.execute("DROP TABLE seo_seed_rows")
        raw.execute("PRAGMA user_version=3")
        raw.commit()
    finally:
        raw.close()

    repository = seo_repo(tmp_path)

    assert "seo_seed_rows" in table_names(path)
    assert user_version(path) == 3
    analysis_id = create(repository)
    repository.save_seed_row(analysis_id, 0, status="waiting", operation_id="op-0")
    assert repository.resume_plan(analysis_id).submitted_seeds == ((0, "op-0"),)


def test_migration_from_populated_version_two_keeps_runs_and_adds_seo(tmp_path):
    path = tmp_path / DB_FILE
    create_legacy_database(path)

    seo = seo_repo(tmp_path)

    assert user_version(path) == 3
    assert LEGACY_TABLES <= table_names(path)
    assert SEO_TABLES <= table_names(path)
    # The migrated file carries both stacks: an SEO run can start right away.
    analysis_id = create(seo)
    assert seo.snapshot(analysis_id)["status"] == "running"
    runs = RunRepository(tmp_path)
    runs.initialize()
    runs.recover_unfinished()
    saved = runs.get("legacy-run")
    assert saved["status"] == "done"
    assert saved["brand"] == "Ромашка"
    assert saved["models"][0]["answer"] == "Ромашка"
    assert saved["search"][0]["position"] == 2


def test_newer_schema_version_is_refused_without_leaking_the_path(tmp_path):
    path = tmp_path / DB_FILE
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version=4")
    connection.commit()
    connection.close()

    with pytest.raises(StorageError) as raised:
        SeoRepository(tmp_path).initialize()
    assert str(path) not in str(raised.value)
    assert user_version(path) == 4


def test_unusable_database_file_fails_safely(tmp_path):
    (tmp_path / DB_FILE).mkdir()
    with pytest.raises(StorageError) as raised:
        seo_repo(tmp_path)
    assert str(tmp_path / DB_FILE) not in str(raised.value)


# -- step 3: durable writes --------------------------------------------------


def test_create_analysis_is_durable_before_the_first_external_call(tmp_path):
    first = seo_repo(tmp_path)
    analysis_id = create(first)

    second = seo_repo(tmp_path)
    snapshot = second.snapshot(analysis_id)
    assert snapshot["status"] == "running"
    assert snapshot["finished_at"] is None
    assert snapshot["input"]["url"] == "https://example.ru/"
    assert snapshot["input"]["host"] == "example.ru"
    assert snapshot["input"]["sphere"] == "Цветочный магазин"
    assert snapshot["input"]["seeds"] == ["букет цветов", "доставка цветов", "розы"]
    assert snapshot["input"]["services"] == ["Букеты", "Доставка"]
    assert snapshot["input"]["connection_ids"] == ["chatgpt", "claude"]
    assert snapshot["estimate"] == {"search": 23, "model": 40}
    assert [stage["stage"] for stage in snapshot["stages"]] == [1, 2, 3, 4, 5, 6]
    assert {stage["status"] for stage in snapshot["stages"]} == {"pending"}
    # The identifier is generated by the server and says nothing about the input.
    assert analysis_id not in snapshot["input"]["url"]
    assert len(analysis_id) >= 20
    with pytest.raises(RunNotFound):
        second.snapshot("нет такого анализа")


def test_stage_updates_keep_order_counters_and_errors(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)

    repository.update_stage(analysis_id, 1, "running")
    repository.update_stage(analysis_id, 1, "done", counters={"pages": 3, "candidates": 5})
    repository.update_stage(analysis_id, 2, "error", error="Не удалось получить выдачу")

    stages = repository.snapshot(analysis_id)["stages"]
    assert [(stage["stage"], stage["status"]) for stage in stages] == [
        (1, "done"), (2, "error"), (3, "pending"), (4, "pending"), (5, "pending"), (6, "pending"),
    ]
    assert stages[0]["counters"] == {"pages": 3, "candidates": 5}
    assert stages[1]["error"] == "Не удалось получить выдачу"
    assert stages[1]["counters"] == {}
    assert stages[2]["error"] is None

    with pytest.raises(ValidationError):
        repository.update_stage(analysis_id, 7, "done")
    with pytest.raises(ValidationError):
        repository.update_stage(analysis_id, 1, "неизвестно")
    with pytest.raises(RunNotFound):
        repository.update_stage("нет такого анализа", 1, "done")


def test_site_facts_replace_pages_and_services(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)

    repository.save_site_facts(
        analysis_id, "Ромашка", ("Букеты", "Доставка", "Свадьбы"),
        (("https://example.ru/", "Главная"), ("https://example.ru/dostavka", "Доставка")),
    )
    snapshot = repository.snapshot(analysis_id)
    assert snapshot["company_name"] == "Ромашка"
    assert snapshot["services"] == ["Букеты", "Доставка", "Свадьбы"]
    assert snapshot["pages"] == [
        {"url": "https://example.ru/", "title": "Главная"},
        {"url": "https://example.ru/dostavka", "title": "Доставка"},
    ]

    repository.save_site_facts(analysis_id, "", ("Букеты",), ())
    snapshot = repository.snapshot(analysis_id)
    assert snapshot["company_name"] == ""
    assert snapshot["services"] == ["Букеты"]
    assert snapshot["pages"] == []
    # The entered request keeps its own services, separate from the merged list.
    assert snapshot["input"]["services"] == ["Букеты", "Доставка"]


def test_candidate_and_query_replacement_drops_the_previous_rows(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)

    repository.replace_candidates(analysis_id, CANDIDATES)
    repository.replace_candidates(analysis_id, CANDIDATES[:1])
    assert repository.snapshot(analysis_id)["candidates"] == [{
        "host": "rival.ru", "title": "Соперник", "occurrences": 3,
        "average_position": 2.33, "seed_indexes": [0, 1, 2], "recurring": True,
    }]

    queries = [query(f"запрос {index}", index) for index in range(3)]
    repository.replace_queries(analysis_id, queries)
    repository.replace_queries(analysis_id, queries[:1])
    assert repository.snapshot(analysis_id)["queries"] == [{
        "index": 0, "text": "запрос 0", "category": "commercial", "service": "Букеты",
        "flags": {
            "mentions_company_name": True, "mentions_company_host": False,
            "mentions_candidate_host": True, "branded": True,
        },
    }]


def test_candidate_hits_are_replaced_per_query(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)
    repository.replace_queries(analysis_id, [query("запрос", 0)])

    repository.save_candidate_hits(analysis_id, 0, (CandidateHit("rival.ru", 2, "https://rival.ru/a"),))
    repository.save_candidate_hits(
        analysis_id, 0,
        (CandidateHit("rival.ru", 4, None), CandidateHit("other.ru", 9, "https://other.ru/")),
    )
    with pytest.raises(RunNotFound):
        repository.save_candidate_hits("нет такого анализа", 0, ())


def test_a_failed_write_rolls_back_without_partial_rows(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)
    repository.save_site_facts(
        analysis_id, "Старое имя", ("Букеты",), (("https://example.ru/", "Главная"),),
    )
    connection = sqlite3.connect(tmp_path / DB_FILE)
    try:
        connection.executescript(
            "CREATE TRIGGER fail_page BEFORE INSERT ON seo_pages "
            "BEGIN SELECT RAISE(ABORT, 'private sql detail'); END;"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(StorageError) as raised:
        repository.save_site_facts(
            analysis_id, "Новое имя", ("Доставка",), (("https://example.ru/new", "Новая"),),
        )
    assert "private sql detail" not in str(raised.value)
    assert str(tmp_path) not in str(raised.value)

    snapshot = repository.snapshot(analysis_id)
    assert snapshot["company_name"] == "Старое имя"
    assert snapshot["services"] == ["Букеты"]
    assert snapshot["pages"] == [{"url": "https://example.ru/", "title": "Главная"}]


# -- step 5: lifecycle reads -------------------------------------------------


def scalar(path: Path, sql: str, params: tuple = ()) -> object:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute(sql, params).fetchone()
        return row[0] if row is not None else None
    finally:
        connection.close()


def seed_states(path: Path, analysis_id: str) -> dict[int, tuple[str, str | None]]:
    connection = sqlite3.connect(path)
    try:
        return {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                "SELECT seed_index, status, operation_id FROM seo_seed_rows "
                "WHERE analysis_id=? ORDER BY seed_index",
                (analysis_id,),
            )
        }
    finally:
        connection.close()


def stamp_created_at(path: Path, analysis_ids: list[str]) -> None:
    connection = sqlite3.connect(path)
    try:
        for index, analysis_id in enumerate(analysis_ids):
            connection.execute(
                "UPDATE seo_analyses SET created_at=? WHERE id=?",
                (f"2026-09-25T14:{index:02d}:00Z", analysis_id),
            )
        connection.commit()
    finally:
        connection.close()


def test_history_is_newest_first_with_a_cursor_and_light_items(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_ids = [create(repository) for _ in range(23)]
    stamp_created_at(tmp_path / DB_FILE, analysis_ids)

    first = repository.list_page()
    second = repository.list_page(cursor=first["next_cursor"])

    assert len(first["items"]) == 20
    assert len(second["items"]) == 3
    assert first["items"][0]["id"] == analysis_ids[-1]
    assert second["items"][-1]["id"] == analysis_ids[0]
    assert second["next_cursor"] is None
    item = first["items"][0]
    assert set(item) == {
        "id", "created_at", "finished_at", "status", "sphere", "host", "company_name", "counters",
    }
    assert item["status"] == "running"
    assert item["sphere"] == "Цветочный магазин"
    assert item["host"] == "example.ru"
    assert item["counters"] == {
        "queries": 0, "search_rows": 0, "model_rows": 0, "search_errors": 0, "model_errors": 0,
    }
    with pytest.raises(ValidationError):
        repository.list_page(cursor="../bad")
    with pytest.raises(ValidationError):
        repository.list_page(cursor="a" * 257)
    with pytest.raises(ValidationError):
        repository.list_page(limit=0)
    with pytest.raises(ValidationError):
        repository.list_page(limit=101)


def test_history_counters_are_saved_row_counts_not_a_report(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)
    repository.replace_queries(analysis_id, [query(f"запрос {index}", index) for index in range(3)])
    repository.save_search_row(analysis_id, 0, status="found", site_position=2, site_url="https://example.ru/")
    repository.save_search_row(analysis_id, 1, status="absent")
    repository.save_search_row(analysis_id, 2, status="error", error="Сбой поиска")
    repository.save_model_row(analysis_id, "chatgpt", "ChatGPT", 0, status="found", answer="да")
    repository.save_model_row(analysis_id, "chatgpt", "ChatGPT", 1, status="error", error="Сбой модели")

    item = repository.list_page()["items"][0]
    assert item["counters"] == {
        "queries": 3, "search_rows": 3, "model_rows": 2, "search_errors": 1, "model_errors": 1,
    }
    assert "aggregates" not in item


def test_snapshot_exposes_aggregates_without_answers_or_operation_ids(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)
    repository.save_site_facts(analysis_id, "Ромашка", ("Букеты",), ())
    repository.replace_candidates(analysis_id, CANDIDATES)
    repository.replace_queries(analysis_id, [query("запрос", 0)])
    repository.save_search_row(
        analysis_id, 0, status="found", operation_id="op-private-1",
        site_position=3, site_url="https://example.ru/",
    )
    repository.save_candidate_hits(analysis_id, 0, (CandidateHit("rival.ru", 5, None),))
    repository.save_model_row(
        analysis_id, "chatgpt", "ChatGPT", 0, status="found",
        answer="Ромашка — да", name_mentioned=True,
    )
    repository.update_stage(analysis_id, 6, "done")

    snapshot = repository.snapshot(analysis_id)
    payload = json.dumps(snapshot, ensure_ascii=False)
    assert "Ромашка — да" not in payload
    assert "op-private-1" not in payload
    assert snapshot["company_name"] == "Ромашка"
    assert snapshot["stages"][5]["status"] == "done"
    assert snapshot["candidates"][0]["host"] == "rival.ru"
    assert snapshot["queries"][0]["text"] == "запрос"
    assert snapshot["counters"] == {
        "queries": 1, "search_rows": 1, "model_rows": 1, "search_errors": 0, "model_errors": 0,
    }
    assert snapshot["readiness"]["report_ready"] is True
    assert snapshot["readiness"]["has_submitted_search_rows"] is False
    assert snapshot["aggregates"]["counts"] == {
        "queries": 1, "search_rows": 1, "model_rows": 1, "search_errors": 0, "model_errors": 0,
    }
    assert snapshot["aggregates"]["site"]["search"]["overall"] == {
        "denominator": 1, "successes": 1, "share": 1.0, "average_position": 3.0,
    }
    assert snapshot["aggregates"]["site"]["ai"]["chatgpt"]["name"] == {
        "denominator": 1, "successes": 1, "share": 1.0, "average_position": None,
    }

    repository.save_model_row(analysis_id, "claude", "Claude", 0, status="pending")
    assert repository.snapshot(analysis_id)["readiness"]["has_unfinished_model_rows"] is True


def test_model_rows_page_filters_orders_and_pages(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)
    repository.replace_queries(analysis_id, [query(f"запрос {index}", index) for index in range(3)])
    for index in range(3):
        for connection_id in ("claude", "chatgpt"):
            repository.save_model_row(
                analysis_id, connection_id, connection_id.upper(), index, status="found",
                answer=f"ответ {connection_id} {index}", name_mentioned=index == 0, host_mentioned=False,
            )
    other = create(repository)
    repository.save_model_row(other, "chatgpt", "CHATGPT", 0, status="found", answer="чужой ответ")

    first = repository.rows_page(analysis_id, "model", limit=3)
    assert [(row["query_index"], row["connection_id"]) for row in first["items"]] == [
        (0, "chatgpt"), (0, "claude"), (1, "chatgpt"),
    ]
    assert first["items"][0] == {
        "query_index": 0, "connection_id": "chatgpt", "provider_name": "CHATGPT", "status": "found",
        "answer": "ответ chatgpt 0", "name_mentioned": True, "host_mentioned": False, "error": None,
        "query": "запрос 0", "category": "commercial", "service": "Букеты",
    }
    second = repository.rows_page(analysis_id, "model", cursor=first["next_cursor"], limit=3)
    assert [(row["query_index"], row["connection_id"]) for row in second["items"]] == [
        (1, "claude"), (2, "chatgpt"), (2, "claude"),
    ]
    assert second["next_cursor"] is None
    assert all(row["answer"] != "чужой ответ" for row in first["items"] + second["items"])

    with pytest.raises(ValidationError):
        repository.rows_page(analysis_id, "model", cursor="../bad")
    with pytest.raises(ValidationError):
        repository.rows_page(analysis_id, "model", cursor=first["next_cursor"], limit=0)
    with pytest.raises(ValidationError):
        repository.rows_page(analysis_id, "model", cursor=first["next_cursor"], limit=101)
    with pytest.raises(ValidationError):
        repository.rows_page(analysis_id, "unknown")
    with pytest.raises(RunNotFound):
        repository.rows_page("нет такого", "model")

    search_cursor = repository._encode_cursor([0])
    with pytest.raises(ValidationError):
        repository.rows_page(analysis_id, "model", cursor=search_cursor)


def test_search_rows_page_orders_and_hides_operation_ids(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)
    repository.replace_queries(analysis_id, [query(f"запрос {index}", index) for index in range(3)])
    repository.save_search_row(
        analysis_id, 0, status="found", operation_id="op-private-1",
        site_position=2, site_url="https://example.ru/a",
    )
    repository.save_search_row(analysis_id, 1, status="absent", operation_id="op-private-2")
    repository.save_search_row(analysis_id, 2, status="error", error="Сбой поиска")

    first = repository.rows_page(analysis_id, "search", limit=2)
    assert [(row["query_index"], row["status"]) for row in first["items"]] == [(0, "found"), (1, "absent")]
    assert first["items"][0]["site_position"] == 2
    assert first["items"][0]["site_url"] == "https://example.ru/a"
    assert first["items"][1]["site_position"] is None
    assert "op-private" not in json.dumps(first, ensure_ascii=False)
    assert set(first["items"][0]) == {
        "query_index", "query", "category", "service", "status", "site_position", "site_url", "error",
    }

    rest = repository.rows_page(analysis_id, "search", cursor=first["next_cursor"])
    assert [(row["query_index"], row["status"]) for row in rest["items"]] == [(2, "error")]
    assert rest["items"][0]["error"] == "Сбой поиска"
    assert rest["next_cursor"] is None


def test_resume_plan_separates_submitted_operations_from_unsubmitted_rows(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)
    repository.replace_queries(analysis_id, [query(f"запрос {index}", index) for index in range(5)])
    repository.save_search_row(analysis_id, 0, status="waiting", operation_id="op-0")
    repository.save_search_row(analysis_id, 1, status="submitting", operation_id="op-1")
    repository.save_search_row(
        analysis_id, 2, status="found", site_position=1, site_url="https://example.ru/",
    )
    repository.save_search_row(analysis_id, 3, status="pending")
    repository.save_model_row(analysis_id, "chatgpt", "ChatGPT", 0, status="pending")

    plan = repository.resume_plan(analysis_id)

    assert isinstance(plan, ResumePlan)
    assert plan.analysis_id == analysis_id
    assert plan.status == "running"
    assert plan.submitted == ((0, "op-0"), (1, "op-1"))
    assert plan.unsubmitted_query_indexes == (3,)
    assert plan.has_unfinished_model_rows is True
    assert plan.report_ready is False

    repository.update_stage(analysis_id, 6, "done")
    assert repository.resume_plan(analysis_id).report_ready is True
    with pytest.raises(RunNotFound):
        repository.resume_plan("нет такого")


def test_a_saved_outcome_keeps_the_stored_operation_id(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)
    repository.replace_queries(analysis_id, [query("запрос", 0)])
    repository.save_search_row(analysis_id, 0, status="waiting", operation_id="op-7")
    repository.save_search_row(
        analysis_id, 0, status="found", site_position=4, site_url="https://example.ru/",
    )

    assert repository.snapshot(analysis_id)["readiness"]["has_submitted_search_rows"] is False
    assert scalar(
        tmp_path / DB_FILE,
        "SELECT operation_id FROM seo_search_rows WHERE analysis_id=? AND query_index=0",
        (analysis_id,),
    ) == "op-7"


def test_interrupt_unsubmitted_rows_keeps_submitted_operations(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)
    repository.replace_queries(analysis_id, [query(f"запрос {index}", index) for index in range(3)])
    repository.save_search_row(analysis_id, 0, status="waiting", operation_id="op-0")
    repository.save_search_row(analysis_id, 1, status="pending")
    repository.save_search_row(analysis_id, 2, status="found", site_position=1)
    repository.save_model_row(analysis_id, "chatgpt", "ChatGPT", 0, status="pending")

    repository.interrupt_unsubmitted_rows(analysis_id)

    plan = repository.resume_plan(analysis_id)
    assert plan.submitted == ((0, "op-0"),)
    assert plan.unsubmitted_query_indexes == ()
    assert plan.has_unfinished_model_rows is False
    assert repository.snapshot(analysis_id)["status"] == "running"
    with pytest.raises(RunNotFound):
        repository.interrupt_unsubmitted_rows("нет такого")


def test_seed_rows_keep_their_operation_id_and_join_the_resume_plan(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)
    path = tmp_path / DB_FILE

    repository.save_seed_row(analysis_id, 0, status="submitting", operation_id="seed-op-0")
    repository.save_seed_row(analysis_id, 1, status="waiting", operation_id="seed-op-1")
    repository.save_seed_row(analysis_id, 2, status="submitting")
    repository.save_seed_row(analysis_id, 0, status="found")
    repository.save_seed_row(analysis_id, 2, status="error", error="Сбой поиска")

    plan = repository.resume_plan(analysis_id)
    assert plan.submitted_seeds == ((1, "seed-op-1"),)
    assert seed_states(path, analysis_id) == {
        0: ("found", "seed-op-0"),
        1: ("waiting", "seed-op-1"),
        2: ("error", None),
    }
    with pytest.raises(ValidationError):
        repository.save_seed_row(analysis_id, 0, status="unknown")
    with pytest.raises(ValidationError):
        repository.save_seed_row(analysis_id, -1, status="found")
    with pytest.raises(RunNotFound):
        repository.save_seed_row("нет такого", 0, status="found")


def test_interrupt_and_cancel_cover_pending_seed_rows(tmp_path):
    repository = seo_repo(tmp_path)
    path = tmp_path / DB_FILE

    resumable = create(repository)
    repository.save_seed_row(resumable, 0, status="waiting", operation_id="seed-op-0")
    repository.save_seed_row(resumable, 1, status="pending")
    repository.interrupt_unsubmitted_rows(resumable)

    assert seed_states(path, resumable) == {
        0: ("waiting", "seed-op-0"),
        1: ("interrupted", None),
    }
    assert repository.resume_plan(resumable).submitted_seeds == ((0, "seed-op-0"),)

    stopped = create(repository)
    repository.save_seed_row(stopped, 0, status="waiting", operation_id="seed-op-1")
    repository.mark_interrupted(stopped)

    assert seed_states(path, stopped) == {0: ("interrupted", "seed-op-1")}

    cancelled = create(repository)
    repository.save_seed_row(cancelled, 0, status="waiting", operation_id="seed-op-2")
    repository.save_seed_row(cancelled, 1, status="found")
    repository.cancel(cancelled)

    assert seed_states(path, cancelled) == {
        0: ("cancelled", "seed-op-2"),
        1: ("found", None),
    }


def test_running_analysis_ids_lists_only_running_analyses(tmp_path):
    repository = seo_repo(tmp_path)

    first = create(repository)
    second = create(repository)
    third = create(repository)
    repository.finish_analysis(second)
    repository.fail_analysis(third)

    assert set(repository.running_analysis_ids()) == {first}
    assert seo_repo(tmp_path).running_analysis_ids() == (first,)


def test_cancel_only_running_analyses_and_keeps_finished_rows(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)
    repository.replace_queries(analysis_id, [query(f"запрос {index}", index) for index in range(3)])
    repository.save_search_row(
        analysis_id, 0, status="found", site_position=1, site_url="https://example.ru/",
    )
    repository.save_search_row(analysis_id, 1, status="waiting", operation_id="op-1")
    repository.save_model_row(analysis_id, "chatgpt", "ChatGPT", 0, status="pending")

    repository.cancel(analysis_id)

    snapshot = repository.snapshot(analysis_id)
    assert snapshot["status"] == "cancelled"
    assert snapshot["finished_at"] is not None
    search = {
        row["query_index"]: row["status"]
        for row in repository.rows_page(analysis_id, "search")["items"]
    }
    assert search == {0: "found", 1: "cancelled"}
    assert repository.rows_page(analysis_id, "model")["items"][0]["status"] == "cancelled"
    with pytest.raises(RunConflict):
        repository.cancel(analysis_id)
    with pytest.raises(RunNotFound):
        repository.cancel("нет такого")


def test_delete_removes_only_terminal_analyses(tmp_path):
    repository = seo_repo(tmp_path)
    path = tmp_path / DB_FILE
    active = create(repository)
    with pytest.raises(RunConflict):
        repository.delete(active)

    finished = create(repository)
    repository.replace_queries(finished, [query("запрос", 0)])
    repository.save_search_row(finished, 0, status="found", site_position=1, site_url="https://example.ru/")
    repository.replace_candidates(finished, CANDIDATES)
    repository.save_candidate_hits(finished, 0, (CandidateHit("rival.ru", 2, None),))
    repository.save_model_row(finished, "chatgpt", "ChatGPT", 0, status="found", answer="да")
    repository.finish_analysis(finished)

    repository.delete(finished)

    with pytest.raises(RunNotFound):
        repository.snapshot(finished)
    for table in sorted(SEO_TABLES - {"seo_analyses"}):
        assert scalar(path, f"SELECT count(*) FROM {table} WHERE analysis_id=?", (finished,)) == 0
    assert scalar(path, "SELECT count(*) FROM seo_analyses") == 1

    interrupted = create(repository)
    repository.mark_interrupted(interrupted)
    repository.delete(interrupted)
    with pytest.raises(RunNotFound):
        repository.delete("нет такого")


def test_lifecycle_transitions_never_overwrite_a_final_state(tmp_path):
    repository = seo_repo(tmp_path)

    completed = create(repository)
    repository.finish_analysis(completed)
    assert repository.snapshot(completed)["status"] == "completed"
    repository.fail_analysis(completed)
    repository.mark_interrupted(completed)
    assert repository.snapshot(completed)["status"] == "completed"

    failed = create(repository)
    repository.fail_analysis(failed)
    repository.finish_analysis(failed)
    assert repository.snapshot(failed)["status"] == "failed"

    cancelled = create(repository)
    repository.cancel(cancelled)
    repository.finish_analysis(cancelled)
    assert repository.snapshot(cancelled)["status"] == "cancelled"

    stopped = create(repository)
    repository.replace_queries(stopped, [query("запрос", 0)])
    repository.save_search_row(stopped, 0, status="pending")
    repository.save_model_row(stopped, "chatgpt", "ChatGPT", 0, status="pending")
    repository.mark_interrupted(stopped)
    snapshot = repository.snapshot(stopped)
    assert snapshot["status"] == "interrupted"
    assert snapshot["finished_at"] is not None
    assert repository.rows_page(stopped, "search")["items"][0]["status"] == "interrupted"
    assert repository.rows_page(stopped, "model")["items"][0]["status"] == "interrupted"
    with pytest.raises(RunNotFound):
        repository.finish_analysis("нет такого")


def test_summary_is_stored_and_exposed_without_answers(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)
    assert repository.snapshot(analysis_id)["summary"] is None
    assert repository.snapshot(analysis_id)["readiness"]["summary_ready"] is False

    repository.save_summary(analysis_id, "Краткий итог")
    snapshot = repository.snapshot(analysis_id)
    assert snapshot["summary"] == "Краткий итог"
    assert snapshot["readiness"]["summary_ready"] is True

    repository.save_summary(analysis_id, None)
    assert repository.snapshot(analysis_id)["readiness"]["summary_ready"] is False


# -- step 7: concurrency -----------------------------------------------------


def test_two_instances_write_hundreds_of_rows_without_locking(tmp_path):
    first = seo_repo(tmp_path)
    analysis_id = create(first)
    second = SeoRepository(tmp_path)
    second.initialize()
    path = tmp_path / DB_FILE

    def write_models(repository: SeoRepository, connection_id: str) -> None:
        for query_index in range(100):
            repository.save_model_row(
                analysis_id, connection_id, connection_id.upper(), query_index,
                status="found", answer=f"ответ {connection_id} {query_index}",
                name_mentioned=query_index % 2 == 0,
            )

    def write_searches(repository: SeoRepository) -> None:
        for query_index in range(100):
            repository.save_search_row(
                analysis_id, query_index,
                status="found" if query_index % 3 else "absent",
                site_position=query_index % 10 + 1 if query_index % 3 else None,
                site_url="https://example.ru/" if query_index % 3 else None,
            )

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(write_models, first, "conn-a"),
            pool.submit(write_models, second, "conn-b"),
            pool.submit(write_models, first, "conn-c"),
            pool.submit(write_searches, second),
        ]
        for future in futures:
            future.result(timeout=60)

    assert scalar(
        path, "SELECT count(*) FROM seo_model_rows WHERE analysis_id=?", (analysis_id,),
    ) == 300
    assert scalar(
        path, "SELECT count(*) FROM seo_search_rows WHERE analysis_id=?", (analysis_id,),
    ) == 100
    page = seo_repo(tmp_path).list_page()["items"][0]
    assert page["counters"] == {
        "queries": 0, "search_rows": 100, "model_rows": 300, "search_errors": 0, "model_errors": 0,
    }
