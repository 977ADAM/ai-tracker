"""PostgreSQL access for every durable row of the application.

The application used to keep its rows in SQLite files beside the JSON settings.
All durable rows — projects, their measurements, and the saved runs — now live
in one PostgreSQL database addressed by `AI_TRACKER_DATABASE_URL`, which
defaults to the local Postgres.app server.

This module is the only place that talks to the driver. It gives the
repositories a small DB-API-like surface:

* `connect()` opens a connection whose rows are `Row` objects, addressable both
  by column name and by position, exactly as the repositories and their callers
  use them;
* `?` placeholders are translated to the driver's `%s`, so a statement stays
  readable next to the PostgreSQL schema in `backend/migrations/`, and literals
  that contain `%` keep working;
* `table_columns()` wraps `information_schema` where the code used
  `PRAGMA table_info`;
* `require_project()` refuses a row written for a project that does not exist;
* the driver's error classes are re-exported, so a repository catches one
  vocabulary (`Error`, `IntegrityError`, `OperationalError`) regardless of the
  driver below it.

A connection is in a transaction from its first statement until `commit()` or
`rollback()`; there is no `BEGIN IMMEDIATE`, because PostgreSQL takes the locks
a statement needs. Callers that read and then write the same row take the row
lock explicitly with `SELECT ... FOR UPDATE`.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any, Self

import psycopg
from psycopg import errors as psycopg_errors
from psycopg.rows import dict_row

from app.core.config import DATABASE_URL_VARIABLE, DEFAULT_DATABASE_URL
from app.core.errors import RunNotFound

Error = psycopg.Error
IntegrityError = psycopg_errors.IntegrityError
OperationalError = psycopg.OperationalError
UniqueViolation = psycopg_errors.UniqueViolation
ForeignKeyViolation = psycopg_errors.ForeignKeyViolation

# Statements that only make sense to SQLite. They are accepted and ignored so a
# caller that still carries one does not have to know which engine runs below.
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
    """

    def __init__(self, raw: psycopg.Connection) -> None:
        self.raw = raw
        self.writing = False

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Result:
        if _ignored(sql):
            return Result(self.raw.cursor())
        if _PLACEHOLDER in sql:
            return Result(self.raw.cursor().execute(_translate(sql), _adapt_params(params)))
        return Result(self.raw.cursor().execute(sql))

    def executemany(self, sql: str, params: Iterable[Sequence[Any]]) -> Result:
        cursor = self.raw.cursor()
        rows = [tuple(row) for row in params]
        if not rows:
            return Result(cursor)
        statement = _translate(sql) if _PLACEHOLDER in sql else sql
        cursor.executemany(statement, [_adapt_params(row) for row in rows])
        return Result(cursor)

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
        self.raw.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def connect(dsn: str | None = None, *, autocommit: bool = False) -> Connection:
    """Open one connection to the configured database."""
    url = dsn or database_url()
    return Connection(psycopg.connect(url, row_factory=dict_row, autocommit=autocommit))


def table_columns(connection: Connection, table: str) -> set[str]:
    """The columns of one table in the current schema (`PRAGMA table_info`)."""
    rows = connection.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row["column_name"]) for row in rows}


def require_project(connection: Connection, project_id: str) -> None:
    """Fail loudly when a row is written for a project that does not exist."""
    row = connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise RunNotFound("Проект не найден")
