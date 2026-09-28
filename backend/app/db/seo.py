"""Owner-only SQLite persistence for durable SEO analyses.

The SEO tables live in the existing `runs.sqlite3` beside the brand-check
tables. This repository owns the `user_version = 4` migration: it creates its
own tables and raises the schema version, while `RunRepository` keeps accepting
every supported version and stays the only owner of `runs`, `model_rows`, and
`search_rows`.

Revision 1 wrote the fixed six-stage tables at version 3. Version 4 keeps them
untouched — already-saved analyses stay readable and the old pipeline keeps
writing its stages — and adds the agent state, the agent trace, and the report
conclusions of the multi-agent run.

Durability rules of the SEO flow: an analysis exists before the first external
call, every finished row is committed in its own `BEGIN IMMEDIATE` transaction,
WAL plus a bounded `busy_timeout` keep hundreds of rows from locking the file,
and the deferred Yandex operation ID is stored so a restart resumes polling it
without paying twice. A trace step takes its `step_index` inside the same
`BEGIN IMMEDIATE` transaction that inserts it, so parallel tool calls can never
share an index. Secrets never reach these tables and operation IDs are never
returned by a read.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, get_args

from app.core.errors import RunConflict, RunNotFound, StorageError, ValidationError
from app.domain.seo import (
    Candidate,
    CandidateHit,
    GeneratedQuery,
    ModelRowValue,
    QueryFlags,
    SearchRowValue,
    SeoInput,
    SeoRowOutcome,
)
from app.domain.seo_report import build_report

FILE_NAME = "runs.sqlite3"
SCHEMA_VERSION = 4
BUSY_TIMEOUT_MS = 5000
STAGE_COUNT = 6
# The six agents of the supervised run, in the order every read reports them.
AGENTS = ("supervisor", "site", "competitors", "queries", "checks", "report")

STORAGE_FAILED = "Не удалось сохранить или прочитать SEO-анализ"
ANALYSIS_NOT_FOUND = "SEO-анализ не найден"
ANALYSIS_TERMINAL = "SEO-анализ уже завершён"
ANALYSIS_ACTIVE = "Дождитесь завершения SEO-анализа"
INVALID_INPUT = "Некорректные данные SEO-анализа"
INVALID_STAGE = "Неизвестный этап SEO-анализа"
INVALID_STAGE_STATUS = "Неизвестное состояние этапа SEO-анализа"
INVALID_ROW_STATUS = "Неизвестное состояние строки SEO-анализа"
INVALID_ROWS_KIND = "Неизвестный вид строк SEO-анализа"
INVALID_AGENT = "Неизвестный агент SEO-анализа"
INVALID_AGENT_STATUS = "Неизвестное состояние агента SEO-анализа"
INVALID_STEP_KIND = "Неизвестный вид шага трассы"
INVALID_STEP_STATUS = "Неизвестное состояние шага трассы"
INVALID_CURSOR = "Некорректная страница истории"
INVALID_ROWS_CURSOR = "Некорректная страница результатов"
INVALID_TRACE_CURSOR = "Некорректная страница трассы"

CURSOR_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")

SeoAnalysisStatus = Literal["running", "completed", "failed", "interrupted", "cancelled"]
SeoStageStatus = Literal["pending", "running", "done", "error", "skipped"]
AgentStatus = Literal["pending", "running", "waiting", "done", "error", "skipped"]
AgentStepKind = Literal["model", "tool", "handoff", "system"]

TERMINAL_ANALYSIS_STATUSES = frozenset({"completed", "failed", "interrupted", "cancelled"})
STAGE_STATUSES = frozenset(get_args(SeoStageStatus))
AGENT_STATUSES = frozenset(get_args(AgentStatus))
STEP_KINDS = frozenset(get_args(AgentStepKind))
# A trace step is normally `done`; `error` carries a safe failure text, `rejected`
# a refused tool call, and `pending`/`running` a step whose result is still open.
STEP_STATUSES = frozenset({"pending", "running", "done", "error", "rejected", "skipped"})

# Stored row vocabulary: `SeoRowOutcome` in `domain.seo` owns every final row
# value the report consumes. A deferred Yandex operation and a queued model call
# are additionally recorded with a pending status before their outcome is known,
# which is how `resume_plan` tells resumable rows from unfinished ones.
PENDING_ROW_STATUSES = frozenset({"pending", "submitting", "waiting"})
ERROR_ROW_STATUSES = frozenset({"error", "interrupted", "cancelled"})
FINAL_ROW_STATUSES = frozenset(get_args(SeoRowOutcome))
ROW_STATUSES = PENDING_ROW_STATUSES | FINAL_ROW_STATUSES
# Fixed literals built from the sets above: no user value ever reaches this SQL.
PENDING_SQL = "(" + ", ".join(f"'{status}'" for status in sorted(PENDING_ROW_STATUSES)) + ")"
ERROR_SQL = "(" + ", ".join(f"'{status}'" for status in sorted(ERROR_ROW_STATUSES)) + ")"

CHILD_TABLES = (
    "seo_stages",
    "seo_agents",
    "seo_agent_steps",
    "seo_conclusions",
    "seo_pages",
    "seo_candidates",
    "seo_queries",
    "seo_search_rows",
    "seo_candidate_hits",
    "seo_model_rows",
    "seo_seed_rows",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS seo_analyses (
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
CREATE TABLE IF NOT EXISTS seo_stages (
    analysis_id TEXT NOT NULL REFERENCES seo_analyses(id) ON DELETE CASCADE,
    stage INTEGER NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    counters_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (analysis_id, stage)
);
CREATE TABLE IF NOT EXISTS seo_pages (
    analysis_id TEXT NOT NULL REFERENCES seo_analyses(id) ON DELETE CASCADE,
    page_index INTEGER NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    PRIMARY KEY (analysis_id, page_index)
);
CREATE TABLE IF NOT EXISTS seo_candidates (
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
CREATE TABLE IF NOT EXISTS seo_queries (
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
CREATE TABLE IF NOT EXISTS seo_search_rows (
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
CREATE TABLE IF NOT EXISTS seo_candidate_hits (
    analysis_id TEXT NOT NULL REFERENCES seo_analyses(id) ON DELETE CASCADE,
    query_index INTEGER NOT NULL,
    host TEXT NOT NULL,
    position INTEGER NOT NULL,
    url TEXT,
    PRIMARY KEY (analysis_id, query_index, host)
);
CREATE TABLE IF NOT EXISTS seo_model_rows (
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
CREATE TABLE IF NOT EXISTS seo_seed_rows (
    analysis_id TEXT NOT NULL REFERENCES seo_analyses(id) ON DELETE CASCADE,
    seed_index INTEGER NOT NULL,
    status TEXT NOT NULL,
    operation_id TEXT,
    error TEXT,
    PRIMARY KEY (analysis_id, seed_index)
);
CREATE TABLE IF NOT EXISTS seo_agents (
    analysis_id TEXT NOT NULL REFERENCES seo_analyses(id) ON DELETE CASCADE,
    agent TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (analysis_id, agent)
);
CREATE TABLE IF NOT EXISTS seo_agent_steps (
    analysis_id TEXT NOT NULL REFERENCES seo_analyses(id) ON DELETE CASCADE,
    step_index INTEGER NOT NULL,
    agent TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    arguments_json TEXT NOT NULL DEFAULT '{}',
    result_summary TEXT,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (analysis_id, step_index)
);
CREATE TABLE IF NOT EXISTS seo_conclusions (
    analysis_id TEXT NOT NULL REFERENCES seo_analyses(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    recommendations TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (analysis_id)
);
"""

