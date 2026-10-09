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
AGENTS = ("supervisor", "site", "competitors", "queries", "checks")
LEGACY_TABLES = {"runs", "model_rows", "search_rows"}
SEO_TABLES = {
    "seo_analyses",
    "seo_stages",
    "seo_pages",
    "seo_candidates",
    "seo_queries",
    "seo_search_rows",
    "seo_search_documents",
    "seo_candidate_hits",
    "seo_model_rows",
    "seo_seed_rows",
    "seo_agents",
    "seo_agent_steps",
}
AGENT_TABLES = {"seo_agents", "seo_agent_steps"}
# The tool-layer tables of Task 2: they are new beside the revision-1 tables and
# a migrated version-3 file gains them empty.
DOCUMENT_TABLES = {"seo_search_documents"}
NEW_TABLES = AGENT_TABLES | DOCUMENT_TABLES
LEGACY_SEO_TABLES = SEO_TABLES - NEW_TABLES
# The SEO tables exactly as revision 1 (`user_version = 3`) wrote them: a real
# migrated file must keep them and gain the agent tables without a rewrite.
VERSION_THREE_SCHEMA = """
CREATE TABLE seo_analyses (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    url TEXT NOT NULL,
    host TEXT NOT NULL,
    sphere TEXT NOT NULL,
    seeds_json TEXT NOT NULL,
    input_services_json TEXT NOT NULL,
    connection_ids_json TEXT NOT NULL,
    estimate_json TEXT NOT NULL,
    company_name TEXT NOT NULL DEFAULT '',
    services_json TEXT NOT NULL,
    summary_text TEXT
);
CREATE TABLE seo_stages (
    analysis_id TEXT NOT NULL REFERENCES seo_analyses(id) ON DELETE CASCADE,
    stage INTEGER NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    counters_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (analysis_id, stage)
);
CREATE TABLE seo_pages (
    analysis_id TEXT NOT NULL REFERENCES seo_analyses(id) ON DELETE CASCADE,
    page_index INTEGER NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    PRIMARY KEY (analysis_id, page_index)
);
CREATE TABLE seo_candidates (
    analysis_id TEXT NOT NULL REFERENCES seo_analyses(id) ON DELETE CASCADE,
    candidate_index INTEGER NOT NULL,
    host TEXT NOT NULL,
    title TEXT NOT NULL,
    occurrences INTEGER NOT NULL,
    average_position REAL NOT NULL,
    seed_indexes_json TEXT NOT NULL,
    recurring INTEGER NOT NULL,
    PRIMARY KEY (analysis_id, candidate_index)
);
CREATE TABLE seo_queries (
    analysis_id TEXT NOT NULL REFERENCES seo_analyses(id) ON DELETE CASCADE,
    query_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    category TEXT NOT NULL,
    service TEXT,
    mentions_company_name INTEGER NOT NULL,
    mentions_company_host INTEGER NOT NULL,
    mentions_candidate_host INTEGER NOT NULL,
    branded INTEGER NOT NULL,
    PRIMARY KEY (analysis_id, query_index)
);
CREATE TABLE seo_search_rows (
    analysis_id TEXT NOT NULL REFERENCES seo_analyses(id) ON DELETE CASCADE,
    query_index INTEGER NOT NULL,
    status TEXT NOT NULL,
    operation_id TEXT,
    site_position INTEGER,
    site_url TEXT,
    error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (analysis_id, query_index)
);
CREATE TABLE seo_candidate_hits (
    analysis_id TEXT NOT NULL REFERENCES seo_analyses(id) ON DELETE CASCADE,
    query_index INTEGER NOT NULL,
    host TEXT NOT NULL,
    position INTEGER NOT NULL,
    url TEXT,
    PRIMARY KEY (analysis_id, query_index, host)
);
CREATE TABLE seo_model_rows (
    analysis_id TEXT NOT NULL REFERENCES seo_analyses(id) ON DELETE CASCADE,
    connection_id TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    query_index INTEGER NOT NULL,
    status TEXT NOT NULL,
    answer TEXT,
    name_mentioned INTEGER,
    host_mentioned INTEGER,
    error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (analysis_id, connection_id, query_index)
);
CREATE TABLE seo_seed_rows (
    analysis_id TEXT NOT NULL REFERENCES seo_analyses(id) ON DELETE CASCADE,
    seed_index INTEGER NOT NULL,
    status TEXT NOT NULL,
    operation_id TEXT,
    error TEXT,
    PRIMARY KEY (analysis_id, seed_index)
);
"""
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


