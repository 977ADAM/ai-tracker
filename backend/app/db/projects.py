"""Project CRUD; snapshots belong to measurements, not mutable projects."""

import json
from uuid import uuid4

from app.core.errors import RunConflict, RunNotFound, ValidationError
from app.db.project_storage import (
    ProjectStorage,
    cursor_decode,
    cursor_encode,
    encode,
    stamp,
)


class ProjectRepository(ProjectStorage):
    @staticmethod
    def public(row):
        return {
            "include_subdomains": True,
            "brand_description": "",
            "brand_aliases": [],
            **json.loads(row["input_json"]),
            "id": row["id"],
            "revision": row["revision"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def create(self, input: dict) -> dict:
        id, now = str(uuid4()), stamp()
        with self.connection(True) as db:
            db.execute(
                "INSERT INTO projects(id,input_json,created_at,updated_at) VALUES(?,?,?,?)",
                (id, encode(input), now, now),
            )
        return self.get(id)

    def get(self, id: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT * FROM projects WHERE id=?", (id,)).fetchone()
            if row is None:
                raise RunNotFound("Проект не найден")
            return self.public(row)

    def update(self, id: str, input: dict) -> dict:
        with self.connection(True) as db:
            if not db.execute(
                "UPDATE projects SET input_json=?,revision=revision+1,updated_at=? WHERE id=?",
                (encode(input), stamp(), id),
            ).rowcount:
                raise RunNotFound("Проект не найден")
        return self.get(id)

    def list_page(self, cursor=None, limit=20):
        if not 1 <= limit <= 100:
            raise ValidationError("Некорректный размер страницы")
        args = []
        where = ""
        if cursor:
            value = cursor_decode(cursor)
            if (
                not isinstance(value, list)
                or len(value) != 2
                or any(not isinstance(x, str) for x in value)
            ):
                raise ValidationError("Некорректная страница проектов")
            where = "WHERE (created_at,id)<(?,?)"
            args.extend(value)
        with self.connection() as db:
            rows = db.execute(
                f"SELECT * FROM projects {where} ORDER BY created_at DESC,id DESC LIMIT ?",
                (*args, limit + 1),
            ).fetchall()
        items = [self.public(r) for r in rows[:limit]]
        return {
            "items": items,
            "cursor": cursor_encode([items[-1]["created_at"], items[-1]["id"]])
            if len(rows) > limit
            else None,
        }

    def delete(self, id: str):
        with self.connection(True) as db:
            if db.execute(
                "SELECT 1 FROM project_measurements WHERE project_id=? AND status='running'",
                (id,),
            ).fetchone():
                raise RunConflict("Сначала завершите или отмените замер")
            if not db.execute("DELETE FROM projects WHERE id=?", (id,)).rowcount:
                raise RunNotFound("Проект не найден")
