"""The PostgreSQL pool: one per database, its log lines, and a fast failure."""

from __future__ import annotations

import logging
import time

import psycopg
import pytest

from app.core import database

LOGGER_NAME = "app.core.database"
UNREACHABLE = "postgresql://nobody@127.0.0.1:1/absent"


def server_dsn(**overrides: str) -> str:
    """A URL of the test server that has no pool yet, for a fresh pool.

    The test DSN carries the throwaway schema in `options`, so it is dropped:
    this helper only needs a second, untouched URL of the same server.
    """
    info = dict(psycopg.conninfo.conninfo_to_dict(database.database_url()))
    info.pop("options", None)
    info.update(overrides)
    return psycopg.conninfo.make_conninfo(**info)


@pytest.fixture
def fresh_pool(database_dsn: str):
    """A helper that gives one unused URL and closes the pools afterwards."""
    created: list[str] = []

    def make(**overrides: str) -> str:
        url = server_dsn(**overrides)
        created.append(url)
        return url

    yield make
    if created:
        database.close_pools()


def test_pool_is_created_once_per_url(database_dsn: str) -> None:
    first = database.pool(database_dsn)
    assert database.pool(database_dsn) is first
    assert first.min_size == database.POOL_MIN_SIZE


def test_pool_size_comes_from_the_environment() -> None:
    assert database.pool_max_size({"AI_TRACKER_DB_POOL_MAX_SIZE": "3"}) == 3
    for value in ("abc", "0", "-1", ""):
        assert database.pool_max_size({"AI_TRACKER_DB_POOL_MAX_SIZE": value}) == database.DEFAULT_POOL_MAX_SIZE
    assert database.pool_max_size({}) == database.DEFAULT_POOL_MAX_SIZE


def test_safe_target_hides_credentials_and_session_options() -> None:
    target = database.safe_target(
        "postgresql://user:secret@db.example:6000/app?options=-csearch_path%3Dhidden"
    )
    assert target == "db.example:6000/app"
    for hidden in ("user", "secret", "hidden", "options"):
        assert hidden not in target


def test_a_borrowed_connection_goes_back_and_is_not_closed(database_dsn: str) -> None:
    pool = database.pool(database_dsn)
    with database.connect(database_dsn) as connection:
        assert connection.execute("SELECT 1 AS value").fetchone()["value"] == 1
        connection.commit()
    stats = pool.get_stats()
    assert stats["connections_num"] - stats["pool_available"] == 0
    assert connection.raw.closed is False


def test_an_application_error_returns_a_clean_connection(database_dsn: str, caplog) -> None:
    """A repository that raises mid-transaction must not make the pool warn."""
    from app.core.errors import RunNotFound

    pool = database.pool(database_dsn)
    with (
        caplog.at_level(logging.WARNING, logger="psycopg.pool"),
        pytest.raises(RunNotFound),
        database.connect(database_dsn) as connection,
    ):
        connection.execute("SELECT 1")
        raise RunNotFound("нет такого")
    assert "rolling back returned connection" not in caplog.text
    assert pool.get_stats()["connections_num"] - pool.get_stats()["pool_available"] == 0


def test_an_autocommit_connection_bypasses_the_pool(database_dsn: str) -> None:
    with database.connect(database_dsn, autocommit=True) as direct:
        assert direct.execute("SELECT 1 AS value").fetchone()["value"] == 1
    assert direct.raw.closed is True


def test_the_first_connection_is_logged_without_the_dsn(fresh_pool, caplog) -> None:
    dsn = fresh_pool(dbname="postgres")
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        database.pool(dsn)

    messages = [record.getMessage() for record in caplog.records if record.name == LOGGER_NAME]
    assert any("Подключение к PostgreSQL установлено" in message for message in messages)
    assert any("postgres" in message for message in messages)
    for message in messages:
        for hidden in ("postgresql://", "options", "search_path", "password"):
            assert hidden not in message


def test_every_physical_connection_is_logged_at_debug(fresh_pool, caplog) -> None:
    dsn = fresh_pool(dbname="postgres")
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME), database.connect(dsn) as connection:
        connection.commit()

    messages = [record.getMessage() for record in caplog.records if record.name == LOGGER_NAME]
    assert any("Новое соединение с PostgreSQL" in message for message in messages)


def test_an_unreachable_database_fails_fast_without_the_url(caplog) -> None:
    started = time.perf_counter()
    with pytest.raises(database.OperationalError):
        database.connect(UNREACHABLE)
    elapsed = time.perf_counter() - started

    assert elapsed < database.POOL_TIMEOUT_SECONDS / 2
    messages = " ".join(record.getMessage() for record in caplog.records if record.name == LOGGER_NAME)
    assert "Не удалось подключиться к PostgreSQL" in messages
    # The target itself is safe to name; the credentials of the URL are not.
    assert "127.0.0.1:1/absent" in messages
    for hidden in ("postgresql://", "nobody"):
        assert hidden not in messages


def test_closing_the_pools_lets_a_later_use_create_them_again(database_dsn: str) -> None:
    first = database.pool(database_dsn)
    database.close_pools()
    assert first.closed is True
    second = database.pool(database_dsn)
    assert second is not first
    assert second.closed is False