def table_counts(path: Path, tables: set[str]) -> dict[str, int]:
    connection = sqlite3.connect(path)
    try:
        return {
            table: int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            for table in sorted(tables)
        }
    finally:
        connection.close()


def create_version_three_database(path: Path) -> str:
    """Write a populated version-3 database exactly as revision 1 left it."""
    analysis_id = "revision-one"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(LEGACY_SCHEMA)
        connection.executescript(VERSION_THREE_SCHEMA)
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
        connection.execute(
            "INSERT INTO seo_analyses (id, status, created_at, updated_at, finished_at, url, host, "
            "sphere, seeds_json, input_services_json, connection_ids_json, estimate_json, company_name, "
            "services_json, summary_text) "
            "VALUES (?, 'running', ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                analysis_id, "2026-09-25T15:00:00Z", "2026-09-25T15:00:00Z",
                "https://example.ru/", "example.ru", "Цветочный магазин",
                '["букет цветов", "доставка цветов", "розы"]', '["Букеты"]', '["chatgpt"]',
                '{"search": 23, "model": 40}', "Ромашка", '["Букеты", "Доставка"]',
            ),
        )
        connection.execute(
            "INSERT INTO seo_stages (analysis_id, stage, status, error, counters_json, updated_at) "
            "VALUES (?, 1, 'done', NULL, '{\"pages\": 2}', ?), (?, 2, 'done', NULL, '{}', ?)",
            (analysis_id, "2026-09-25T15:00:00Z", analysis_id, "2026-09-25T15:00:00Z"),
        )
        connection.execute(
            "INSERT INTO seo_pages (analysis_id, page_index, url, title) VALUES (?, 0, ?, ?), (?, 1, ?, ?)",
            (analysis_id, "https://example.ru/", "Главная",
             analysis_id, "https://example.ru/dostavka", "Доставка"),
        )
        connection.execute(
            "INSERT INTO seo_candidates (analysis_id, candidate_index, host, title, occurrences, "
            "average_position, seed_indexes_json, recurring) VALUES (?, 0, ?, ?, 3, 2.33, '[0, 1, 2]', 1)",
            (analysis_id, "rival.ru", "Соперник"),
        )
        connection.execute(
            "INSERT INTO seo_queries (analysis_id, query_index, text, category, service, "
            "mentions_company_name, mentions_company_host, mentions_candidate_host, branded) "
            "VALUES (?, 0, ?, 'commercial', 'Букеты', 0, 0, 0, 0), "
            "(?, 1, ?, 'informational', NULL, 0, 0, 1, 0)",
            (analysis_id, "букет цветов купить", analysis_id, "как выбрать букет"),
        )
        connection.execute(
            "INSERT INTO seo_search_rows (analysis_id, query_index, status, operation_id, site_position, "
            "site_url, error, updated_at) VALUES (?, 0, 'found', 'op-revision-one', 3, ?, NULL, ?)",
            (analysis_id, "https://example.ru/", "2026-09-25T15:00:00Z"),
        )
        connection.execute(
            "INSERT INTO seo_candidate_hits (analysis_id, query_index, host, position, url) "
            "VALUES (?, 0, 'rival.ru', 2, 'https://rival.ru/')",
            (analysis_id,),
        )
        connection.execute(
            "INSERT INTO seo_model_rows (analysis_id, connection_id, provider_name, query_index, status, "
            "answer, name_mentioned, host_mentioned, error, updated_at) "
            "VALUES (?, 'chatgpt', 'ChatGPT', 0, 'found', ?, 1, 0, NULL, ?)",
            (analysis_id, "Ромашка — да", "2026-09-25T15:00:00Z"),
        )
        connection.execute(
            "INSERT INTO seo_seed_rows (analysis_id, seed_index, status, operation_id, error) "
            "VALUES (?, 0, 'found', 'seed-op-revision-one', NULL)",
            (analysis_id,),
        )
        connection.execute("PRAGMA user_version=3")
        connection.commit()
    finally:
        connection.close()
    return analysis_id


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


