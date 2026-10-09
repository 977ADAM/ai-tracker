"""Minimum regression checks for project snapshots and repeatable paid work."""

import asyncio
import sqlite3

import pytest

from app.core.errors import RunConflict, ValidationError
from app.db.measurements import MeasurementRepository
from app.db.projects import ProjectRepository
from app.domain.measurement_report import build_measurement_report, compare_measurements
from app.domain.projects import comparison_key, normalize_project
from app.domain.seo_answer import SeoAnswer
from app.service.measurement_worker import MeasurementWorker


def project(**changes):
    return {
        "name": "Пицца",
        "brand": "Додопицца",
        "site_url": "https://example.ru",
        "competitors": [],
        "queries": [{"text": "Где заказать пиццу?", "category": None}],
        "connection_ids": ["m1"],
        "yandex_enabled": False,
        **changes,
    }


def snapshot(p=None):
    return {
        "project": p or project(),
        "connections": [
            {
                "connection_id": "m1",
                "name": "Модель",
                "kind": "openai",
                "endpoint": "https://api.example.com/chat/completions",
                "model": "test",
                "answer_mode": "text",
                "thinking_disabled": False,
            }
        ],
        "classifier": {
            "endpoint": "https://api.example.com/chat/completions",
            "model": "judge",
            "prompt_version": "sentiment-v1",
        },
        "yandex": None,
        "metric_version": "project-metrics-v1",
    }


def test_validation_and_comparison_identity():
    p = normalize_project(project())
    assert p["queries"][0]["text"] == "Где заказать пиццу?"
    for changes in (
        {"queries": [{"text": "x"}] * 21},
        {"site_url": "http://localhost"},
        {"connection_ids": ["m"] * 6},
    ):
        with pytest.raises(ValidationError):
            normalize_project(project(**changes))
    left = snapshot(
        project(
            queries=[{"text": "a", "category": None}, {"text": "b", "category": None}]
        )
    )
    right = snapshot(
        project(name="Иное имя", queries=list(reversed(left["project"]["queries"])))
    )
    assert comparison_key(left) == comparison_key(right)
    right["classifier"]["model"] = "other"
    assert comparison_key(left) != comparison_key(right)


def test_storage_snapshot_cancel_and_legacy_migration(tmp_path):
    projects = ProjectRepository(tmp_path)
    projects.initialize()
    runs = MeasurementRepository(tmp_path)
    p = projects.create(normalize_project(project()))
    run = runs.create(
        p["id"], snapshot(), {"model_calls": 1, "sentiment_calls": 1, "search_calls": 0}
    )
    with pytest.raises(RunConflict):
        runs.create(p["id"], snapshot(), {})
    projects.update(p["id"], normalize_project(project(brand="Другой")))
    assert runs.get(run)["snapshot"]["project"]["brand"] == "Додопицца"
    with pytest.raises(RunConflict):
        projects.delete(p["id"])
    runs.cancel(run)
    assert not runs.save_answer(
        run,
        (0, "m1"),
        SeoAnswer("Додопицца", "text", "not_requested", (), (), "test", None),
    )
    runs.finish(run, "completed")
    assert runs.get(run)["status"] == "cancelled"
    from app.db.chat import ChatRepository
    from app.db.runs import RunRepository
    from app.db.seo import SeoRepository

    for repo in (
        RunRepository(tmp_path),
        SeoRepository(tmp_path),
        ChatRepository(tmp_path),
    ):
        repo.initialize()
    with sqlite3.connect(tmp_path / "runs.sqlite3") as db:
        assert db.execute("pragma user_version").fetchone()[0] == 7


