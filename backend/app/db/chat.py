"""Owner-only SQLite persistence for the SEO chat.

The two chat tables live in the existing `runs.sqlite3` beside the brand-check,
run, and SEO tables. This repository owns the `user_version = 5` migration: it
creates `seo_chats` and `seo_chat_messages` and raises the schema version as the
last owner of the shared file, while `RunRepository` and `SeoRepository` keep
reading their own tables.

Durability rules follow `app/db/seo.py`: owner-only 0o700/0o600 access, WAL and
a bounded `busy_timeout`, the version read before any write so a file written by
a newer application version is refused untouched, and every write in its own
transaction. A message takes its `seq` inside the same `BEGIN IMMEDIATE`
transaction that inserts it, so parallel appends of one chat never share an
index. `draft` and `payload` are JSON with `ensure_ascii=False`; secrets never
reach these tables.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.core.errors import ChatNotFound, StorageError, ValidationError

FILE_NAME = "runs.sqlite3"
SCHEMA_VERSION = 5
MAX_FILE_VERSION = 7
BUSY_TIMEOUT_MS = 5000

STORAGE_FAILED = "Не удалось сохранить или прочитать чат"
CHAT_NOT_FOUND = "Чат не найден"
MESSAGE_NOT_FOUND = "Сообщение не найдено"
INVALID_DATA = "Некорректные данные чата"
INVALID_CURSOR = "Некорректная страница сообщений"
INVALID_LIMIT = "Некорректное число сообщений"

# The accumulated chat parameters: `app.domain.chat.ChatDraft` in JSON form.
# A fresh chat stores this shape rather than `{}`, so a reader always sees the
# five fields of the design's draft. It is private to this module on purpose:
# the domain owns the public draft vocabulary.
_DEFAULT_DRAFT: dict[str, object] = {
    "url": "",
    "sphere": "",
    "seeds": [],
    "services": [],
    "connection_ids": [],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS seo_chats (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    draft TEXT NOT NULL,
    pending_proposal_id TEXT,
    active_analysis_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS seo_chat_messages (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT,
    payload TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (chat_id, seq)
);
"""