def test_initialize_creates_seo_tables_and_reaches_version_six(tmp_path):
    repository = seo_repo(tmp_path)

    assert user_version(tmp_path / DB_FILE) == 6
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
    assert user_version(tmp_path / DB_FILE) == 6


def test_initialize_adds_a_missing_seo_table_to_an_existing_version_three_file(tmp_path):
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
    assert user_version(path) == 6
    analysis_id = create(repository)
    repository.save_seed_row(analysis_id, 0, status="waiting", operation_id="op-0")
    assert repository.resume_plan(analysis_id).submitted_seeds == ((0, "op-0"),)


def test_migration_from_a_populated_version_three_database_keeps_every_row(tmp_path):
    path = tmp_path / DB_FILE
    analysis_id = create_version_three_database(path)
    before = table_counts(path, LEGACY_SEO_TABLES)

    repository = seo_repo(tmp_path)

    assert user_version(path) == 6
    # Every revision-1 row is still there, including the ones outside the new tables.
    assert table_counts(path, LEGACY_SEO_TABLES) == before
    assert all(count > 0 for count in before.values())
    assert NEW_TABLES <= table_names(path)
    # The new tables start empty: a migrated analysis reports its agents as pending.
    assert table_counts(path, NEW_TABLES) == {table: 0 for table in sorted(NEW_TABLES)}
    snapshot = repository.snapshot(analysis_id)
    assert snapshot["status"] == "running"
    assert [agent["agent"] for agent in snapshot["agents"]] == list(AGENTS)
    assert {agent["status"] for agent in snapshot["agents"]} == {"pending"}
    assert snapshot["budget"]["pages"] == 2
    assert snapshot["budget"]["searches"] == 1
    # The same file still opens as plain run history.
    runs = RunRepository(tmp_path)
    runs.initialize()
    runs.recover_unfinished()
    saved = runs.get("legacy-run")
    assert saved["status"] == "done"
    assert saved["brand"] == "Ромашка"
    assert saved["search"][0]["position"] == 2


def test_migration_from_populated_version_two_keeps_runs_and_adds_seo(tmp_path):
    path = tmp_path / DB_FILE
    create_legacy_database(path)

    seo = seo_repo(tmp_path)

    assert user_version(path) == 6
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


def test_a_version_five_file_from_the_chat_migration_is_not_downgraded(tmp_path):
    """The chat repository owns version 5; opening the file must leave it there."""
    path = tmp_path / DB_FILE
    seo_repo(tmp_path)
    raw = sqlite3.connect(path)
    try:
        raw.execute("PRAGMA user_version=5")
        raw.commit()
    finally:
        raw.close()

    repository = seo_repo(tmp_path)

    assert user_version(path) == 6
    assert create(repository)


def test_newer_schema_version_is_refused_without_leaking_the_path(tmp_path):
    path = tmp_path / DB_FILE
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version=7")
    connection.commit()
    connection.close()

    with pytest.raises(StorageError) as raised:
        SeoRepository(tmp_path).initialize()
    assert str(path) not in str(raised.value)
    assert user_version(path) == 7


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
        "answer_mode": "text", "search_status": "not_requested", "search_results": [],
        "citations": [], "model": None, "search_calls": None,
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
    repository.upsert_agent(finished, "checks", "done")
    repository.append_step(finished, "checks", "model", "turn")
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


# -- step 3: agents, trace, and budget ---------------------------------------


TRACE_FIELDS = {
    "step_index", "agent", "kind", "name", "arguments", "result_summary", "status", "error",
    "created_at",
}


def test_create_analysis_seeds_five_pending_agents(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)

    agents = repository.agents(analysis_id)

    assert [agent["agent"] for agent in agents] == list(AGENTS)
    assert {agent["status"] for agent in agents} == {"pending"}
    assert [agent["error"] for agent in agents] == [None] * len(AGENTS)
    assert set(agents[0]) == {"agent", "status", "error", "updated_at"}
    with pytest.raises(RunNotFound):
        repository.agents("нет такого анализа")


