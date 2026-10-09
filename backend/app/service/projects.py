"""Project settings and dashboard summaries from saved measurements."""

from app.domain.projects import normalize_project


class ProjectService:
    def __init__(self, repository, measurements, connections):
        self.repository, self.measurements, self.connections = (
            repository,
            measurements,
            connections,
        )

    def create(self, payload):
        p = normalize_project(payload)
        for id in p["connection_ids"]:
            self.connections.require(id)
        return self.repository.create(p)

    def update(self, id, payload):
        p = normalize_project(payload)
        for connection_id in p["connection_ids"]:
            self.connections.require(connection_id)
        return self.repository.update(id, p)

    def get(self, id):
        return self.repository.get(id)

    def list_page(self, cursor=None, limit=20):
        result = self.repository.list_page(cursor, limit)
        for p in result["items"]:
            with self.measurements.connection() as db:
                latest = db.execute(
                    "SELECT id FROM project_measurements WHERE project_id=? AND status='completed' ORDER BY created_at DESC,id DESC LIMIT 1",
                    (p["id"],),
                ).fetchone()
                active = db.execute(
                    "SELECT id FROM project_measurements WHERE project_id=? AND status='running'",
                    (p["id"],),
                ).fetchone()
            p["latest_measurement"] = (
                self.measurements.get(latest["id"]) if latest else None
            )
            p["active_measurement"] = (
                self.measurements.get(active["id"]) if active else None
            )
            p["connections"] = []
            for id in p["connection_ids"]:
                c = self.connections.find(id)
                p["connections"].append(
                    {"connection_id": id, "name": c.name if c else "Удалённая модель"}
                )
        return result

    def delete(self, id):
        self.repository.delete(id)
