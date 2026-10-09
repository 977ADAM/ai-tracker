"""Shared fixtures: a migrated test schema, a temporary config dir, and a client.

The application keeps every durable row in PostgreSQL, so the suite runs against
a real server: one throwaway schema is created for the whole session, the Alembic
revisions are applied to it once, and every test starts from empty tables.

The server is the local Postgres.app default (`AI_TRACKER_DATABASE_URL`), or
`AI_TRACKER_TEST_DATABASE_URL` when a different database should be used. It is
never the database the application itself uses: the schema is random and is
dropped again at the end of the session.

`app.main` assembles the application at import, so the fixtures here swap its
container through FastAPI's dependency overrides instead of rebuilding the app.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import build_container, get_container
from app.core import database
from app.core.config import Settings
from app.db.connections import ConnectionRepository
from tests.fakes import TEST_PRESETS, MemorySecrets

# The Alembic command is the only migration entry point; the suite drives it
# exactly as a developer does, from the backend root.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"

# The trusted-host guard allows loopback only, so the test client speaks as 127.0.0.1.
TEST_BASE_URL = "http://127.0.0.1"

ENV_KEY_VARIABLES = (
    "DEEPSEEK_API_KEY",
    "YANDEX_SEARCH_API_KEY",
    "YANDEX_SEARCH_FOLDER_ID",
    # Legacy names for the same Yandex credentials.
    "API_KEY",
    "FOLDER_ID",
)

# Every table the application owns, in an order that satisfies foreign keys.
# `alembic_version` is deliberately absent: the schema must stay at head.
APPLICATION_TABLES = (
    "search_rows",
    "model_rows",
    "runs",
    "project_search_rows",
    "project_model_rows",
    "project_measurements",
    "projects",
)


def schema_dsn(base_dsn: str, name: str) -> str:
    """Address one schema of the server from the connection URL itself."""
    separator = "&" if "?" in base_dsn else "?"
    return f"{base_dsn}{separator}options={quote(f'-csearch_path={name}')}"


def truncate_all(dsn: str) -> None:
    """Empty every application table and restart its identity columns."""
    with database.connect(dsn) as connection:
        connection.execute(
            "TRUNCATE " + ", ".join(APPLICATION_TABLES) + " RESTART IDENTITY CASCADE"
        )
        connection.commit()


# One throwaway schema per test session. It is created before `app.main` is
# imported, because that module builds the application — and migrates the
# database — at import time; the test run must never touch the database the
# developer uses for the application itself.
SESSION_SCHEMA = f"test_{uuid4().hex[:12]}"
BASE_DSN = os.environ.get("AI_TRACKER_TEST_DATABASE_URL") or database.database_url()
TEST_DSN = schema_dsn(BASE_DSN, SESSION_SCHEMA)
os.environ["AI_TRACKER_DATABASE_URL"] = TEST_DSN


def _run_alembic(*arguments: str) -> None:
    """Apply migrations the way a developer does: through the Alembic CLI."""
    environment = dict(os.environ, AI_TRACKER_DATABASE_URL=TEST_DSN)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(arguments)} failed:\n{result.stderr}{result.stdout}")


def _prepare_database() -> None:
    admin = database.connect(BASE_DSN, autocommit=True)
    try:
        admin.execute(f'CREATE SCHEMA "{SESSION_SCHEMA}"')
    finally:
        admin.close()
    _run_alembic("upgrade", "head")


def _drop_database() -> None:
    admin = database.connect(BASE_DSN, autocommit=True)
    try:
        admin.execute(f'DROP SCHEMA "{SESSION_SCHEMA}" CASCADE')
    finally:
        admin.close()


_prepare_database()

from app.main import app as application


@pytest.fixture(scope="session", autouse=True)
def session_database() -> Iterator[str]:
    """Yield the migrated test schema and drop it when the session ends."""
    yield TEST_DSN
    # The pools of this process are closed before the schema they point at is
    # dropped, so no backend stays alive for the rest of the session.
    database.close_pools()
    _drop_database()


@pytest.fixture(scope="session")
def database_dsn(session_database: str) -> str:
    """The connection URL of the test schema addressed by every fixture."""
    return session_database


@pytest.fixture(autouse=True)
def clean_database(database_dsn: str) -> Iterator[None]:
    """Give every test empty tables, whatever a previous test left behind."""
    truncate_all(database_dsn)
    yield
    truncate_all(database_dsn)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every credential fallback out of tests unless one sets it itself.

    The application reads the repository `.env` at import, so a developer's own
    keys would otherwise reach the tests and turn a "missing credentials" case
    into a real paid call.
    """
    for variable in ENV_KEY_VARIABLES:
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def secrets() -> MemorySecrets:
    return MemorySecrets()


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def settings(config_dir: Path, database_dsn: str) -> Settings:
    """Test settings: a temporary config dir, the test database, and presets."""
    return Settings(config_dir=config_dir, database_url=database_dsn, presets=TEST_PRESETS)


@pytest.fixture
def repository(settings: Settings, secrets: MemorySecrets) -> ConnectionRepository:
    return ConnectionRepository(
        settings.config_dir,
        secrets,
        presets=settings.presets,
        env_api_key=settings.env_api_key,
        service_name=settings.service_name,
    )


@pytest.fixture
def make_client(
    settings: Settings,
    secrets: MemorySecrets,
) -> Iterator[Callable[..., TestClient]]:
    def build(
        *,
        client_options: dict[str, object] | None = None,
        **overrides: object,
    ) -> TestClient:
        # The container is built once, exactly like `app.main` builds it at
        # import: the search service keeps job state in memory, so every request
        # of one client must reach the same service.
        container = build_container(settings, secrets=secrets, **overrides)
        application.dependency_overrides[get_container] = lambda: container
        return TestClient(application, base_url=TEST_BASE_URL, **(client_options or {}))

    yield build
    application.dependency_overrides.clear()


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()