def test_report_denominators_unknown_and_comparison():
    rows = [
        {
            "query_index": 0,
            "connection_id": "m1",
            "status": "success",
            "answer": "Додопицца хороша",
            "brand_mentioned": True,
            "domain_mentioned": False,
            "sentiment_status": "unknown",
            "sentiment": None,
            "evidence": None,
        },
        {"query_index": 1, "connection_id": "m1", "status": "error", "answer": None},
    ]
    s = snapshot(
        project(
            queries=[{"text": "a", "category": None}, {"text": "b", "category": None}]
        )
    )
    report = build_measurement_report(s, rows, [])
    assert report["visibility"] == 1
    assert report["successful"] == 1 and report["planned"] == 2
    assert report["sentiment"]["unknown"] == 1 and report["sentiment"]["neutral"] == 0
    current = {"snapshot": s, "status": "completed", "aggregates": report}
    assert compare_measurements(current, current)["visibility_delta"] is None


def test_worker_checks_cartesian_pairs_and_preserves_sentiment_failures(tmp_path):
    projects = ProjectRepository(tmp_path)
    projects.initialize()
    runs = MeasurementRepository(tmp_path)
    queries = [{"text": f"Запрос {i}", "category": None} for i in range(15)]
    p = project(queries=queries, connection_ids=[f"m{i}" for i in range(5)])
    saved = projects.create(normalize_project(p))
    s = snapshot(p)
    base = s["connections"][0]
    s["connections"] = [{**base, "connection_id": f"m{i}"} for i in range(5)]
    run = runs.create(
        saved["id"], s, {"model_calls": 75, "sentiment_calls": 75, "search_calls": 0}
    )

    class Provider:
        def answer(self, prompt):
            return SeoAnswer(
                f"Додопицца: {prompt}", "text", "not_requested", (), (), "test", None
            )

        def close(self):
            pass

    class Classifier:
        async def classify(self, brand, answer):
            raise ValidationError("Ошибка оценки")

    asyncio.run(
        MeasurementWorker(runs).run(
            run, asyncio.Event(), {f"m{i}": Provider() for i in range(5)}, Classifier()
        )
    )
    result = runs.get(run)
    assert result["status"] == "completed"
    assert result["aggregates"]["successful"] == 75
    assert result["aggregates"]["sentiment"]["unknown"] == 75
    assert result["aggregates"]["sentiment"]["neutral"] == 0


def test_project_api_keeps_history_and_refuses_unconfigured_start(client):
    connections = client.get("/api/providers").json()
    payload = project(connection_ids=[connections[0]["id"]])
    created = client.post("/api/projects", json=payload)
    assert created.status_code == 201
    id = created.json()["id"]
    assert client.get("/api/projects").json()["items"][0]["id"] == id
    assert client.get(f"/api/projects/{id}/measurements").json()["items"] == []
    assert client.post(f"/api/projects/{id}/measurements").status_code == 400
    assert client.get(f"/api/projects/{id}/measurements").json()["items"] == []
    assert client.delete(f"/api/projects/{id}").status_code == 204


def test_create_brand_and_site_only(client):
    response = client.post(
        "/api/projects", json={"brand": "Додопицца", "site_url": "https://example.ru"}
    )
    assert response.status_code == 201
    p = response.json()
    assert p["name"] == "Додопицца"
    assert p["queries"] == [] and p["connection_ids"] == []
    assert client.post(f"/api/projects/{p['id']}/measurements").status_code == 400


def test_cancelled_deleted_measurement_closes_unstarted_clients(tmp_path):
    projects = ProjectRepository(tmp_path)
    projects.initialize()
    runs = MeasurementRepository(tmp_path)
    p = projects.create(normalize_project(project()))
    id = runs.create(p["id"], snapshot(), {})
    runs.cancel(id)
    runs.delete(id)

    class Provider:
        closed = False

        def close(self):
            self.closed = True

        def answer(self, prompt):
            raise AssertionError("No paid call after cancellation")

    provider = Provider()

    async def run():
        event = asyncio.Event()
        event.set()
        await MeasurementWorker(runs).run(id, event, {"m1": provider}, None)

    asyncio.run(run())
    assert provider.closed
