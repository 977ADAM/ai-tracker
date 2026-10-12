"""The legacy run tables leave the schema, and saved rows stop the drop."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from app.core import database
from tests.conftest import BASE_DSN, schema_dsn

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
FUSE_MESSAGE = "В таблице runs есть сохранённые прогоны"


def legacy_tables(dsn: str) -> set[str]:
    with database.connect(dsn) as connection:
        rows = connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()"
        ).fetchall()
    return {row["table_name"] for row in rows}


def run_alembic(dsn: str, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *arguments],
        cwd=BACKEND_ROOT,
        env={**os.environ, "AI_TRACKER_DATABASE_URL": dsn},
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_legacy_tables_are_gone(database_dsn):
    assert legacy_tables(database_dsn).isdisjoint({"runs", "model_rows", "search_rows"})


def test_the_migration_refuses_to_drop_saved_runs():
    name = "guard_" + uuid4().hex[:12]
    dsn = schema_dsn(BASE_DSN, name)
    admin = database.connect(BASE_DSN, autocommit=True)
    try:
        admin.execute(f'CREATE SCHEMA "{name}"')
        assert run_alembic(dsn, "upgrade", "0001_projects_root").returncode == 0
        with database.connect(dsn) as connection:
            connection.execute(
                "INSERT INTO projects VALUES(?,?,?,?,?)", ("p1", "{}", 1, "now", "now")
            )
            connection.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?)",
                ("r1", "p1", "now", None, "Бренд", "example.ru", "[]", "[]", "[]"),
            )
            # `with` closes the connection with a rollback, so the row is committed here.
            connection.commit()
        result = run_alembic(dsn, "upgrade", "head")
        assert result.returncode != 0
        assert FUSE_MESSAGE in (result.stderr + result.stdout)
        assert "runs" in legacy_tables(dsn)
    finally:
        admin.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
        admin.close()
        # The pool opened for the guard schema must not outlive it.
        database.close_pools()