COUNTER_SELECT = (
    "(SELECT count(*) FROM seo_queries q WHERE q.analysis_id=a.id) AS queries, "
    "(SELECT count(*) FROM seo_search_rows r WHERE r.analysis_id=a.id) AS search_rows, "
    "(SELECT count(*) FROM seo_model_rows m WHERE m.analysis_id=a.id) AS model_rows, "
    f"(SELECT count(*) FROM seo_search_rows r WHERE r.analysis_id=a.id AND r.status IN {ERROR_SQL}) AS search_errors, "
    f"(SELECT count(*) FROM seo_model_rows m WHERE m.analysis_id=a.id AND m.status IN {ERROR_SQL}) AS model_errors"
)


@dataclass(frozen=True)
class ResumePlan:
    """What a restarted process may still do for one unfinished analysis.

    ``submitted`` holds ``(query_index, operation_id)`` of deferred Yandex
    operations of generated queries to poll without submitting them again;
    ``submitted_seeds`` holds ``(seed_index, operation_id)`` of the key-query
    operations that were already paid for in stage 2. ``unsubmitted_query_indexes``
    holds generated-query rows that were never sent and must be marked
    interrupted; ``has_unfinished_model_rows`` reports queued model calls that are
    never replayed after a restart. ``report_ready`` means the report stage already
    finished, so a resumed analysis may end up completed instead of interrupted.
    """

    analysis_id: str
    status: str
    submitted: tuple[tuple[int, str], ...]
    unsubmitted_query_indexes: tuple[int, ...]
    has_unfinished_model_rows: bool
    report_ready: bool
    submitted_seeds: tuple[tuple[int, str], ...] = ()