class ChatRepository:
    """Small transactions keep every message independently durable."""

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = Path(config_dir)
        self.path = self.config_dir / FILE_NAME

    def initialize(self) -> None:
        """Create the chat tables and raise `user_version` to the chat schema."""
        try:
            self.config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.config_dir, 0o700)
            descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(descriptor)
            os.chmod(self.path, 0o600)
        except OSError as exc:
            raise StorageError(STORAGE_FAILED) from exc
        version = self._read_version()
        if version > MAX_FILE_VERSION:
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
        """WAL and a bounded busy timeout keep a busy chat from locking the file.

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
    def _require_chat(connection: sqlite3.Connection, chat_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM seo_chats WHERE id=?", (chat_id,)).fetchone()
        if row is None:
            raise ChatNotFound(CHAT_NOT_FOUND)
        return row

    # -- chats -----------------------------------------------------------

    def create_chat(self, title: str) -> str:
        """Create one chat and return its server-generated identifier."""
        chat_id = uuid4().hex
        now = _now()
        with self._connection(write=True) as connection:
            connection.execute(
                "INSERT INTO seo_chats (id, title, draft, pending_proposal_id, active_analysis_id, "
                "created_at, updated_at) VALUES (?, ?, ?, NULL, NULL, ?, ?)",
                (chat_id, title, _json_dumps(_DEFAULT_DRAFT), now, now),
            )
        return chat_id

    def chat(self, chat_id: str) -> dict:
        """Return one chat with its parsed draft, or raise `ChatNotFound`."""
        with self._connection() as connection:
            return _chat_dict(self._require_chat(connection, chat_id))

    def list_chats(self, limit: int = 100) -> tuple[dict, ...]:
        """Return the most recently updated chats first."""
        size = _page_size(limit)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM seo_chats ORDER BY updated_at DESC, id DESC LIMIT ?",
                (size,),
            ).fetchall()
            return tuple(_chat_dict(row) for row in rows)

    def delete_chat(self, chat_id: str) -> None:
        """Delete one chat and every message it owns.

        The runs a chat mentioned are not touched here: the service deletes them
        through `SeoRepository.delete` once the chat's own run is terminal.
        """
        with self._connection(write=True) as connection:
            self._require_chat(connection, chat_id)
            connection.execute("DELETE FROM seo_chat_messages WHERE chat_id=?", (chat_id,))
            connection.execute("DELETE FROM seo_chats WHERE id=?", (chat_id,))

    def save_draft(self, chat_id: str, draft: Mapping[str, object]) -> None:
        """Replace the accumulated parameters of one chat."""
        payload = _json_dumps(draft)
        now = _now()
        with self._connection(write=True) as connection:
            self._require_chat(connection, chat_id)
            connection.execute(
                "UPDATE seo_chats SET draft=?, updated_at=? WHERE id=?",
                (payload, now, chat_id),
            )

    def set_title(self, chat_id: str, title: str) -> None:
        """Replace the title of one chat, which the first user message sets."""
        now = _now()
        with self._connection(write=True) as connection:
            self._require_chat(connection, chat_id)
            connection.execute(
                "UPDATE seo_chats SET title=?, updated_at=? WHERE id=?",
                (title, now, chat_id),
            )

    def set_pending_proposal(self, chat_id: str, message_id: str | None) -> None:
        """Point the chat at its open proposal message, or clear the pointer."""
        now = _now()
        with self._connection(write=True) as connection:
            self._require_chat(connection, chat_id)
            connection.execute(
                "UPDATE seo_chats SET pending_proposal_id=?, updated_at=? WHERE id=?",
                (message_id, now, chat_id),
            )

    def claim_proposal(self, chat_id: str, message_id: str) -> bool:
        """Clear the open proposal pointer, but only for the caller naming it.

        The one conditional `UPDATE` is the compare-and-swap that makes a launch
        safe under concurrent turns: the clear and the equality test happen in a
        single write transaction, so when two turns read the same
        `pending_proposal_id` only the first update matches and every later one
        reports `rowcount == 0`. `True` means this caller won and owns the launch.
        """
        now = _now()
        with self._connection(write=True) as connection:
            self._require_chat(connection, chat_id)
            cursor = connection.execute(
                "UPDATE seo_chats SET pending_proposal_id=NULL, updated_at=? "
                "WHERE id=? AND pending_proposal_id=?",
                (now, chat_id, message_id),
            )
            return cursor.rowcount == 1

    def restore_proposal(self, chat_id: str, message_id: str) -> bool:
        """Point a chat with no open proposal back at the one named here.

        The inverse of `claim_proposal`, for a launch that could not start: the
        claim already cleared the pointer, so a refused `SeoService.start` would
        otherwise leave the card `pending` with nothing pointing at it. The
        `IS NULL` test makes the restore a compare-and-swap of its own: if
        another turn has claimed or created a proposal since, that pointer is
        not this caller's to overwrite, and the update reports `rowcount == 0`.
        """
        now = _now()
        with self._connection(write=True) as connection:
            self._require_chat(connection, chat_id)
            cursor = connection.execute(
                "UPDATE seo_chats SET pending_proposal_id=?, updated_at=? "
                "WHERE id=? AND pending_proposal_id IS NULL",
                (message_id, now, chat_id),
            )
            return cursor.rowcount == 1

    def set_active_analysis(self, chat_id: str, analysis_id: str | None) -> None:
        """Point the chat at the analysis it started, or clear the pointer."""
        now = _now()
        with self._connection(write=True) as connection:
            self._require_chat(connection, chat_id)
            connection.execute(
                "UPDATE seo_chats SET active_analysis_id=?, updated_at=? WHERE id=?",
                (analysis_id, now, chat_id),
            )

    # -- messages --------------------------------------------------------

    def append_message(
        self,
        chat_id: str,
        role: str,
        kind: str,
        text: str | None,
        payload: Mapping[str, object] | None,
    ) -> dict:
        """Append one message and return it with its monotonic `seq`.

        The index is `MAX(seq) + 1` read and inserted inside one
        `BEGIN IMMEDIATE` transaction: the write lock is already held when the
        maximum is read, so parallel appends of the same chat can never receive
        the same index.
        """
        message_id = uuid4().hex
        stored = None if payload is None else _json_dumps(payload)
        now = _now()
        with self._connection(write=True) as connection:
            self._require_chat(connection, chat_id)
            seq = int(
                connection.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM seo_chat_messages WHERE chat_id=?",
                    (chat_id,),
                ).fetchone()[0]
            )
            connection.execute(
                "INSERT INTO seo_chat_messages (id, chat_id, seq, role, kind, text, payload, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (message_id, chat_id, seq, role, kind, text, stored, now),
            )
            connection.execute("UPDATE seo_chats SET updated_at=? WHERE id=?", (now, chat_id))
            stored_row = connection.execute(
                "SELECT * FROM seo_chat_messages WHERE id=?", (message_id,),
            ).fetchone()
        return _message_dict(stored_row)

    def message(self, message_id: str) -> dict:
        """Return one message, or raise `ChatNotFound` when it does not exist."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM seo_chat_messages WHERE id=?", (message_id,),
            ).fetchone()
        if row is None:
            raise ChatNotFound(MESSAGE_NOT_FOUND)
        return _message_dict(row)

    def messages(self, chat_id: str, cursor: int | None = None, limit: int = 200) -> dict:
        """Return one page of messages, oldest first inside the page.

        The window holds the newest `limit` messages; `next_cursor` is the
        highest `seq` left outside it, so the next call reads older messages
        with `seq` at most the cursor. A chat without messages — or without
        older ones — reports `next_cursor` as `None`.
        """
        size = _page_size(limit)
        after = _cursor(cursor)
        where = "AND seq <= ?" if after is not None else ""
        params: tuple = (chat_id, after, size + 1) if after is not None else (chat_id, size + 1)
        with self._connection() as connection:
            self._require_chat(connection, chat_id)
            rows = connection.execute(
                "SELECT * FROM seo_chat_messages WHERE chat_id=? "
                f"{where} ORDER BY seq DESC LIMIT ?",
                params,
            ).fetchall()
            page = rows[:size]
            items = [_message_dict(row) for row in reversed(page)]
        next_cursor = page[-1]["seq"] - 1 if page and len(rows) > size else None
        return {"items": items, "next_cursor": next_cursor}

    def update_message_payload(self, message_id: str, payload: Mapping[str, object]) -> dict:
        """Replace the payload of one message and return the stored message."""
        stored = _json_dumps(payload)
        now = _now()
        with self._connection(write=True) as connection:
            row = connection.execute(
                "SELECT chat_id FROM seo_chat_messages WHERE id=?", (message_id,),
            ).fetchone()
            if row is None:
                raise ChatNotFound(MESSAGE_NOT_FOUND)
            connection.execute(
                "UPDATE seo_chat_messages SET payload=? WHERE id=?", (stored, message_id),
            )
            connection.execute("UPDATE seo_chats SET updated_at=? WHERE id=?", (now, row["chat_id"]))
            updated = connection.execute(
                "SELECT * FROM seo_chat_messages WHERE id=?", (message_id,),
            ).fetchone()
        return _message_dict(updated)


