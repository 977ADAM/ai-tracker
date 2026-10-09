"""The project root of the schema: shared helpers and transactions.

`projects` is the main table of the application. Every measurement, run, SEO
analysis, and chat belongs to one project through `project_id`, so this module
holds the connection helper its repositories share and the cursor helpers that
the project and measurement history pages use.

PostgreSQL sessions are short and explicit: one connection per operation, a
commit on the happy path, a rollback on a driver error.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from app.core import database
from app.core.errors import StorageError, ValidationError

PROJECT_STORAGE_FAILED = "Не удалось сохранить или прочитать проект"


def stamp() -> str:
    return datetime.now(UTC).isoformat()


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def cursor_encode(value) -> str:
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
    """One PostgreSQL database, opened per operation."""

    def __init__(self, dsn: str):
        self.dsn = dsn

    @contextmanager
    def connection(self, write=False) -> Iterator[database.Connection]:
        db: database.Connection | None = None
        try:
            db = database.connect(self.dsn)
            db.writing = write
            yield db
            db.commit()
        except database.Error as exc:
            if db is not None:
                db.rollback()
            raise StorageError(PROJECT_STORAGE_FAILED) from exc
        finally:
            if db is not None:
                db.close()