def test_agent_upsert_validates_the_name_and_the_status(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)

    repository.upsert_agent(analysis_id, "site", "running")
    repository.upsert_agent(analysis_id, "site", "error", error="Сбой обхода")
    repository.upsert_agent(analysis_id, "checks", "waiting")

    agents = {agent["agent"]: agent for agent in repository.agents(analysis_id)}
    assert agents["site"]["status"] == "error"
    assert agents["site"]["error"] == "Сбой обхода"
    assert agents["checks"]["status"] == "waiting"
    assert agents["supervisor"]["status"] == "pending"

    repository.upsert_agent(analysis_id, "site", "done")
    agents = {agent["agent"]: agent for agent in repository.agents(analysis_id)}
    assert agents["site"]["status"] == "done"
    assert agents["site"]["error"] is None
    # The default rows survive a reopen: a fresh repository reads the same five agents.
    assert [agent["agent"] for agent in seo_repo(tmp_path).agents(analysis_id)] == list(AGENTS)

    with pytest.raises(ValidationError):
        repository.upsert_agent(analysis_id, "неизвестный агент", "done")
    with pytest.raises(ValidationError):
        repository.upsert_agent(analysis_id, "site", "готово")
    with pytest.raises(ValidationError):
        repository.upsert_agent(analysis_id, "site", "done", error=42)  # type: ignore[arg-type]
    with pytest.raises(RunNotFound):
        repository.upsert_agent("нет такого анализа", "site", "done")


def test_steps_are_ordered_monotonic_and_paged_by_cursor(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)

    indexes = [
        repository.append_step(analysis_id, "supervisor", "tool", "handoff_to",
                               arguments={"agent": "site"}, result_summary="передано"),
        repository.append_step(analysis_id, "site", "tool", "fetch_site",
                               arguments={"url": "https://example.ru/", "pages": 2},
                               result_summary="2 страницы"),
        repository.append_step(analysis_id, "site", "model", "turn", status="done"),
        repository.append_step(analysis_id, "site", "tool", "fetch_site", status="error",
                               error="Лимит прогона исчерпан"),
        repository.append_step(analysis_id, "checks", "system", "budget",
                               arguments={"pages": 2}, status="skipped"),
    ]

    assert indexes == [1, 2, 3, 4, 5]
    first = repository.trace_page(analysis_id, limit=2)
    assert [item["step_index"] for item in first["items"]] == [1, 2]
    assert first["next_cursor"] is not None
    assert set(first["items"][0]) == TRACE_FIELDS
    assert first["items"][0] == {
        "step_index": 1, "agent": "supervisor", "kind": "tool", "name": "handoff_to",
        "arguments": {"agent": "site"}, "result_summary": "передано", "status": "done", "error": None,
        "created_at": first["items"][0]["created_at"],
    }
    # `arguments` comes back as a parsed object, never as the stored JSON string.
    assert first["items"][1]["arguments"] == {"url": "https://example.ru/", "pages": 2}
    second = repository.trace_page(analysis_id, cursor=first["next_cursor"], limit=2)
    assert [item["step_index"] for item in second["items"]] == [3, 4]
    assert second["items"][1]["status"] == "error"
    assert second["items"][1]["error"] == "Лимит прогона исчерпан"
    assert second["items"][0]["arguments"] == {}
    assert second["items"][0]["result_summary"] is None
    third = repository.trace_page(analysis_id, cursor=second["next_cursor"], limit=2)
    assert [item["step_index"] for item in third["items"]] == [5]
    assert third["items"][0]["status"] == "skipped"
    assert third["next_cursor"] is None

    # A restarted repository keeps numbering the same trace.
    assert seo_repo(tmp_path).append_step(analysis_id, "checks", "model", "turn") == 6
    assert [item["step_index"] for item in repository.trace_page(analysis_id)["items"]] == [1, 2, 3, 4, 5, 6]
    assert repository.trace_page(analysis_id, limit=100)["next_cursor"] is None

    with pytest.raises(ValidationError):
        repository.trace_page(analysis_id, cursor="../bad")
    with pytest.raises(ValidationError):
        repository.trace_page(analysis_id, cursor="a" * 257)
    with pytest.raises(ValidationError):
        repository.trace_page(analysis_id, cursor=repository._encode_cursor(["не число"]))
    with pytest.raises(ValidationError):
        repository.trace_page(analysis_id, limit=0)
    with pytest.raises(ValidationError):
        repository.trace_page(analysis_id, limit=101)
    with pytest.raises(RunNotFound):
        repository.trace_page("нет такого анализа")
    with pytest.raises(RunNotFound):
        repository.append_step("нет такого анализа", "site", "tool", "fetch_site")


