"""Owner-only SQLite history for combined model and Yandex runs."""

from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.core.errors import RunConflict, RunNotFound, StorageError, ValidationError
from app.domain.models import PromptResult
from app.domain.runs import RunInput, summary_rows
from app.domain.search import REGIONS
from app.service.search import SearchRow

FILE_NAME = "runs.sqlite3"
STORAGE_FAILED = "Не удалось сохранить или прочитать историю проверок"
RUN_NOT_FOUND = "Прогон не найден"
RUN_ACTIVE = "Дождитесь завершения прогона"
INVALID_CURSOR = "Некорректная страница истории"
PENDING_MODEL = frozenset({"pending"})
PENDING_SEARCH = frozenset({"submitting", "waiting"})
CURSOR_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
REGION_NAMES = dict(REGIONS)


class RunRepository:
    """Small transactions keep every received row independently durable."""

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = Path(config_dir)
        self.path = self.config_dir / FILE_NAME

    def initialize(self) -> None:
        try:
            self.config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.config_dir, 0o700)
            descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(descriptor)
            os.chmod(self.path, 0o600)
        except OSError as exc:
            raise StorageError(STORAGE_FAILED) from exc
        with self._connection(write=True) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise StorageError(STORAGE_FAILED)
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    brand TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    prompts_json TEXT NOT NULL,
                    provider_ids_json TEXT NOT NULL,
                    regions_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_rows (
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    provider_id TEXT NOT NULL,
                    prompt_index INTEGER NOT NULL,
                    provider_name TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL,
                    answer TEXT,
                    mentioned INTEGER,
                    error TEXT,
                    PRIMARY KEY (run_id, provider_id, prompt_index)
                );
                CREATE TABLE IF NOT EXISTS search_rows (
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    search_index INTEGER NOT NULL,
                    prompt_index INTEGER NOT NULL,
                    region_index INTEGER NOT NULL,
                    prompt TEXT NOT NULL,
                    region_id INTEGER NOT NULL,
                    region_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    position INTEGER,
                    url TEXT,
                    error TEXT,
                    PRIMARY KEY (run_id, search_index)
                );
            """)
            if version == 0:
                connection.execute("PRAGMA user_version=1")

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.path, timeout=5)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except sqlite3.Error as exc:
            if connection is not None and write:
                connection.rollback()
            raise StorageError(STORAGE_FAILED) from exc
        except Exception:
            if connection is not None and write:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()

    def create(self, run_id: str, request: RunInput, provider_names: dict[str, str], created_at: str) -> None:
        with self._connection(write=True) as connection:
            connection.execute(
                "INSERT INTO runs VALUES (?, ?, NULL, ?, ?, ?, ?, ?)",
                (run_id, created_at, request.brand, request.domain,
                 json.dumps(request.prompts, ensure_ascii=False),
                 json.dumps(request.provider_ids), json.dumps(request.regions)),
            )
            connection.executemany(
                "INSERT INTO model_rows VALUES (?, ?, ?, ?, ?, 'pending', NULL, NULL, NULL)",
                [(run_id, provider_id, prompt_index, provider_names[provider_id], prompt)
                 for provider_id in request.provider_ids
                 for prompt_index, prompt in enumerate(request.prompts)],
            )
            connection.executemany(
                "INSERT INTO search_rows VALUES (?, ?, ?, ?, ?, ?, ?, 'submitting', NULL, NULL, NULL)",
                [(run_id, prompt_index * len(request.regions) + region_index, prompt_index,
                  region_index, prompt, region_id, REGION_NAMES[region_id])
                 for prompt_index, prompt in enumerate(request.prompts)
                 for region_index, region_id in enumerate(request.regions)],
            )

    def save_model(self, run_id: str, provider_id: str, prompt_index: int, result: PromptResult) -> None:
        with self._connection(write=True) as connection:
            updated = connection.execute(
                "UPDATE model_rows SET status=?, answer=?, mentioned=?, error=? "
                "WHERE run_id=? AND provider_id=? AND prompt_index=? AND status='pending'",
                (result.status, result.answer, int(result.mentioned) if result.mentioned is not None else None,
                 result.error, run_id, provider_id, prompt_index),
            )
            self._require_updated(connection, run_id, updated.rowcount)
            self._finish_if_terminal(connection, run_id)

    def save_search(self, run_id: str, search_index: int, row: SearchRow) -> None:
        if row.status not in {"found", "absent", "error"}:
            raise ValueError("Only terminal search rows can be saved")
        with self._connection(write=True) as connection:
            updated = connection.execute(
                "UPDATE search_rows SET status=?, position=?, url=?, error=? "
                "WHERE run_id=? AND search_index=? AND status IN ('submitting','waiting')",
                (row.status, row.position, row.url, row.error, run_id, search_index),
            )
            self._require_updated(connection, run_id, updated.rowcount)
            self._finish_if_terminal(connection, run_id)

    def fail_pending_branch(self, run_id: str, branch: Literal["model", "search"], message: str) -> None:
        if branch not in ("model", "search"):
            raise ValueError("Unknown run branch")
        table = "model_rows" if branch == "model" else "search_rows"
        pending = "status='pending'" if branch == "model" else "status IN ('submitting','waiting')"
        with self._connection(write=True) as connection:
            self._require_run(connection, run_id)
            connection.execute(
                f"UPDATE {table} SET status='error', error=? WHERE run_id=? AND {pending}",
                (message, run_id),
            )
            self._finish_if_terminal(connection, run_id)

    def interrupt_search(self, run_id: str) -> None:
        with self._connection(write=True) as connection:
            self._require_run(connection, run_id)
            connection.execute(
                "UPDATE search_rows SET status='interrupted' "
                "WHERE run_id=? AND status IN ('submitting','waiting')", (run_id,),
            )
            self._finish_if_terminal(connection, run_id)

    def recover_unfinished(self) -> None:
        with self._connection(write=True) as connection:
            connection.execute(
                "UPDATE model_rows SET status='interrupted' WHERE status='pending' "
                "AND run_id IN (SELECT id FROM runs WHERE finished_at IS NULL)"
            )
            connection.execute(
                "UPDATE search_rows SET status='interrupted' WHERE status IN ('submitting','waiting') "
                "AND run_id IN (SELECT id FROM runs WHERE finished_at IS NULL)"
            )
            for run in connection.execute("SELECT id FROM runs WHERE finished_at IS NULL").fetchall():
                self._finish_if_terminal(connection, run["id"])

    def get(self, run_id: str) -> dict:
        with self._connection() as connection:
            run = self._require_run(connection, run_id)
            models = [dict(row) for row in connection.execute(
                "SELECT provider_id, prompt_index, provider_name, prompt, status, answer, mentioned, error "
                "FROM model_rows WHERE run_id=? ORDER BY rowid", (run_id,),
            )]
            for row in models:
                row["mentioned"] = bool(row["mentioned"]) if row["mentioned"] is not None else None
            search = [dict(row) for row in connection.execute(
                "SELECT search_index, prompt_index, region_index, prompt, region_id, region_name, "
                "status, position, url, error FROM search_rows WHERE run_id=? ORDER BY search_index",
                (run_id,),
            )]
        try:
            prompts = json.loads(run["prompts_json"])
            provider_ids = tuple(json.loads(run["provider_ids_json"]))
            regions = tuple(json.loads(run["regions_json"]))
            interrupted = any(row["status"] == "interrupted" for row in (*models, *search))
            status = "pending" if run["finished_at"] is None else "interrupted" if interrupted else "done"
            return {
                "id": run["id"], "created_at": run["created_at"], "finished_at": run["finished_at"],
                "status": status, "brand": run["brand"], "domain": run["domain"],
                "prompts": prompts, "provider_ids": list(provider_ids), "regions": list(regions),
                "models": models, "search": search,
                "summary_rows": summary_rows(models, search, provider_ids=provider_ids, regions=regions),
            }
        except (ValueError, TypeError, KeyError) as exc:
            raise StorageError(STORAGE_FAILED) from exc

    def list_page(self, cursor: str | None = None, limit: int = 20) -> dict:
        if not 1 <= limit <= 100:
            raise ValidationError(INVALID_CURSOR)
        before = self._decode_cursor(cursor) if cursor is not None else None
        where = "WHERE (created_at, id) < (?, ?)" if before else ""
        params = (*before, limit + 1) if before else (limit + 1,)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT id, created_at, finished_at, prompts_json FROM runs {where} "
                "ORDER BY created_at DESC, id DESC LIMIT ?", params,
            ).fetchall()
        page = rows[:limit]
        items = []
        for row in page:
            snapshot = self.get(row["id"])
            items.append({
                "id": row["id"], "created_at": row["created_at"],
                "status": snapshot["status"], "prompts": snapshot["prompts"],
            })
        next_cursor = self._encode_cursor(page[-1]["created_at"], page[-1]["id"]) if len(rows) > limit else None
        return {"items": items, "next_cursor": next_cursor}

    def delete(self, run_id: str) -> None:
        with self._connection(write=True) as connection:
            run = self._require_run(connection, run_id)
            if run["finished_at"] is None:
                raise RunConflict(RUN_ACTIVE)
            connection.execute("DELETE FROM runs WHERE id=?", (run_id,))

    @staticmethod
    def _require_run(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise RunNotFound(RUN_NOT_FOUND)
        return row

    @classmethod
    def _require_updated(cls, connection: sqlite3.Connection, run_id: str, count: int) -> None:
        if count == 0:
            cls._require_run(connection, run_id)
            raise RunConflict("Результат прогона уже завершён")

    @staticmethod
    def _finish_if_terminal(connection: sqlite3.Connection, run_id: str) -> None:
        pending = connection.execute(
            "SELECT (SELECT count(*) FROM model_rows WHERE run_id=? AND status='pending') "
            "+ (SELECT count(*) FROM search_rows WHERE run_id=? AND status IN ('submitting','waiting'))",
            (run_id, run_id),
        ).fetchone()[0]
        if pending == 0:
            connection.execute(
                "UPDATE runs SET finished_at=COALESCE(finished_at, ?) WHERE id=?",
                (datetime.now(UTC).isoformat(), run_id),
            )

    @staticmethod
    def _encode_cursor(created_at: str, run_id: str) -> str:
        raw = json.dumps([created_at, run_id], separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[str, str]:
        if not isinstance(cursor, str) or CURSOR_PATTERN.fullmatch(cursor) is None:
            raise ValidationError(INVALID_CURSOR)
        try:
            raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
            value = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValidationError(INVALID_CURSOR) from exc
        if not isinstance(value, list) or len(value) != 2 or not all(isinstance(part, str) for part in value):
            raise ValidationError(INVALID_CURSOR)
        return value[0], value[1]
