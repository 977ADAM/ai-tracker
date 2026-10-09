"""Persist individual outcomes; reject writes after a terminal measurement."""

import json
import sqlite3
from dataclasses import asdict
from uuid import uuid4

from app.core.errors import RunConflict, RunNotFound, ValidationError
from app.db.project_storage import (
    ProjectStorage,
    cursor_decode,
    cursor_encode,
    encode,
    stamp,
)
from app.domain.projects import (
    comparison_key,
    mentions_project_brand,
    mentions_project_domain,
)
from app.domain.seo_answer import answer_from_dict


class MeasurementRepository(ProjectStorage):
    @staticmethod
    def require(db, id):
        row = db.execute(
            "SELECT * FROM project_measurements WHERE id=?", (id,)
        ).fetchone()
        if row is None:
            raise RunNotFound("Замер не найден")
        return row

    @classmethod
    def active(cls, db, id):
        return cls.require(db, id)["status"] == "running"

    def create(self, project_id, snapshot, estimate):
        id = str(uuid4())
        try:
            with self.connection(True) as db:
                if not db.execute(
                    "SELECT 1 FROM projects WHERE id=?", (project_id,)
                ).fetchone():
                    raise RunNotFound("Проект не найден")
                if db.execute(
                    "SELECT 1 FROM project_measurements WHERE project_id=? AND status='running'",
                    (project_id,),
                ).fetchone():
                    raise RunConflict("Замер проекта уже выполняется")
                db.execute(
                    "INSERT INTO project_measurements VALUES(?,?,?,?,?,?,?,?)",
                    (
                        id,
                        project_id,
                        encode(snapshot),
                        comparison_key(snapshot),
                        encode(estimate),
                        "running",
                        stamp(),
                        None,
                    ),
                )
                for i, _ in enumerate(snapshot["project"]["queries"]):
                    for c in snapshot["connections"]:
                        db.execute(
                            "INSERT INTO project_model_rows(measurement_id,query_index,connection_id) VALUES(?,?,?)",
                            (id, i, c["connection_id"]),
                        )
                    if snapshot["project"]["yandex_enabled"]:
                        db.execute(
                            "INSERT INTO project_search_rows(measurement_id,query_index) VALUES(?,?)",
                            (id, i),
                        )
        except sqlite3.IntegrityError as exc:
            raise RunConflict("Замер проекта уже выполняется") from exc
        return id

    def mark_sent(self, id, kind, row_key):
        with self.connection(True) as db:
            if not self.active(db, id):
                return False
            if kind == "model":
                return bool(
                    db.execute(
                        "UPDATE project_model_rows SET status='sent' WHERE measurement_id=? AND query_index=? AND connection_id=? AND status='pending'",
                        (id, *row_key),
                    ).rowcount
                )
            if kind == "sentiment":
                return bool(
                    db.execute(
                        "UPDATE project_model_rows SET sentiment_status='sent' WHERE measurement_id=? AND query_index=? AND connection_id=? AND sentiment_status='pending'",
                        (id, *row_key),
                    ).rowcount
                )
            return bool(
                db.execute(
                    "UPDATE project_search_rows SET status='sent' WHERE measurement_id=? AND query_index=? AND status='pending'",
                    (id, row_key),
                ).rowcount
            )

    def save_answer(self, id, row_key, answer, error=None):
        with self.connection(True) as db:
            if not self.active(db, id):
                return False
            p = json.loads(self.require(db, id)["snapshot_json"])["project"]
            if answer is not None:
                value = asdict(answer)
                answer_from_dict(value)
                name = mentions_project_brand(answer.text, p)
                host = mentions_project_domain(answer.text, p)
            else:
                value, name, host = None, False, False
            return bool(
                db.execute(
                    """UPDATE project_model_rows SET status=?,evidence_json=?,brand_mentioned=?,domain_mentioned=?,sentiment_status=?,error=?
                WHERE measurement_id=? AND query_index=? AND connection_id=? AND status IN ('pending','sent')""",
                    (
                        "success" if answer is not None else "error",
                        encode(value) if value else None,
                        name,
                        host,
                        "pending" if name else "not_applicable",
                        error,
                        id,
                        *row_key,
                    ),
                ).rowcount
            )

    def save_sentiment(self, id, row_key, result, error=None):
        with self.connection(True) as db:
            if not self.active(db, id):
                return False
            return bool(
                db.execute(
                    """UPDATE project_model_rows SET sentiment_status=?,sentiment_json=?,sentiment_error=?
                WHERE measurement_id=? AND query_index=? AND connection_id=? AND sentiment_status IN ('pending','sent')""",
                    (
                        "completed" if result else "unknown",
                        encode(asdict(result)) if result else None,
                        error,
                        id,
                        *row_key,
                    ),
                ).rowcount
            )

    def save_search_operation(self, id, query_index, operation_id):
        with self.connection(True) as db:
            if not self.active(db, id):
                return False
            return bool(
                db.execute(
                    "UPDATE project_search_rows SET status='waiting',operation_id=? WHERE measurement_id=? AND query_index=? AND status='sent'",
                    (operation_id, id, query_index),
                ).rowcount
            )

    def save_search_result(self, id, query_index, documents, error=None):
        with self.connection(True) as db:
            if not self.active(db, id):
                return False
            return bool(
                db.execute(
                    """UPDATE project_search_rows SET status=?,documents_json=?,error=? WHERE measurement_id=? AND query_index=? AND status IN ('pending','sent','waiting')""",
                    (
                        "success" if documents is not None else "error",
                        encode([asdict(d) for d in documents])
                        if documents is not None
                        else None,
                        error,
                        id,
                        query_index,
                    ),
                ).rowcount
            )

    @staticmethod
    def _stop_rows(db, id, status):
        db.execute(
            "UPDATE project_model_rows SET status=? WHERE measurement_id=? AND status IN ('pending','sent')",
            (status, id),
        )
        db.execute(
            "UPDATE project_model_rows SET sentiment_status=? WHERE measurement_id=? AND sentiment_status IN ('pending','sent')",
            (status, id),
        )
        db.execute(
            "UPDATE project_search_rows SET status=? WHERE measurement_id=? AND status IN ('pending','sent','waiting')",
            (status, id),
        )

    def finish(self, id, status):
        if status not in ("completed", "failed", "cancelled", "interrupted"):
            raise ValidationError("Неизвестное состояние замера")
        with self.connection(True) as db:
            if self.active(db, id):
                self._stop_rows(
                    db,
                    id,
                    "interrupted" if status in ("completed", "failed") else status,
                )
                db.execute(
                    "UPDATE project_measurements SET status=?,finished_at=? WHERE id=?",
                    (status, stamp(), id),
                )

    def cancel(self, id):
        self.finish(id, "cancelled")
        return self.get(id)

    def recover_unfinished(self):
        with self.connection(True) as db:
            for row in db.execute(
                "SELECT id FROM project_measurements WHERE status='running'"
            ).fetchall():
                self._stop_rows(db, row["id"], "interrupted")
            db.execute(
                "UPDATE project_measurements SET status='interrupted',finished_at=? WHERE status='running'",
                (stamp(),),
            )

    @staticmethod
    def model_row(row, snapshot):
        evidence = json.loads(row["evidence_json"]) if row["evidence_json"] else None
        if evidence:
            answer_from_dict(evidence)
        query = snapshot["project"]["queries"][row["query_index"]]
        c = next(
            c
            for c in snapshot["connections"]
            if c["connection_id"] == row["connection_id"]
        )
        return {
            "query_index": row["query_index"],
            "connection_id": row["connection_id"],
            "query": query["text"],
            "category": query.get("category"),
            "group": query.get("group"),
            "provider_name": c["name"],
            "status": row["status"],
            "answer": evidence["text"] if evidence else None,
            "evidence": evidence,
            "brand_mentioned": bool(row["brand_mentioned"]),
            "domain_mentioned": bool(row["domain_mentioned"]),
            "sentiment_status": row["sentiment_status"],
            "sentiment": json.loads(row["sentiment_json"])
            if row["sentiment_json"]
            else None,
            "error": row["error"],
            "sentiment_error": row["sentiment_error"],
            "answer_mode": evidence["answer_mode"] if evidence else c["answer_mode"],
            "citations": evidence["citations"] if evidence else [],
        }

    @staticmethod
    def search_row(row, snapshot):
        return {
            "query_index": row["query_index"],
            "query": snapshot["project"]["queries"][row["query_index"]]["text"],
            "status": row["status"],
            "documents": json.loads(row["documents_json"])
            if row["documents_json"]
            else [],
            "error": row["error"],
        }

    def _snapshot(self, db, row):
        from app.domain.measurement_report import build_measurement_report

        snapshot = json.loads(row["snapshot_json"])
        models = [
            self.model_row(r, snapshot)
            for r in db.execute(
                "SELECT * FROM project_model_rows WHERE measurement_id=? ORDER BY query_index,connection_id",
                (row["id"],),
            )
        ]
        searches = [
            self.search_row(r, snapshot)
            for r in db.execute(
                "SELECT * FROM project_search_rows WHERE measurement_id=? ORDER BY query_index",
                (row["id"],),
            )
        ]
        aggregates = build_measurement_report(snapshot, models, searches)
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "snapshot": snapshot,
            "status": row["status"],
            "created_at": row["created_at"],
            "finished_at": row["finished_at"],
            "estimate": json.loads(row["estimate_json"]),
            "incomplete": aggregates["successful"] != aggregates["planned"]
            or aggregates["search_errors"] > 0,
            "progress": aggregates["progress"],
            "aggregates": aggregates,
            "comparison": None,
        }

    def get(self, id):
        from app.domain.measurement_report import compare_measurements

        with self.connection() as db:
            row = self.require(db, id)
            result = self._snapshot(db, row)
            previous = db.execute(
                "SELECT * FROM project_measurements WHERE project_id=? AND comparison_key=? AND status='completed' AND (created_at,id)<(?,?) ORDER BY created_at DESC,id DESC LIMIT 1",
                (row["project_id"], row["comparison_key"], row["created_at"], id),
            ).fetchone()
            result["comparison"] = compare_measurements(
                result, self._snapshot(db, previous) if previous else None
            )
            if previous:
                result["comparison"]["previous_id"] = previous["id"]
            return result

    def list_page(self, project_id, cursor=None, limit=20):
        if not 1 <= limit <= 100:
            raise ValidationError("Некорректный размер страницы")
        args = [project_id]
        where = ""
        if cursor:
            value = cursor_decode(cursor)
            if (
                not isinstance(value, list)
                or len(value) != 2
                or any(not isinstance(x, str) for x in value)
            ):
                raise ValidationError("Некорректная страница истории")
            where = "AND (created_at,id)<(?,?)"
            args.extend(value)
        with self.connection() as db:
            rows = db.execute(
                f"SELECT * FROM project_measurements WHERE project_id=? {where} ORDER BY created_at DESC,id DESC LIMIT ?",
                (*args, limit + 1),
            ).fetchall()
        items = [self.get(r["id"]) for r in rows[:limit]]
        return {
            "items": items,
            "cursor": cursor_encode([items[-1]["created_at"], items[-1]["id"]])
            if len(rows) > limit
            else None,
        }

    def rows_page(self, id, kind, cursor=None, limit=50):
        if kind not in ("model", "search") or not 1 <= limit <= 100:
            raise ValidationError("Некорректная детализация замера")
        offset = cursor_decode(cursor) if cursor else 0
        if type(offset) is not int or offset < 0:
            raise ValidationError("Некорректная страница результатов")
        table = "project_model_rows" if kind == "model" else "project_search_rows"
        order = "query_index,connection_id" if kind == "model" else "query_index"
        with self.connection() as db:
            snapshot = json.loads(self.require(db, id)["snapshot_json"])
            rows = db.execute(
                f"SELECT * FROM {table} WHERE measurement_id=? ORDER BY {order} LIMIT ? OFFSET ?",
                (id, limit + 1, offset),
            ).fetchall()
            items = [
                (self.model_row if kind == "model" else self.search_row)(r, snapshot)
                for r in rows[:limit]
            ]
        return {
            "kind": kind,
            "items": items,
            "cursor": cursor_encode(offset + limit) if len(rows) > limit else None,
        }

    def delete(self, id):
        with self.connection(True) as db:
            if self.active(db, id):
                raise RunConflict("Сначала отмените или завершите замер")
            db.execute("DELETE FROM project_measurements WHERE id=?", (id,))