def test_step_append_validates_kind_agent_and_arguments(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)

    with pytest.raises(ValidationError):
        repository.append_step(analysis_id, "site", "unknown", "fetch_site")
    with pytest.raises(ValidationError):
        repository.append_step(analysis_id, "неизвестный агент", "tool", "fetch_site")
    with pytest.raises(ValidationError):
        repository.append_step(analysis_id, "site", "tool", "fetch_site", status="готово")
    with pytest.raises(ValidationError):
        repository.append_step(analysis_id, "site", "tool", "fetch_site", arguments=["не", "объект"])  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        repository.append_step(analysis_id, "site", "tool", "fetch_site", arguments={"плохо": object()})  # type: ignore[dict-item]
    with pytest.raises(ValidationError):
        repository.append_step(analysis_id, "site", "tool", "")
    assert repository.trace_page(analysis_id)["items"] == []


def test_step_indexes_stay_monotonic_under_concurrent_appends(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)
    per_worker = 20

    def append(indexes: list[int]) -> None:
        for _ in range(per_worker):
            indexes.append(repository.append_step(analysis_id, "checks", "tool", "read_checks"))

    with ThreadPoolExecutor(max_workers=4) as pool:
        results: list[list[int]] = [[], [], [], []]
        futures = [pool.submit(append, indexes) for indexes in results]
        for future in futures:
            future.result(timeout=60)

    returned = sorted(index for indexes in results for index in indexes)
    assert returned == list(range(1, len(results) * per_worker + 1))
    page = repository.trace_page(analysis_id, limit=100)
    assert [item["step_index"] for item in page["items"]] == returned


def test_budget_state_counts_every_saved_row(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)

    assert repository.budget_state(analysis_id) == {
        "pages": 0, "searches": 0, "seed_searches": 0, "model_rows": 0, "steps": 0,
        "tool_calls": 0, "handoffs": 0,
        "agent_steps": {agent: 0 for agent in AGENTS},
    }

    repository.save_site_facts(
        analysis_id, "Ромашка", ("Букеты",),
        (("https://example.ru/", "Главная"), ("https://example.ru/dostavka", "Доставка")),
    )
    repository.replace_queries(analysis_id, [query(f"запрос {index}", index) for index in range(3)])
    repository.save_search_row(analysis_id, 0, status="found", site_position=1)
    repository.save_search_row(analysis_id, 1, status="absent")
    repository.save_seed_row(analysis_id, 0, status="found")
    repository.save_model_row(analysis_id, "chatgpt", "ChatGPT", 0, status="found", answer="да")
    repository.save_model_row(analysis_id, "claude", "Claude", 0, status="found", answer="нет")
    repository.append_step(analysis_id, "supervisor", "tool", "handoff_to")
    repository.append_step(analysis_id, "site", "tool", "fetch_site")
    repository.append_step(analysis_id, "site", "model", "turn")
    repository.append_step(analysis_id, "checks", "system", "budget", status="skipped")

    budget = repository.budget_state(analysis_id)
    assert budget == {
        "pages": 2, "searches": 2, "seed_searches": 1, "model_rows": 2, "steps": 4,
        "tool_calls": 2, "handoffs": 1,
        "agent_steps": {
            "supervisor": 1, "site": 2, "competitors": 0, "queries": 0, "checks": 1,
        },
    }
    assert seo_repo(tmp_path).budget_state(analysis_id) == budget
    with pytest.raises(RunNotFound):
        repository.budget_state("нет такого анализа")


