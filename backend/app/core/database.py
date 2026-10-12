from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Self

import psycopg
import psycopg_pool
from psycopg import errors as psycopg_errors
from psycopg.rows import dict_row

from app.core.config import DATABASE_URL_VARIABLE, DEFAULT_DATABASE_URL

Error = psycopg.Error
IntegrityError = psycopg_errors.IntegrityError
OperationalError = psycopg.OperationalError
UniqueViolation = psycopg_errors.UniqueViolation
ForeignKeyViolation = psycopg_errors.ForeignKeyViolation

POOL_MIN_SIZE = 1
DEFAULT_POOL_MAX_SIZE = 8
POOL_TIMEOUT_SECONDS = 5.0
POOL_MAX_SIZE_VARIABLE = "AI_TRACKER_DB_POOL_MAX_SIZE"

LOGGER = logging.getLogger(__name__)

_POOLS: dict[str, psycopg_pool.ConnectionPool] = {}
_POOLS_LOCK = threading.Lock()

_IGNORED_PREFIXES = ("begin", "commit", "rollback", "pragma", "vacuum", "analyze")
_PLACEHOLDER = "?"


class Row(dict):
    """A result row addressable by column name and by column position."""

    __slots__ = ()

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class Result:
    """The slice of a driver cursor the repositories use."""

    def __init__(self, cursor: psycopg.Cursor) -> None:
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def description(self) -> Any:
        return self._cursor.description

    def fetchone(self) -> Row | None:
        row = self._cursor.fetchone()
        return None if row is None else Row(row)

    def fetchall(self) -> list[Row]:
        return [Row(row) for row in self._cursor.fetchall()]

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())

    def close(self) -> None:
        self._cursor.close()


def database_url(env: Mapping[str, str] | None = None) -> str:
    """The configured database, defaulting to the local Postgres.app server."""
    source = os.environ if env is None else env
    value = source.get(DATABASE_URL_VARIABLE)
    return value.strip() if value and value.strip() else DEFAULT_DATABASE_URL


def pool_max_size(env: Mapping[str, str] | None = None) -> int:
    """The per-process connection ceiling; a bad value keeps the default."""
    source = os.environ if env is None else env
    raw = source.get(POOL_MAX_SIZE_VARIABLE)
    try:
        value = int(str(raw).strip()) if raw is not None else DEFAULT_POOL_MAX_SIZE
    except (TypeError, ValueError):
        return DEFAULT_POOL_MAX_SIZE
    return value if value >= POOL_MIN_SIZE else DEFAULT_POOL_MAX_SIZE


def safe_target(dsn: str) -> str:
    """`host:port/database` of one connection URL — never the user or the password.

    Logs may name the database they reached, so every message about the
    connection goes through here: the DSN itself carries credentials.
    """
    try:
        info = psycopg.conninfo.conninfo_to_dict(dsn)
    except psycopg.Error:
        return "?"
    host = info.get("host") or "localhost"
    port = info.get("port") or "5432"
    database = info.get("dbname") or "?"
    return f"{host}:{port}/{database}"


def _adapt(value: Any) -> Any:
    """PostgreSQL has no implicit boolean-to-integer cast for a parameter."""
    return int(value) if isinstance(value, bool) else value


def _adapt_params(params: Sequence[Any]) -> tuple[Any, ...]:
    return tuple(_adapt(value) for value in params)


def _translate(sql: str) -> str:
    """Rewrite `?` placeholders as `%s` and escape every other percent sign.

    Quoted strings, quoted identifiers, and line comments are copied verbatim so
    a `?` or a `%` inside a literal is never mistaken for syntax.
    """
    output: list[str] = []
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if char == "'" or char == '"':
            quote = char
            output.append(char)
            index += 1
            while index < length:
                output.append(sql[index])
                if sql[index] == quote:
                    if index + 1 < length and sql[index + 1] == quote:
                        index += 1
                        output.append(sql[index])
                    else:
                        break
                index += 1
            index += 1
        elif char == "-" and sql.startswith("--", index):
            end = sql.find("\n", index)
            end = length if end == -1 else end
            output.append(sql[index:end])
            index = end
        elif char == _PLACEHOLDER:
            output.append("%s")
            index += 1
        elif char == "%":
            output.append("%%")
            index += 1
        else:
            output.append(char)
            index += 1
    return "".join(output)


def _split_script(script: str) -> list[str]:
    """Split a DDL script on semicolons that are not inside a literal."""
    statements: list[str] = []
    current: list[str] = []
    index = 0
    length = len(script)
    while index < length:
        char = script[index]
        if char == "'" or char == '"':
            quote = char
            current.append(char)
            index += 1
            while index < length:
                current.append(script[index])
                if script[index] == quote:
                    if index + 1 < length and script[index + 1] == quote:
                        index += 1
                        current.append(script[index])
                    else:
                        break
                index += 1
            index += 1
        elif char == "-" and script.startswith("--", index):
            end = script.find("\n", index)
            end = length if end == -1 else end
            index = end
        elif char == ";":
            statements.append("".join(current))
            current = []
            index += 1
        else:
            current.append(char)
            index += 1
    statements.append("".join(current))
    return [statement.strip() for statement in statements if statement.strip()]