class SeoRepository:
    """Small transactions keep every received SEO row independently durable."""

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = Path(config_dir)
        self.path = self.config_dir / FILE_NAME

    def initialize(self) -> None:
        """Create the SEO tables and raise `user_version` to the SEO schema."""
        try:
            self.config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.config_dir, 0o700)
            descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(descriptor)
            os.chmod(self.path, 0o600)
        except OSError as exc:
            raise StorageError(STORAGE_FAILED) from exc
        version = self._read_version()
        if version > SCHEMA_VERSION:
            # A database written by a newer application version stays untouched.
            raise StorageError(STORAGE_FAILED)
        self._enable_wal()
        with self._connection(write=True) as connection:
            connection.executescript(SCHEMA)
            if version < SCHEMA_VERSION:
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _read_version(self) -> int:
        """Read `user_version` before any write, so a newer file is never touched."""
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000)
            return int(connection.execute("PRAGMA user_version").fetchone()[0])
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise StorageError(STORAGE_FAILED) from exc
        finally:
            if connection is not None:
                connection.close()

    def _enable_wal(self) -> None:
        """WAL and a bounded busy timeout: hundreds of rows must not lock the file.

        `journal_mode` is persistent and cannot be changed inside a transaction,
        so it is set on its own connection before the migration transaction.
        """
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            connection.commit()
        except sqlite3.Error as exc:
            raise StorageError(STORAGE_FAILED) from exc
        finally:
            if connection is not None:
                connection.close()

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except sqlite3.Error as exc:
            if connection is not None:
                connection.rollback()
            raise StorageError(STORAGE_FAILED) from exc
        except Exception:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _require_analysis(connection: sqlite3.Connection, analysis_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM seo_analyses WHERE id=?", (analysis_id,)).fetchone()
        if row is None:
            raise RunNotFound(ANALYSIS_NOT_FOUND)
        return row

    # -- writes ----------------------------------------------------------

    def create_analysis(self, input: SeoInput, estimate: Mapping[str, int]) -> str:
        """Write the durable analysis before the first external call.

        The returned identifier is generated by the server: opaque, URL-safe,
        and unrelated to any value the user typed.
        """
        if not isinstance(input, SeoInput):
            raise ValidationError(INVALID_INPUT)
        if not isinstance(estimate, Mapping):
            raise ValidationError(INVALID_INPUT)
        try:
            estimate_data = {str(key): int(value) for key, value in estimate.items()}
        except (TypeError, ValueError) as exc:
            raise ValidationError(INVALID_INPUT) from exc
        analysis_id = secrets.token_urlsafe(16)
        now = _now()
        with self._connection(write=True) as connection:
            connection.execute(
                "INSERT INTO seo_analyses (id, status, created_at, updated_at, finished_at, url, host, "
                "sphere, seeds_json, input_services_json, connection_ids_json, estimate_json, "
                "company_name, services_json, summary_text) "
                "VALUES (?, 'running', ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, '', ?, NULL)",
                (
                    analysis_id, now, now, input.url, input.host, input.sphere,
                    json.dumps(list(input.seeds), ensure_ascii=False),
                    json.dumps(list(input.services), ensure_ascii=False),
                    json.dumps(list(input.connection_ids), ensure_ascii=False),
                    json.dumps(estimate_data, ensure_ascii=False),
                    json.dumps(list(input.services), ensure_ascii=False),
                ),
            )
            connection.executemany(
                "INSERT INTO seo_stages (analysis_id, stage, status, error, counters_json, updated_at) "
                "VALUES (?, ?, 'pending', NULL, '{}', ?)",
                [(analysis_id, stage, now) for stage in range(1, STAGE_COUNT + 1)],
            )
            # The version-4 agent layer starts beside the frozen stage rows: the
            # old fixed pipeline keeps writing `seo_stages`, the supervisor
            # runtime reads and writes the six agent rows.
            connection.executemany(
                "INSERT INTO seo_agents (analysis_id, agent, status, error, updated_at) "
                "VALUES (?, ?, 'pending', NULL, ?)",
                [(analysis_id, agent, now) for agent in AGENTS],
            )
        return analysis_id

    def update_stage(
        self,
        analysis_id: str,
        stage: int,
        status: SeoStageStatus,
        *,
        error: str | None = None,
        counters: Mapping[str, int] | None = None,
    ) -> None:
        """Record one stage transition with its optional counters in one transaction."""
        if not _is_index(stage) or not 1 <= stage <= STAGE_COUNT:
            raise ValidationError(INVALID_STAGE)
        if status not in STAGE_STATUSES:
            raise ValidationError(INVALID_STAGE_STATUS)
        if error is not None and not isinstance(error, str):
            raise ValidationError(INVALID_INPUT)
        counters_data = _counters(counters)
        now = _now()
        with self._connection(write=True) as connection:
            self._require_analysis(connection, analysis_id)
            connection.execute(
                "INSERT INTO seo_stages (analysis_id, stage, status, error, counters_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(analysis_id, stage) DO UPDATE SET status=excluded.status, error=excluded.error, "
                "counters_json=excluded.counters_json, updated_at=excluded.updated_at",
                (analysis_id, stage, status, error, json.dumps(counters_data, ensure_ascii=False), now),
            )
            connection.execute("UPDATE seo_analyses SET updated_at=? WHERE id=?", (now, analysis_id))

    def save_site_facts(
        self,
        analysis_id: str,
        company_name: str,
        services: Sequence[str],
        pages: Sequence[tuple[str, str]],
    ) -> None:
        """Store the extracted company name, the merged services, and the crawled pages."""
        if not isinstance(company_name, str):
            raise ValidationError(INVALID_INPUT)
        merged = _text_sequence(services)
        page_rows = _pages(pages)
        now = _now()
        with self._connection(write=True) as connection:
            self._require_analysis(connection, analysis_id)
            connection.execute(
                "UPDATE seo_analyses SET company_name=?, services_json=?, updated_at=? WHERE id=?",
                (company_name.strip(), json.dumps(merged, ensure_ascii=False), now, analysis_id),
            )
            connection.execute("DELETE FROM seo_pages WHERE analysis_id=?", (analysis_id,))
            connection.executemany(
                "INSERT INTO seo_pages (analysis_id, page_index, url, title) VALUES (?, ?, ?, ?)",
                [(analysis_id, index, url, title) for index, (url, title) in enumerate(page_rows)],
            )

    def replace_candidates(self, analysis_id: str, candidates: Sequence[Candidate]) -> None:
        """Replace the ranked candidate list of one analysis."""
        rows = [_candidate_row(candidate) for candidate in candidates]
        now = _now()
        with self._connection(write=True) as connection:
            self._require_analysis(connection, analysis_id)
            connection.execute("DELETE FROM seo_candidates WHERE analysis_id=?", (analysis_id,))
            connection.executemany(
                "INSERT INTO seo_candidates (analysis_id, candidate_index, host, title, occurrences, "
                "average_position, seed_indexes_json, recurring) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (analysis_id, index, *row)
                    for index, row in enumerate(rows)
                ],
            )
            connection.execute("UPDATE seo_analyses SET updated_at=? WHERE id=?", (now, analysis_id))

    def replace_queries(self, analysis_id: str, queries: Sequence[GeneratedQuery]) -> None:
        """Replace the accepted generated queries, flags included."""
        rows = [_query_row(item) for item in queries]
        now = _now()
        with self._connection(write=True) as connection:
            self._require_analysis(connection, analysis_id)
            connection.execute("DELETE FROM seo_queries WHERE analysis_id=?", (analysis_id,))
            connection.executemany(
                "INSERT INTO seo_queries (analysis_id, query_index, text, category, service, "
                "mentions_company_name, mentions_company_host, mentions_candidate_host, branded) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(analysis_id, index, *row) for index, row in enumerate(rows)],
            )
            connection.execute("UPDATE seo_analyses SET updated_at=? WHERE id=?", (now, analysis_id))

    def save_search_row(
        self,
        analysis_id: str,
        query_index: int,
        *,
        status: SeoRowOutcome,
        operation_id: str | None = None,
        site_position: int | None = None,
        site_url: str | None = None,
        error: str | None = None,
    ) -> None:
        """Upsert one Yandex row.

        When a deferred operation is submitted, the row is stored with a pending
        status and its `operation_id`; the later outcome overwrites the status
        and keeps the stored operation ID (`COALESCE`), so a restart can still
        tell which operations were already paid for.
        """
        _require_index(query_index)
        _require_row_status(status)
        operation = _optional_str(operation_id)
        position = _optional_position(site_position)
        url = _optional_str(site_url)
        message = _optional_str(error)
        now = _now()
        with self._connection(write=True) as connection:
            self._require_analysis(connection, analysis_id)
            connection.execute(
                "INSERT INTO seo_search_rows (analysis_id, query_index, status, operation_id, "
                "site_position, site_url, error, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(analysis_id, query_index) DO UPDATE SET status=excluded.status, "
                "operation_id=COALESCE(excluded.operation_id, seo_search_rows.operation_id), "
                "site_position=excluded.site_position, site_url=excluded.site_url, "
                "error=excluded.error, updated_at=excluded.updated_at",
                (analysis_id, query_index, status, operation, position, url, message, now),
            )

    def save_seed_row(
        self,
        analysis_id: str,
        seed_index: int,
        *,
        status: SeoRowOutcome,
        operation_id: str | None = None,
        error: str | None = None,
    ) -> None:
        """Upsert one stage-2 key-query row.

        As with a generated-query row, submitting the deferred operation stores
        the pending status together with its ``operation_id``, and the later
        outcome keeps that ID through ``COALESCE`` so a restart still knows which
        key searches were already paid for and must only be polled again.
        """
        _require_index(seed_index)
        _require_row_status(status)
        operation = _optional_str(operation_id)
        message = _optional_str(error)
        with self._connection(write=True) as connection:
            self._require_analysis(connection, analysis_id)
            connection.execute(
                "INSERT INTO seo_seed_rows (analysis_id, seed_index, status, operation_id, error) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(analysis_id, seed_index) DO UPDATE SET status=excluded.status, "
                "operation_id=COALESCE(excluded.operation_id, seo_seed_rows.operation_id), "
                "error=excluded.error",
                (analysis_id, seed_index, status, operation, message),
            )

    def save_candidate_hits(
        self, analysis_id: str, query_index: int, hits: Sequence[CandidateHit],
    ) -> None:
        """Replace the top-ten hits of the recurring candidates of one query."""
        _require_index(query_index)
        rows = [_hit_row(hit) for hit in hits]
        with self._connection(write=True) as connection:
            self._require_analysis(connection, analysis_id)
            connection.execute(
                "DELETE FROM seo_candidate_hits WHERE analysis_id=? AND query_index=?",
                (analysis_id, query_index),
            )
            connection.executemany(
                "INSERT INTO seo_candidate_hits (analysis_id, query_index, host, position, url) "
                "VALUES (?, ?, ?, ?, ?)",
                [(analysis_id, query_index, *row) for row in rows],
            )

    def save_model_row(
        self,
        analysis_id: str,
        connection_id: str,
        provider_name: str,
        query_index: int,
        *,
        status: SeoRowOutcome,
        answer: str | None = None,
        name_mentioned: bool | None = None,
        host_mentioned: bool | None = None,
        error: str | None = None,
    ) -> None:
        """Upsert one model answer.

        A saved answer and its mention flags survive a later metadata-only
        upsert; the error message is always overwritten by the last write.
        """
        provider = _required_str(connection_id)
        name = _required_str(provider_name)
        _require_index(query_index)
        _require_row_status(status)
        text = _optional_str(answer)
        mentioned = _optional_bool(name_mentioned)
        host = _optional_bool(host_mentioned)
        message = _optional_str(error)
        now = _now()
        with self._connection(write=True) as connection:
            self._require_analysis(connection, analysis_id)
            connection.execute(
                "INSERT INTO seo_model_rows (analysis_id, connection_id, provider_name, query_index, "
                "status, answer, name_mentioned, host_mentioned, error, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(analysis_id, connection_id, query_index) DO UPDATE SET "
                "provider_name=excluded.provider_name, status=excluded.status, "
                "answer=COALESCE(excluded.answer, seo_model_rows.answer), "
                "name_mentioned=COALESCE(excluded.name_mentioned, seo_model_rows.name_mentioned), "
                "host_mentioned=COALESCE(excluded.host_mentioned, seo_model_rows.host_mentioned), "
                "error=excluded.error, updated_at=excluded.updated_at",
                (analysis_id, provider, name, query_index, status, text,
                 _flag(mentioned), _flag(host), message, now),
            )

    def save_summary(self, analysis_id: str, text: str | None) -> None:
        """Store the generated summary text, or clear it when it is unavailable."""
        if text is not None and not isinstance(text, str):
            raise ValidationError(INVALID_INPUT)
        now = _now()
        with self._connection(write=True) as connection:
            self._require_analysis(connection, analysis_id)
            connection.execute(
                "UPDATE seo_analyses SET summary_text=?, updated_at=? WHERE id=?",
                (text, now, analysis_id),
            )

    # -- agents, trace, and conclusions ----------------------------------

    def upsert_agent(
        self, analysis_id: str, agent: str, status: str, *, error: str | None = None,
    ) -> None:
        """Record one agent transition of one analysis.

        The agent name and the status come from fixed literals, and an unknown
        analysis fails like every other write. The upsert replaces the previous
        state, so `error` is cleared by a later status without an error.
        """
        _require_agent(agent)
        _require_agent_status(status)
        message = _optional_str(error)
        now = _now()
        with self._connection(write=True) as connection:
            self._require_analysis(connection, analysis_id)
            connection.execute(
                "INSERT INTO seo_agents (analysis_id, agent, status, error, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(analysis_id, agent) DO UPDATE SET status=excluded.status, "
                "error=excluded.error, updated_at=excluded.updated_at",
                (analysis_id, agent, status, message, now),
            )
            connection.execute("UPDATE seo_analyses SET updated_at=? WHERE id=?", (now, analysis_id))

    def agents(self, analysis_id: str) -> tuple[dict, ...]:
        """Return the six agents in fixed order; a missing row reads as `pending`.

        A database migrated from version 3 has no agent rows, so the fixed
        `pending` default is what makes an old analysis readable.
        """
        with self._connection() as connection:
            self._require_analysis(connection, analysis_id)
            return self._agents_in(connection, analysis_id)

    def append_step(
        self,
        analysis_id: str,
        agent: str,
        kind: str,
        name: str,
        *,
        arguments: Mapping[str, object] | None = None,
        result_summary: str | None = None,
        status: str = "done",
        error: str | None = None,
    ) -> int:
        """Append one trace step and return its monotonic `step_index`.

        The index is `MAX(step_index) + 1` read and inserted inside one
        `BEGIN IMMEDIATE` transaction: the write lock is already held when the
        maximum is read, so parallel tool calls of the same analysis can never
        receive the same index. Arguments are stored as JSON and returned as a
        parsed object; safe summaries and errors stay short by contract.
        """
        _require_agent(agent)
        _require_step_kind(kind)
        title = _required_str(name)
        _require_step_status(status)
        payload = _json_object(arguments)
        summary = _optional_str(result_summary)
        message = _optional_str(error)
        now = _now()
        with self._connection(write=True) as connection:
            self._require_analysis(connection, analysis_id)
            step_index = int(
                connection.execute(
                    "SELECT COALESCE(MAX(step_index), 0) + 1 FROM seo_agent_steps "
                    "WHERE analysis_id=?",
                    (analysis_id,),
                ).fetchone()[0]
            )
            connection.execute(
                "INSERT INTO seo_agent_steps (analysis_id, step_index, agent, kind, name, "
                "arguments_json, result_summary, status, error, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (analysis_id, step_index, agent, kind, title, payload, summary, status, message, now),
            )
            connection.execute("UPDATE seo_analyses SET updated_at=? WHERE id=?", (now, analysis_id))
        return step_index

    def save_conclusions(
        self, analysis_id: str, *, summary: str, recommendations: str, model: str,
    ) -> None:
        """Store the report agent's text block: model output beside server numbers."""
        _require_text(summary)
        _require_text(recommendations)
        model_name = _required_str(model)
        now = _now()
        with self._connection(write=True) as connection:
            self._require_analysis(connection, analysis_id)
            connection.execute(
                "INSERT INTO seo_conclusions (analysis_id, summary, recommendations, model, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(analysis_id) DO UPDATE SET summary=excluded.summary, "
                "recommendations=excluded.recommendations, model=excluded.model, "
                "created_at=excluded.created_at",
                (analysis_id, summary, recommendations, model_name, now),
            )
            connection.execute("UPDATE seo_analyses SET updated_at=? WHERE id=?", (now, analysis_id))

    # -- lifecycle -------------------------------------------------------

    def finish_analysis(self, analysis_id: str) -> None:
        """Move a running analysis to `completed`; a final state is never overwritten."""
        self._close_analysis(analysis_id, "completed")

    def fail_analysis(self, analysis_id: str) -> None:
        """Move a running analysis to `failed`; a cancelled analysis stays cancelled."""
        self._close_analysis(analysis_id, "failed")

    def _close_analysis(self, analysis_id: str, status: SeoAnalysisStatus) -> None:
        now = _now()
        with self._connection(write=True) as connection:
            row = self._require_analysis(connection, analysis_id)
            if row["status"] in TERMINAL_ANALYSIS_STATUSES:
                return
            connection.execute(
                "UPDATE seo_analyses SET status=?, finished_at=COALESCE(finished_at, ?), updated_at=? "
                "WHERE id=?",
                (status, now, now, analysis_id),
            )

    def cancel(self, analysis_id: str) -> None:
        """Cancel a running analysis: finished rows stay, unfinished rows are cancelled."""
        now = _now()
        with self._connection(write=True) as connection:
            row = self._require_analysis(connection, analysis_id)
            if row["status"] != "running":
                raise RunConflict(ANALYSIS_TERMINAL)
            connection.execute(
                "UPDATE seo_analyses SET status='cancelled', finished_at=?, updated_at=? WHERE id=?",
                (now, now, analysis_id),
            )
            connection.execute(
                f"UPDATE seo_search_rows SET status='cancelled', updated_at=? "
                f"WHERE analysis_id=? AND status IN {PENDING_SQL}",
                (now, analysis_id),
            )
            connection.execute(
                f"UPDATE seo_seed_rows SET status='cancelled' "
                f"WHERE analysis_id=? AND status IN {PENDING_SQL}",
                (analysis_id,),
            )
            connection.execute(
                f"UPDATE seo_model_rows SET status='cancelled', updated_at=? "
                f"WHERE analysis_id=? AND status IN {PENDING_SQL}",
                (now, analysis_id),
            )

    def running_analysis_ids(self) -> tuple[str, ...]:
        """Return the IDs of analyses a restarted process may still resume."""
        with self._connection() as connection:
            return tuple(
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM seo_analyses WHERE status='running' ORDER BY created_at, id"
                )
            )

    def mark_interrupted(self, analysis_id: str) -> None:
        """End an unfinished analysis as `interrupted`, keeping every finished row."""
        now = _now()
        with self._connection(write=True) as connection:
            row = self._require_analysis(connection, analysis_id)
            if row["status"] in TERMINAL_ANALYSIS_STATUSES:
                return
            connection.execute(
                "UPDATE seo_analyses SET status='interrupted', finished_at=COALESCE(finished_at, ?), "
                "updated_at=? WHERE id=?",
                (now, now, analysis_id),
            )
            self._interrupt_pending_rows(connection, analysis_id, now, include_submitted=True)

    def interrupt_unsubmitted_rows(self, analysis_id: str) -> None:
        """Interrupt every row a restart may never replay.

        Yandex rows without an operation ID were never submitted, and a model
        call is never repeated after a restart; both become `interrupted` while
        the analysis itself keeps running for the operations still being polled.
        """
        now = _now()
        with self._connection(write=True) as connection:
            self._require_analysis(connection, analysis_id)
            self._interrupt_pending_rows(connection, analysis_id, now, include_submitted=False)

    @staticmethod
    def _interrupt_pending_rows(
        connection: sqlite3.Connection, analysis_id: str, now: str, *, include_submitted: bool,
    ) -> None:
        guard = "" if include_submitted else "AND operation_id IS NULL "
        connection.execute(
            f"UPDATE seo_search_rows SET status='interrupted', updated_at=? "
            f"WHERE analysis_id=? {guard}AND status IN {PENDING_SQL}",
            (now, analysis_id),
        )
        connection.execute(
            f"UPDATE seo_seed_rows SET status='interrupted' "
            f"WHERE analysis_id=? {guard}AND status IN {PENDING_SQL}",
            (analysis_id,),
        )
        connection.execute(
            f"UPDATE seo_model_rows SET status='interrupted', updated_at=? "
            f"WHERE analysis_id=? AND status IN {PENDING_SQL}",
            (now, analysis_id),
        )

    def delete(self, analysis_id: str) -> None:
        """Delete a terminal analysis and every row it owns."""
        with self._connection(write=True) as connection:
            row = self._require_analysis(connection, analysis_id)
            if row["status"] not in TERMINAL_ANALYSIS_STATUSES:
                raise RunConflict(ANALYSIS_ACTIVE)
            for table in CHILD_TABLES:
                connection.execute(f"DELETE FROM {table} WHERE analysis_id=?", (analysis_id,))
            connection.execute("DELETE FROM seo_analyses WHERE id=?", (analysis_id,))

    # -- reads -----------------------------------------------------------

    def snapshot(self, analysis_id: str) -> dict:
        """Return stages, agent state, budget, conclusions, facts, and aggregates.

        Saved model answers and Yandex operation IDs are deliberately absent:
        the detail page reads them from `rows_page` instead, and the trace keeps
        only safe arguments and short results.
        """
        with self._connection() as connection:
            row = self._require_analysis(connection, analysis_id)
            return self._snapshot(connection, row)

    def trace_page(self, analysis_id: str, cursor: str | None = None, limit: int = 100) -> dict:
        """Return one page of the agent trace, oldest step first.

        The cursor is the base64url `step_index` of the last returned step, so
        new steps arriving between two pages never shift the window; a malformed
        cursor is a validation error and an unknown analysis is not found.
        `arguments_json` is parsed before it leaves the repository.
        """
        if not _is_index(limit) or not 1 <= limit <= 100:
            raise ValidationError(INVALID_TRACE_CURSOR)
        with self._connection() as connection:
            self._require_analysis(connection, analysis_id)
            after = (
                self._decode_cursor(cursor, (int,), INVALID_TRACE_CURSOR)
                if cursor is not None
                else None
            )
            where = "AND step_index > ?" if after else ""
            params: tuple = (analysis_id, *after, limit + 1) if after else (analysis_id, limit + 1)
            rows = connection.execute(
                "SELECT step_index, agent, kind, name, arguments_json, result_summary, status, "
                f"error, created_at FROM seo_agent_steps WHERE analysis_id=? {where} "
                "ORDER BY step_index LIMIT ?",
                params,
            ).fetchall()
            page = rows[:limit]
            items = [
                {
                    "step_index": row["step_index"],
                    "agent": row["agent"],
                    "kind": row["kind"],
                    "name": row["name"],
                    "arguments": _json_read(row["arguments_json"]),
                    "result_summary": row["result_summary"],
                    "status": row["status"],
                    "error": row["error"],
                    "created_at": row["created_at"],
                }
                for row in page
            ]
        key: list | None = [page[-1]["step_index"]] if len(rows) > limit else None
        return {"items": items, "next_cursor": self._encode_cursor(key) if key else None}

    def conclusions(self, analysis_id: str) -> dict | None:
        """Return the stored model text block, or `None` while it is missing."""
        with self._connection() as connection:
            self._require_analysis(connection, analysis_id)
            return self._conclusions_in(connection, analysis_id)

    def budget_state(self, analysis_id: str) -> dict:
        """Count the resources a run already spent, from its saved rows alone.

        Pages, searches, seed searches, and model rows come from their tables;
        steps, tool calls (`kind = 'tool'`), and handoffs (`name = 'handoff_to'`)
        come from the trace. `agent_steps` counts the trace by agent and always
        names all six agents, so a reader sees zeroes instead of missing keys.
        """
        with self._connection() as connection:
            self._require_analysis(connection, analysis_id)
            return self._budget_state(connection, analysis_id)

    def list_page(self, cursor: str | None = None, limit: int = 20) -> dict:
        """Return one light history page, newest first, without building reports."""
        if not _is_index(limit) or not 1 <= limit <= 100:
            raise ValidationError(INVALID_CURSOR)
        before = self._decode_cursor(cursor, (str, str), INVALID_CURSOR) if cursor is not None else None
        where = "WHERE (a.created_at, a.id) < (?, ?)" if before else ""
        params: tuple = (*before, limit + 1) if before else (limit + 1,)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT a.id, a.created_at, a.finished_at, a.status, a.sphere, a.host, "
                f"a.company_name, {COUNTER_SELECT} FROM seo_analyses a {where} "
                "ORDER BY a.created_at DESC, a.id DESC LIMIT ?",
                params,
            ).fetchall()
            page = rows[:limit]
            items = [
                {
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "finished_at": row["finished_at"],
                    "status": row["status"],
                    "sphere": row["sphere"],
                    "host": row["host"],
                    "company_name": row["company_name"],
                    "counters": {
                        "queries": row["queries"],
                        "search_rows": row["search_rows"],
                        "model_rows": row["model_rows"],
                        "search_errors": row["search_errors"],
                        "model_errors": row["model_errors"],
                    },
                }
                for row in page
            ]
        next_cursor = (
            self._encode_cursor([page[-1]["created_at"], page[-1]["id"]])
            if len(rows) > limit
            else None
        )
        return {"items": items, "next_cursor": next_cursor}

    def rows_page(
        self,
        analysis_id: str,
        kind: Literal["model", "search"],
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Return one page of saved model answers or Yandex rows.

        Model rows are ordered by query index and then by connection; Yandex
        rows by query index alone. The cursor is the base64url sort key of
        the last returned row and a malformed cursor is a validation error.
        Yandex operation IDs stay inside the database.
        """
        if kind not in ("model", "search"):
            raise ValidationError(INVALID_ROWS_KIND)
        if not _is_index(limit) or not 1 <= limit <= 100:
            raise ValidationError(INVALID_ROWS_CURSOR)
        with self._connection() as connection:
            self._require_analysis(connection, analysis_id)
            if kind == "model":
                before = (
                    self._decode_cursor(cursor, (int, str), INVALID_ROWS_CURSOR)
                    if cursor is not None
                    else None
                )
                where = "AND (m.query_index, m.connection_id) > (?, ?)" if before else ""
                params: tuple = (analysis_id, *before, limit + 1) if before else (analysis_id, limit + 1)
                rows = connection.execute(
                    "SELECT m.query_index, m.connection_id, m.provider_name, m.status, m.answer, "
                    "m.name_mentioned, m.host_mentioned, m.error, q.text AS query, "
                    "q.category AS category, q.service AS service "
                    "FROM seo_model_rows m LEFT JOIN seo_queries q "
                    "ON q.analysis_id=m.analysis_id AND q.query_index=m.query_index "
                    f"WHERE m.analysis_id=? {where} "
                    "ORDER BY m.query_index, m.connection_id LIMIT ?",
                    params,
                ).fetchall()
                page = rows[:limit]
                items = [
                    {
                        "query_index": row["query_index"],
                        "connection_id": row["connection_id"],
                        "provider_name": row["provider_name"],
                        "status": row["status"],
                        "answer": row["answer"],
                        "name_mentioned": _optional_flag(row["name_mentioned"]),
                        "host_mentioned": _optional_flag(row["host_mentioned"]),
                        "error": row["error"],
                        "query": row["query"],
                        "category": row["category"],
                        "service": row["service"],
                    }
                    for row in page
                ]
                key: list | None = (
                    [page[-1]["query_index"], page[-1]["connection_id"]] if len(rows) > limit else None
                )
            else:
                before = (
                    self._decode_cursor(cursor, (int,), INVALID_ROWS_CURSOR)
                    if cursor is not None
                    else None
                )
                where = "AND r.query_index > ?" if before else ""
                params = (analysis_id, *before, limit + 1) if before else (analysis_id, limit + 1)
                rows = connection.execute(
                    "SELECT r.query_index, r.status, r.site_position, r.site_url, r.error, "
                    "q.text AS query, q.category AS category, q.service AS service "
                    "FROM seo_search_rows r LEFT JOIN seo_queries q "
                    "ON q.analysis_id=r.analysis_id AND q.query_index=r.query_index "
                    f"WHERE r.analysis_id=? {where} "
                    "ORDER BY r.query_index LIMIT ?",
                    params,
                ).fetchall()
                page = rows[:limit]
                items = [
                    {
                        "query_index": row["query_index"],
                        "query": row["query"],
                        "category": row["category"],
                        "service": row["service"],
                        "status": row["status"],
                        "site_position": row["site_position"],
                        "site_url": row["site_url"],
                        "error": row["error"],
                    }
                    for row in page
                ]
                key = [page[-1]["query_index"]] if len(rows) > limit else None
        return {"items": items, "next_cursor": self._encode_cursor(key) if key else None}

    def resume_plan(self, analysis_id: str) -> ResumePlan:
        """Describe the work a restarted process may still do for one analysis."""
        with self._connection() as connection:
            row = self._require_analysis(connection, analysis_id)
            submitted = tuple(
                (item["query_index"], item["operation_id"])
                for item in connection.execute(
                    "SELECT query_index, operation_id FROM seo_search_rows WHERE analysis_id=? "
                    "AND operation_id IS NOT NULL "
                    f"AND status IN {PENDING_SQL} ORDER BY query_index",
                    (analysis_id,),
                )
            )
            unsubmitted = tuple(
                item["query_index"]
                for item in connection.execute(
                    "SELECT query_index FROM seo_search_rows WHERE analysis_id=? "
                    f"AND operation_id IS NULL AND status IN {PENDING_SQL} ORDER BY query_index",
                    (analysis_id,),
                )
            )
            submitted_seeds = tuple(
                (item["seed_index"], item["operation_id"])
                for item in connection.execute(
                    "SELECT seed_index, operation_id FROM seo_seed_rows WHERE analysis_id=? "
                    f"AND operation_id IS NOT NULL AND status IN {PENDING_SQL} ORDER BY seed_index",
                    (analysis_id,),
                )
            )
            unfinished_models = connection.execute(
                f"SELECT count(*) FROM seo_model_rows WHERE analysis_id=? AND status IN {PENDING_SQL}",
                (analysis_id,),
            ).fetchone()[0]
            return ResumePlan(
                analysis_id=analysis_id,
                status=row["status"],
                submitted=submitted,
                unsubmitted_query_indexes=unsubmitted,
                has_unfinished_model_rows=unfinished_models > 0,
                report_ready=self._report_ready(connection, analysis_id, row["status"]),
                submitted_seeds=submitted_seeds,
            )

    @staticmethod
    def _report_ready(connection: sqlite3.Connection, analysis_id: str, status: str) -> bool:
        """The report is final when the analysis completed or stage 6 is done."""
        if status == "completed":
            return True
        stage_six = connection.execute(
            "SELECT status FROM seo_stages WHERE analysis_id=? AND stage=?",
            (analysis_id, STAGE_COUNT),
        ).fetchone()
        return stage_six is not None and stage_six["status"] == "done"

    @staticmethod
    def _encode_cursor(value: Sequence[object]) -> str:
        raw = json.dumps(list(value), separators=(",", ":"), ensure_ascii=False).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str, kinds: tuple[type, ...], message: str) -> tuple:
        """Decode one cursor into its sort key, or raise a validation error."""
        if not isinstance(cursor, str) or CURSOR_PATTERN.fullmatch(cursor) is None:
            raise ValidationError(message)
        try:
            raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
            value = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValidationError(message) from exc
        if not isinstance(value, list) or len(value) != len(kinds):
            raise ValidationError(message)
        for item, kind in zip(value, kinds, strict=True):
            if kind is int:
                if not _is_index(item):
                    raise ValidationError(message)
            elif not isinstance(item, kind):
                raise ValidationError(message)
        return tuple(value)

    def _snapshot(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
        analysis_id = row["id"]
        pages = [
            {"url": page["url"], "title": page["title"]}
            for page in connection.execute(
                "SELECT url, title FROM seo_pages WHERE analysis_id=? ORDER BY page_index",
                (analysis_id,),
            )
        ]
        candidates = tuple(
            Candidate(
                host=candidate["host"],
                title=candidate["title"],
                occurrences=candidate["occurrences"],
                average_position=candidate["average_position"],
                seed_indexes=tuple(_loads(candidate["seed_indexes_json"], [])),
                recurring=bool(candidate["recurring"]),
            )
            for candidate in connection.execute(
                "SELECT host, title, occurrences, average_position, seed_indexes_json, recurring "
                "FROM seo_candidates WHERE analysis_id=? ORDER BY candidate_index",
                (analysis_id,),
            )
        )
        queries = tuple(
            GeneratedQuery(
                text=item["text"],
                category=item["category"],
                service=item["service"],
                flags=QueryFlags(
                    mentions_company_name=bool(item["mentions_company_name"]),
                    mentions_company_host=bool(item["mentions_company_host"]),
                    mentions_candidate_host=bool(item["mentions_candidate_host"]),
                    branded=bool(item["branded"]),
                ),
            )
            for item in connection.execute(
                "SELECT text, category, service, mentions_company_name, mentions_company_host, "
                "mentions_candidate_host, branded FROM seo_queries WHERE analysis_id=? "
                "ORDER BY query_index",
                (analysis_id,),
            )
        )
        searches = tuple(
            SearchRowValue(
                query_index=item["query_index"],
                status=item["status"],
                site_position=item["site_position"],
                site_url=item["site_url"],
                error=item["error"],
            )
            for item in connection.execute(
                "SELECT query_index, status, site_position, site_url, error FROM seo_search_rows "
                "WHERE analysis_id=? ORDER BY query_index",
                (analysis_id,),
            )
        )
        models = tuple(
            ModelRowValue(
                connection_id=item["connection_id"],
                query_index=item["query_index"],
                status=item["status"],
                answer=item["answer"],
                name_mentioned=_optional_flag(item["name_mentioned"]),
                host_mentioned=_optional_flag(item["host_mentioned"]),
                error=item["error"],
            )
            for item in connection.execute(
                "SELECT connection_id, query_index, status, answer, name_mentioned, host_mentioned, "
                "error FROM seo_model_rows WHERE analysis_id=? ORDER BY query_index, connection_id",
                (analysis_id,),
            )
        )
        hits: dict[int, list[CandidateHit]] = {}
        for hit in connection.execute(
            "SELECT query_index, host, position, url FROM seo_candidate_hits WHERE analysis_id=? "
            "ORDER BY query_index, position",
            (analysis_id,),
        ):
            hits.setdefault(hit["query_index"], []).append(
                CandidateHit(host=hit["host"], position=hit["position"], url=hit["url"])
            )
        services = tuple(_loads(row["services_json"], []))
        request = SeoInput(
            url=row["url"],
            host=row["host"],
            sphere=row["sphere"],
            seeds=tuple(_loads(row["seeds_json"], [])),
            services=tuple(_loads(row["input_services_json"], [])),
            connection_ids=tuple(_loads(row["connection_ids_json"], [])),
        )
        aggregates = build_report(
            request, row["company_name"], services, candidates, queries, searches, models,
            candidate_hits=hits,
        )
        return {
            "id": analysis_id,
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "finished_at": row["finished_at"],
            "input": {
                "url": request.url,
                "host": request.host,
                "sphere": request.sphere,
                "seeds": list(request.seeds),
                "services": list(request.services),
                "connection_ids": list(request.connection_ids),
            },
            "estimate": _loads(row["estimate_json"], {}),
            "company_name": row["company_name"],
            "services": list(services),
            "pages": pages,
            "stages": self._stages(connection, analysis_id),
            "agents": list(self._agents_in(connection, analysis_id)),
            "budget": self._budget_state(connection, analysis_id),
            "candidates": [_plain(candidate) for candidate in candidates],
            "queries": [
                {
                    "index": index,
                    "text": item.text,
                    "category": item.category,
                    "service": item.service,
                    "flags": _plain(item.flags),
                }
                for index, item in enumerate(queries)
            ],
            "summary": row["summary_text"],
            "conclusions": self._conclusions_in(connection, analysis_id),
            "counters": _row_counters(searches, models, len(queries)),
            "readiness": self._readiness(connection, row, queries, searches, models),
            "aggregates": _plain(aggregates),
        }

    def _stages(self, connection: sqlite3.Connection, analysis_id: str) -> list[dict]:
        return [
            {
                "stage": stage["stage"],
                "status": stage["status"],
                "error": stage["error"],
                "counters": _loads(stage["counters_json"], {}),
                "updated_at": stage["updated_at"],
            }
            for stage in connection.execute(
                "SELECT stage, status, error, counters_json, updated_at FROM seo_stages "
                "WHERE analysis_id=? ORDER BY stage",
                (analysis_id,),
            )
        ]

    @staticmethod
    def _agents_in(connection: sqlite3.Connection, analysis_id: str) -> tuple[dict, ...]:
        """Project the stored agent rows onto the fixed six-agent order."""
        stored = {
            row["agent"]: row
            for row in connection.execute(
                "SELECT agent, status, error, updated_at FROM seo_agents WHERE analysis_id=?",
                (analysis_id,),
            )
        }
        return tuple(
            {
                "agent": agent,
                "status": stored[agent]["status"] if agent in stored else "pending",
                "error": stored[agent]["error"] if agent in stored else None,
                "updated_at": stored[agent]["updated_at"] if agent in stored else None,
            }
            for agent in AGENTS
        )

    @staticmethod
    def _conclusions_in(connection: sqlite3.Connection, analysis_id: str) -> dict | None:
        row = connection.execute(
            "SELECT summary, recommendations, model, created_at FROM seo_conclusions "
            "WHERE analysis_id=?",
            (analysis_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "summary": row["summary"],
            "recommendations": row["recommendations"],
            "model": row["model"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _budget_state(connection: sqlite3.Connection, analysis_id: str) -> dict:
        counts = connection.execute(
            "SELECT (SELECT count(*) FROM seo_pages WHERE analysis_id=?) AS pages, "
            "(SELECT count(*) FROM seo_search_rows WHERE analysis_id=?) AS searches, "
            "(SELECT count(*) FROM seo_seed_rows WHERE analysis_id=?) AS seed_searches, "
            "(SELECT count(*) FROM seo_model_rows WHERE analysis_id=?) AS model_rows, "
            "(SELECT count(*) FROM seo_agent_steps WHERE analysis_id=?) AS steps, "
            "(SELECT count(*) FROM seo_agent_steps WHERE analysis_id=? AND kind='tool') "
            "AS tool_calls, "
            "(SELECT count(*) FROM seo_agent_steps WHERE analysis_id=? AND name='handoff_to') "
            "AS handoffs",
            (analysis_id,) * 7,
        ).fetchone()
        agent_steps = {agent: 0 for agent in AGENTS}
        for row in connection.execute(
            "SELECT agent, count(*) AS steps FROM seo_agent_steps WHERE analysis_id=? GROUP BY agent",
            (analysis_id,),
        ):
            agent_steps[row["agent"]] = row["steps"]
        return {
            "pages": counts["pages"],
            "searches": counts["searches"],
            "seed_searches": counts["seed_searches"],
            "model_rows": counts["model_rows"],
            "steps": counts["steps"],
            "tool_calls": counts["tool_calls"],
            "handoffs": counts["handoffs"],
            "agent_steps": agent_steps,
        }

    def _readiness(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        queries: Sequence[GeneratedQuery],
        searches: Sequence[SearchRowValue],
        models: Sequence[ModelRowValue],
    ) -> dict:
        prepared = connection.execute(
            f"SELECT (SELECT count(*) FROM seo_search_rows WHERE analysis_id=? AND "
            f"operation_id IS NOT NULL AND status IN {PENDING_SQL}) AS submitted, "
            f"(SELECT count(*) FROM seo_search_rows WHERE analysis_id=? AND "
            f"operation_id IS NULL AND status IN {PENDING_SQL}) AS unsubmitted",
            (row["id"], row["id"]),
        ).fetchone()
        return {
            "report_ready": self._report_ready(connection, row["id"], row["status"]),
            "summary_ready": row["summary_text"] is not None,
            "queries_ready": bool(queries),
            "has_submitted_search_rows": prepared["submitted"] > 0,
            "has_unsubmitted_search_rows": prepared["unsubmitted"] > 0,
            "has_unfinished_model_rows": any(
                model.status in PENDING_ROW_STATUSES for model in models
            ),
            "search_rows": len(searches),
            "model_rows": len(models),
        }



# -- helpers -----------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _is_index(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_index(value: object) -> None:
    if not _is_index(value) or value < 0:  # type: ignore[operator]
        raise ValidationError(INVALID_INPUT)


def _require_row_status(status: object) -> None:
    if status not in ROW_STATUSES:
        raise ValidationError(INVALID_ROW_STATUS)


def _require_agent(agent: object) -> None:
    if agent not in AGENTS:
        raise ValidationError(INVALID_AGENT)


def _require_agent_status(status: object) -> None:
    if status not in AGENT_STATUSES:
        raise ValidationError(INVALID_AGENT_STATUS)


def _require_step_kind(kind: object) -> None:
    if kind not in STEP_KINDS:
        raise ValidationError(INVALID_STEP_KIND)


def _require_step_status(status: object) -> None:
    if status not in STEP_STATUSES:
        raise ValidationError(INVALID_STEP_STATUS)


def _require_text(value: object) -> str:
    """Accept any text, including an empty one, but never another type."""
    if not isinstance(value, str):
        raise ValidationError(INVALID_INPUT)
    return value


def _json_object(arguments: Mapping[str, object] | None) -> str:
    """Serialize safe step arguments, refusing a non-mapping or a non-JSON value."""
    if arguments is None:
        return "{}"
    if not isinstance(arguments, Mapping):
        raise ValidationError(INVALID_INPUT)
    try:
        return json.dumps(dict(arguments), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError(INVALID_INPUT) from exc


def _json_read(value: object) -> dict:
    """Parse stored step arguments back into an object."""
    parsed = _loads(value, {})
    return parsed if isinstance(parsed, dict) else {}


def _required_str(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(INVALID_INPUT)
    return value.strip()


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(INVALID_INPUT)
    return value


def _optional_position(value: object) -> int | None:
    """A 1-based SERP position; the report itself keeps only the top ten."""
    if value is None:
        return None
    if not _is_index(value) or value < 1:  # type: ignore[operator]
        raise ValidationError(INVALID_INPUT)
    return value  # type: ignore[return-value]


def _optional_bool(value: object) -> bool | None:
    if value is None or isinstance(value, bool):
        return value  # type: ignore[return-value]
    raise ValidationError(INVALID_INPUT)


def _optional_flag(value: object) -> bool | None:
    return bool(value) if value is not None else None


def _flag(value: bool | None) -> int | None:
    return int(value) if value is not None else None


def _counters(counters: Mapping[str, int] | None) -> dict[str, int]:
    if counters is None:
        return {}
    if not isinstance(counters, Mapping):
        raise ValidationError(INVALID_INPUT)
    result: dict[str, int] = {}
    for key, value in counters.items():
        if not isinstance(key, str) or not _is_index(value):
            raise ValidationError(INVALID_INPUT)
        result[key] = int(value)
    return result


def _text_sequence(value: object) -> list[str]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValidationError(INVALID_INPUT)
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValidationError(INVALID_INPUT)
        result.append(item.strip())
    return result


def _pages(value: object) -> list[tuple[str, str]]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValidationError(INVALID_INPUT)
    result: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, Sequence) or isinstance(item, str) or len(item) != 2:
            raise ValidationError(INVALID_INPUT)
        url, title = item
        if not isinstance(url, str) or not isinstance(title, str):
            raise ValidationError(INVALID_INPUT)
        result.append((url, title))
    return result


def _candidate_row(candidate: object) -> tuple[str, str, int, float, str, int]:
    if not isinstance(candidate, Candidate):
        raise ValidationError(INVALID_INPUT)
    return (
        candidate.host,
        candidate.title,
        candidate.occurrences,
        candidate.average_position,
        json.dumps(list(candidate.seed_indexes)),
        int(candidate.recurring),
    )


def _query_row(query: object) -> tuple[str, str, str | None, int, int, int, int]:
    if not isinstance(query, GeneratedQuery) or not isinstance(query.flags, QueryFlags):
        raise ValidationError(INVALID_INPUT)
    return (
        query.text,
        query.category,
        query.service,
        int(query.flags.mentions_company_name),
        int(query.flags.mentions_company_host),
        int(query.flags.mentions_candidate_host),
        int(query.flags.branded),
    )


def _hit_row(hit: object) -> tuple[str, int, str | None]:
    if not isinstance(hit, CandidateHit):
        raise ValidationError(INVALID_INPUT)
    _require_index(hit.position)
    _optional_str(hit.url)
    return (hit.host, hit.position, hit.url)


def _loads(value: object, default: object) -> object:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except ValueError as exc:
        raise StorageError(STORAGE_FAILED) from exc
    return default if parsed is None else parsed


def _plain(value: object) -> object:
    """Turn dataclasses, mappings, and tuples into JSON-ready values."""
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _plain(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _row_counters(
    searches: Sequence[SearchRowValue],
    models: Sequence[ModelRowValue],
    queries: int,
) -> dict[str, int]:
    return {
        "queries": queries,
        "search_rows": len(searches),
        "model_rows": len(models),
        "search_errors": sum(1 for row in searches if row.status in ERROR_ROW_STATUSES),
        "model_errors": sum(1 for row in models if row.status in ERROR_ROW_STATUSES),
    }