def test_snapshot_exposes_agents_budget_and_numbers_without_answers(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)
    repository.replace_queries(analysis_id, [query("запрос", 0)])
    repository.upsert_agent(analysis_id, "site", "error", error="Сбой обхода")
    repository.append_step(
        analysis_id, "site", "tool", "fetch_site",
        arguments={"url": "https://example.ru/"}, result_summary="2 страницы",
    )
    repository.append_step(analysis_id, "site", "tool", "fetch_site", status="error",
                           error="Лимит прогона исчерпан")
    repository.save_search_row(
        analysis_id, 0, status="found", operation_id="op-private-1", site_position=2,
        site_url="https://example.ru/",
    )
    repository.save_model_row(
        analysis_id, "chatgpt", "ChatGPT", 0, status="found", answer="секретный ответ модели",
        name_mentioned=True,
    )

    snapshot = repository.snapshot(analysis_id)

    assert set(snapshot) >= {
        "stages", "counters", "readiness", "aggregates", "agents", "budget",
    }
    assert [(agent["agent"], agent["status"]) for agent in snapshot["agents"]] == [
        ("supervisor", "pending"), ("site", "error"), ("competitors", "pending"),
        ("queries", "pending"), ("checks", "pending"),
    ]
    assert snapshot["agents"][1]["error"] == "Сбой обхода"
    assert snapshot["budget"]["steps"] == 2
    assert snapshot["budget"]["searches"] == 1
    assert snapshot["budget"]["tool_calls"] == 2
    assert snapshot["budget"]["agent_steps"]["site"] == 2
    # Answers and operation IDs stay inside the database, agents and budget included.
    payload = json.dumps(snapshot, ensure_ascii=False)
    assert "секретный ответ модели" not in payload
    assert "op-private-1" not in payload



# -- tool-layer persistence --------------------------------------------------


def test_pages_round_trip_in_crawl_order_and_are_replaced(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)

    assert repository.pages(analysis_id) == ()
    repository.save_pages(
        analysis_id,
        (("https://example.ru/", "Главная"), ("https://example.ru/dostavka", "Доставка")),
    )
    assert repository.pages(analysis_id) == (
        {"url": "https://example.ru/", "title": "Главная"},
        {"url": "https://example.ru/dostavka", "title": "Доставка"},
    )
    assert repository.snapshot(analysis_id)["pages"] == [
        {"url": "https://example.ru/", "title": "Главная"},
        {"url": "https://example.ru/dostavka", "title": "Доставка"},
    ]

    repository.save_pages(analysis_id, (("https://example.ru/about", "О нас"),))
    assert [page["url"] for page in repository.pages(analysis_id)] == ["https://example.ru/about"]
    assert repository.pages(analysis_id)[0]["title"] == "О нас"
    # The same rows survive a second repository instance.
    assert len(seo_repo(tmp_path).pages(analysis_id)) == 1

    with pytest.raises(ValidationError):
        repository.save_pages(analysis_id, ("https://example.ru/",))  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        repository.save_pages(analysis_id, ((1, "Главная"),))  # type: ignore[arg-type]
    with pytest.raises(RunNotFound):
        repository.save_pages("нет такого анализа", ())
    with pytest.raises(RunNotFound):
        repository.pages("нет такого анализа")


def test_search_documents_store_positions_and_replace_one_query(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)

    assert repository.search_documents(analysis_id, 0) is None
    repository.save_search_documents(
        analysis_id, 0,
        ((1, "https://rival.ru/", "Соперник"), (3, "https://example.ru/", "Ромашка")),
    )
    stored = repository.search_documents(analysis_id, 0)
    assert stored == {
        "status": "found",
        "documents": ((1, "https://rival.ru/", "Соперник"), (3, "https://example.ru/", "Ромашка")),
    }

    repository.save_search_documents(analysis_id, 0, ((2, "https://other.ru/", "Другой"),))
    assert repository.search_documents(analysis_id, 0)["documents"] == (
        (2, "https://other.ru/", "Другой"),
    )
    # Another query of the same analysis keeps its own documents.
    repository.save_search_documents(analysis_id, 1, ((1, "https://new.ru/", ""),))
    assert repository.search_documents(analysis_id, 0)["documents"] == (
        (2, "https://other.ru/", "Другой"),
    )

    with pytest.raises(ValidationError):
        repository.save_search_documents(analysis_id, 0, ((0, "https://rival.ru/", ""),))
    with pytest.raises(ValidationError):
        repository.save_search_documents(analysis_id, 0, ((11, "https://rival.ru/", ""),))
    with pytest.raises(ValidationError):
        repository.save_search_documents(analysis_id, 0, ((1, "", "Соперник"),))
    with pytest.raises(ValidationError):
        repository.save_search_documents(analysis_id, 0, ((1, "https://a.ru/", ""), (1, "https://b.ru/", "")))
    with pytest.raises(ValidationError):
        repository.save_search_documents(analysis_id, 0, (), status="неизвестно")
    with pytest.raises(ValidationError):
        repository.save_search_documents(analysis_id, 0, (), seed="да")  # type: ignore[arg-type]
    with pytest.raises(RunNotFound):
        repository.search_documents("нет такого анализа", 0)
    with pytest.raises(RunNotFound):
        repository.save_search_documents("нет такого анализа", 0, ())