def _chat_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "draft": _json_read(row["draft"]),
        "pending_proposal_id": row["pending_proposal_id"],
        "active_analysis_id": row["active_analysis_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _message_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "chat_id": row["chat_id"],
        "seq": row["seq"],
        "role": row["role"],
        "kind": row["kind"],
        "text": row["text"],
        "payload": None if row["payload"] is None else _json_read(row["payload"]),
        "created_at": row["created_at"],
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json_dumps(value: Mapping[str, object]) -> str:
    """Serialize a mapping, refusing a non-mapping or a non-JSON value."""
    if not isinstance(value, Mapping):
        raise ValidationError(INVALID_DATA)
    try:
        return json.dumps(dict(value), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError(INVALID_DATA) from exc


def _json_read(value: object) -> dict:
    """Parse stored JSON back into an object; a non-object reads as empty."""
    try:
        parsed = json.loads(value) if isinstance(value, str) else None
    except ValueError as exc:
        raise StorageError(STORAGE_FAILED) from exc
    return parsed if isinstance(parsed, dict) else {}


def _is_index(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _page_size(value: object) -> int:
    """Accept any non-negative page size; a negative one reads as empty."""
    if not _is_index(value):
        raise ValidationError(INVALID_LIMIT)
    return max(0, value)  # type: ignore[arg-type]


def _cursor(value: object) -> int | None:
    if value is None:
        return None
    if not _is_index(value) or value < 0:  # type: ignore[operator]
        raise ValidationError(INVALID_CURSOR)
    return value  # type: ignore[return-value]