def _ignored(statement: str) -> bool:
    lowered = statement.lstrip().lower()
    return lowered.startswith(_IGNORED_PREFIXES)


class Connection:
    """A psycopg connection behind the surface the repositories expect.

    `writing` marks a transaction opened by a repository for a mutation. A
    repository that reads a row and then changes it asks for that row with
    `SELECT ... FOR UPDATE` while `writing` is set, which is the exclusion that
    SQLite's `BEGIN IMMEDIATE` used to give the whole file.

    A connection borrowed from the pool goes back to it on `close()`; only a
    directly opened one (autocommit DDL) is really closed.
    """

    def __init__(self, raw: psycopg.Connection, *, pool: psycopg_pool.ConnectionPool | None = None) -> None:
        self.raw = raw
        self.writing = False
        self._pool = pool

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Result:
        if _ignored(sql):
            return Result(self.raw.cursor())
        if _PLACEHOLDER in sql:
            return Result(self.raw.cursor().execute(_translate(sql), _adapt_params(params)))
        return Result(self.raw.cursor().execute(sql))

    def executescript(self, script: str) -> None:
        for statement in _split_script(script):
            if _ignored(statement):
                continue
            self.raw.cursor().execute(statement)

    def commit(self) -> None:
        self.raw.commit()

    def rollback(self) -> None:
        self.raw.rollback()

    def close(self) -> None:
        if self._pool is None:
            self.raw.close()
            return
        # A repository can leave the transaction open when it raises an
        # application error (an unknown id, a conflict). The pool would roll it
        # back anyway, but only after logging a warning, so it happens here.
        self.raw.rollback()
        self._pool.putconn(self.raw)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _log_new_connection(connection: psycopg.Connection) -> None:
    """DEBUG once per physical connection: how many the pool really opens."""
    info = connection.info
    LOGGER.debug(
        "Новое соединение с PostgreSQL: %s:%s/%s",
        info.host or "localhost",
        info.port or 5432,
        info.dbname or "?",
    )


def pool(dsn: str | None = None) -> psycopg_pool.ConnectionPool:
    """The pool of one database, created on first use and kept for the process.

    Repositories get a database URL rather than a pool, so pools are keyed by
    URL: the application has one, and the test session has one per throwaway
    schema. Creation probes the server once, because a pool would otherwise
    retry an unreachable database in the background and only time out later.
    """
    url = dsn or database_url()
    with _POOLS_LOCK:
        existing = _POOLS.get(url)
        if existing is not None:
            return existing
        try:
            psycopg.connect(url).close()
        except psycopg.Error:
            LOGGER.error("Не удалось подключиться к PostgreSQL: %s", safe_target(url))
            raise
        created = psycopg_pool.ConnectionPool(
            url,
            min_size=POOL_MIN_SIZE,
            max_size=pool_max_size(),
            timeout=POOL_TIMEOUT_SECONDS,
            open=False,
            kwargs={"row_factory": dict_row},
            configure=_log_new_connection,
        )
        created.open()
        _POOLS[url] = created
        LOGGER.info(
            "Подключение к PostgreSQL установлено: %s (пул %d..%d)",
            safe_target(url),
            POOL_MIN_SIZE,
            created.max_size,
        )
        return created


def close_pools() -> None:
    """Close every pool of this process; the application calls it on shutdown."""
    with _POOLS_LOCK:
        pools = list(_POOLS.values())
        _POOLS.clear()
    for created in pools:
        created.close()


def connect(dsn: str | None = None, *, autocommit: bool = False) -> Connection:
    """Borrow one connection from the process pool of that database.

    `autocommit=True` bypasses the pool and really closes on `close()`: the few
    callers that own DDL outside a transaction (creating or dropping a schema in
    the tests) must not leave a half-finished transaction in a pooled session.
    """
    url = dsn or database_url()
    if autocommit:
        return Connection(psycopg.connect(url, row_factory=dict_row, autocommit=True))
    created = pool(url)
    try:
        raw = created.getconn(timeout=POOL_TIMEOUT_SECONDS)
    except psycopg_pool.PoolError as exc:
        raise OperationalError(str(exc)) from exc
    return Connection(raw, pool=created)


def table_columns(connection: Connection, table: str) -> set[str]:
    """The columns of one table in the current schema (`PRAGMA table_info`)."""
    rows = connection.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row["column_name"]) for row in rows}