def test_a_checked_empty_serp_is_stored_with_its_status(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)

    repository.save_search_documents(analysis_id, 0, (), status="absent")
    repository.save_search_documents(analysis_id, 0, (), status="error", seed=True)

    assert repository.search_documents(analysis_id, 0) == {"status": "absent", "documents": ()}
    # The key-query index space is separate from the generated one.
    assert repository.search_documents(analysis_id, 0, seed=True) == {"status": "error", "documents": ()}
    assert repository.search_documents(analysis_id, 0, seed=False) == {"status": "absent", "documents": ()}
    # A later successful check replaces the empty outcome.
    repository.save_search_documents(analysis_id, 0, ((1, "https://rival.ru/", "Rival"),))
    assert repository.search_documents(analysis_id, 0)["status"] == "found"


def test_deleting_an_analysis_removes_its_pages_and_documents(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)
    repository.save_pages(analysis_id, (("https://example.ru/", "Главная"),))
    repository.save_search_documents(analysis_id, 0, ((1, "https://rival.ru/", "Rival"),))
    repository.finish_analysis(analysis_id)

    repository.delete(analysis_id)

    assert table_counts(tmp_path / DB_FILE, DOCUMENT_TABLES) == {"seo_search_documents": 0}


def test_budget_exhaustion_is_flagged_on_the_analysis(tmp_path):
    repository = seo_repo(tmp_path)
    analysis_id = create(repository)

    assert repository.snapshot(analysis_id)["budget_exhausted"] is False

    repository.mark_budget_exhausted(analysis_id)

    assert repository.snapshot(analysis_id)["budget_exhausted"] is True
    # The flag never touches the lifecycle: the run still has to be closed.
    assert repository.snapshot(analysis_id)["status"] == "running"
    with pytest.raises(RunNotFound):
        repository.mark_budget_exhausted("нет такого анализа")


def test_a_version_four_database_gains_the_budget_flag_column(tmp_path):
    path = tmp_path / DB_FILE
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE seo_analyses (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            finished_at TEXT,
            url TEXT NOT NULL,
            host TEXT NOT NULL,
            sphere TEXT NOT NULL,
            seeds_json TEXT NOT NULL,
            input_services_json TEXT NOT NULL,
            connection_ids_json TEXT NOT NULL,
            estimate_json TEXT NOT NULL,
            company_name TEXT NOT NULL DEFAULT '',
            services_json TEXT NOT NULL,
            summary_text TEXT
        );
        PRAGMA user_version=4;
        """
    )
    connection.execute(
        "INSERT INTO seo_analyses (id, status, created_at, updated_at, url, host, sphere, "
        "seeds_json, input_services_json, connection_ids_json, estimate_json, services_json) "
        "VALUES ('old', 'running', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', "
        "'https://example.ru/', 'example.ru', 'Цветы', '[]', '[]', '[]', '{}', '[]')",
    )
    connection.commit()
    connection.close()

    repository = seo_repo(tmp_path)

    snapshot = repository.snapshot("old")
    assert snapshot["budget_exhausted"] is False
    repository.mark_budget_exhausted("old")
    assert repository.snapshot("old")["budget_exhausted"] is True
