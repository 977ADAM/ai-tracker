"""Additive schema and transactions for projects in the shared SQLite file."""

import base64
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.core.errors import StorageError, ValidationError


def stamp():
    return datetime.now(UTC).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def cursor_encode(value):
    return base64.urlsafe_b64encode(encode(value).encode()).decode().rstrip("=")


def cursor_decode(cursor):
    try:
        if not isinstance(cursor, str) or len(cursor) > 1000:
            raise ValueError
        return json.loads(
            base64.b64decode(
                cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
            )
        )
    except (ValueError, UnicodeError, TypeError) as exc:
        raise ValidationError("Некорректная страница истории") from exc


class ProjectStorage:
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.path = config_dir / "runs.sqlite3"

    @contextmanager
    def connection(self, write=False):
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=5)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=5000")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except sqlite3.Error as exc:
            if db:
                db.rollback()
            raise StorageError("Не удалось сохранить или прочитать проект") from exc
        finally:
            if db:
                db.close()

    def initialize(self):
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self.config_dir, 0o700)
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            os.chmod(self.path, 0o600)
        except OSError as exc:
            raise StorageError("Не удалось открыть хранилище проектов") from exc
        with self.connection() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] > 7:
                raise StorageError("Версия хранилища не поддерживается")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, input_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_measurements (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    snapshot_json TEXT NOT NULL, comparison_key TEXT NOT NULL, estimate_json TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_project_measurement
                    ON project_measurements(project_id) WHERE status='running';
                CREATE INDEX IF NOT EXISTS project_measurement_history ON project_measurements(project_id, created_at, id);
                CREATE TABLE IF NOT EXISTS project_model_rows (
                    measurement_id TEXT NOT NULL REFERENCES project_measurements(id) ON DELETE CASCADE,
                    query_index INTEGER NOT NULL, connection_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    evidence_json TEXT, brand_mentioned INTEGER NOT NULL DEFAULT 0, domain_mentioned INTEGER NOT NULL DEFAULT 0,
                    sentiment_status TEXT NOT NULL DEFAULT 'not_applicable', sentiment_json TEXT, error TEXT, sentiment_error TEXT,
                    PRIMARY KEY(measurement_id,query_index,connection_id)
                );
                CREATE TABLE IF NOT EXISTS project_search_rows (
                    measurement_id TEXT NOT NULL REFERENCES project_measurements(id) ON DELETE CASCADE,
                    query_index INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    operation_id TEXT, documents_json TEXT, error TEXT,
                    PRIMARY KEY(measurement_id,query_index)
                );
                PRAGMA user_version=7;
                COMMIT;
            """)
