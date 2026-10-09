"""Alembic environment: the target database comes from the application settings.

`AI_TRACKER_DATABASE_URL` is the only source of the target database, exactly as
at runtime, so `alembic upgrade head` and the application always agree on where
the schema lives. The URL is rewritten to SQLAlchemy's psycopg (v3) dialect,
because the application talks to PostgreSQL through psycopg 3.

Migrations run against one database at a time. The URL can also be injected
through the Alembic `Config` attributes (`ai_tracker_database_url`), which is how
the test suite points the CLI at its throwaway schema.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

# The backend root must be importable when Alembic is started from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import DATABASE_URL_VARIABLE, DEFAULT_DATABASE_URL

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# The migrations are raw SQL: there is no declarative metadata to compare against.
target_metadata = None


def sqlalchemy_url(dsn: str) -> str:
    """Rewrite a connection URL into SQLAlchemy's psycopg (v3) dialect."""
    for prefix in ("postgresql://", "postgres://"):
        if dsn.startswith(prefix):
            return "postgresql+psycopg://" + dsn[len(prefix) :]
    return dsn


def database_url() -> str:
    """The URL of the database to migrate."""
    injected = config.attributes.get("ai_tracker_database_url")
    if injected:
        return str(injected)
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    return sqlalchemy_url(os.environ.get(DATABASE_URL_VARIABLE) or DEFAULT_DATABASE_URL)


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(database_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
