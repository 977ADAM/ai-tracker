"""Run history, snapshots, conflicts and CSV over HTTP."""

from __future__ import annotations

import csv
import io
import time

import pytest

from app.db.projects import ProjectRepository
from tests.fakes import FakeSearchGateway, ProviderFactorySpy


@pytest.fixture
def project(database_dsn: str) -> dict:
    """Every run belongs to a project, so each test starts with one."""
    return ProjectRepository(database_dsn).create({"domain": "example.ru"})


def body(project_id: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "project_id": project_id,
        "brand": "Ромашка", "domain": "example.ru", "prompts_text": "цветы\nподарки",
        "provider_ids": ["openai"], "regions": [1],
    }
    payload.update(overrides)
    return payload


def wait_done(client, run_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}")
        if response.json()["status"] != "pending":
            return response.json()
        time.sleep(0.01)
    raise AssertionError("run did not finish")


def test_combined_run_history_snapshot_and_csv(make_client, project):
    gateway = FakeSearchGateway(pending_polls=0)
    with make_client(search_gateway=gateway, provider_factory=ProviderFactorySpy()) as client:
        created = client.post("/api/runs", json=body(project["id"]))
        assert created.status_code == 202
        assert set(created.json()) == {"id", "status"}
        run_id = created.json()["id"]
        snapshot = wait_done(client, run_id)
        assert len(snapshot["summary_rows"]) == 4
        assert [row["source"] for row in snapshot["summary_rows"]] == ["Яндекс", "Яндекс", "OpenAI", "OpenAI"]
        assert set(snapshot) == {"id", "project_id", "created_at", "finished_at", "status", "brand", "domain",
                                 "prompts", "provider_ids", "regions", "models", "search", "summary_rows"}
        assert snapshot["project_id"] == project["id"]
        history = client.get("/api/runs").json()
        assert history["items"][0]["id"] == run_id
        assert history["next_cursor"] is None
        export = client.get(f"/api/runs/{run_id}/export.csv")
        assert export.status_code == 200
        assert export.content.startswith(b"\xef\xbb\xbf")
        assert export.headers["content-type"].startswith("text/csv")
        assert "ai-serp-results-" in export.headers["content-disposition"]
        rows = list(csv.reader(io.StringIO(export.content.decode("utf-8-sig")), delimiter=";"))
        assert rows[0] == ["Запрос", "Поисковик", "Язык", "Регион", "ИИ-ответ", "Сайт найден",
                           "Позиция", "Бренд найден", "Статус"]
        assert len(rows) == 5
        assert "api_key" not in str(snapshot)
        assert "operation_id" not in str(snapshot)
        deleted = client.delete(f"/api/runs/{run_id}")
        assert deleted.status_code == 204
        assert client.get(f"/api/runs/{run_id}").status_code == 404


def test_active_run_refuses_delete_and_export(make_client, project):
    gateway = FakeSearchGateway(pending_polls=1000)
    with make_client(search_gateway=gateway) as client:
        created = client.post("/api/runs", json=body(project["id"], provider_ids=[]))
        run_id = created.json()["id"]
        assert client.delete(f"/api/runs/{run_id}").status_code == 409
        assert client.get(f"/api/runs/{run_id}/export.csv").status_code == 409


def test_run_saves_the_selected_engine_with_each_search_result(make_client, project):
    gateway = FakeSearchGateway(pending_polls=0)
    with make_client(search_gateway=gateway, provider_factory=ProviderFactorySpy()) as client:
        request = body(project["id"], provider_ids=[], regions=[1],
                       region_targets=[{"region": 1, "engine": "yandex"}])
        created = client.post("/api/runs", json=request)
        assert created.status_code == 202
        snapshot = wait_done(client, created.json()["id"])
        assert [row["engine"] for row in snapshot["search"]] == ["yandex", "yandex"]
        assert [row["source"] for row in snapshot["summary_rows"]] == ["Яндекс", "Яндекс"]


def test_run_rejects_an_unsupported_search_engine(make_client, project):
    with make_client(search_gateway=FakeSearchGateway()) as client:
        request = body(project["id"], provider_ids=[], regions=[1],
                       region_targets=[{"region": 1, "engine": "google"}])
        response = client.post("/api/runs", json=request)
        assert response.status_code == 400


def test_invalid_run_and_cursor_errors(make_client, project):
    with make_client(search_gateway=FakeSearchGateway()) as client:
        assert client.post(
            "/api/runs", json=body(project["id"], provider_ids=[], regions=[]),
        ).status_code == 400
        assert client.get("/api/runs?cursor=!!!").status_code == 400
        assert client.get("/api/runs/missing").status_code == 404
        assert client.delete("/api/runs/missing").status_code == 404


def test_a_run_for_an_unknown_project_is_not_found(make_client, project):
    with make_client(search_gateway=FakeSearchGateway()) as client:
        response = client.post(
            "/api/runs", json=body("missing-project", provider_ids=[], regions=[1]),
        )
    assert response.status_code == 404


def test_history_can_be_scoped_to_one_project(make_client, project, database_dsn):
    other = ProjectRepository(database_dsn).create({"domain": "other.ru"})
    with make_client(search_gateway=FakeSearchGateway(pending_polls=0)) as client:
        created = client.post("/api/runs", json=body(project["id"], provider_ids=[], regions=[1]))
        client.post("/api/runs", json=body(other["id"], provider_ids=[], regions=[1]))

        scoped = client.get("/api/runs", params={"project_id": project["id"]}).json()

    assert [item["id"] for item in scoped["items"]] == [created.json()["id"]]


def test_disabled_yandex_skips_search_but_combined_run_finishes_models(make_client, project):
    gateway = FakeSearchGateway(pending_polls=0)
    with make_client(search_gateway=gateway, provider_factory=ProviderFactorySpy()) as client:
        response = client.put("/api/search/settings", json={"enabled": False})
        assert response.status_code == 200
        created = client.post("/api/runs", json=body(project["id"]))
        assert created.status_code == 202
        snapshot = wait_done(client, created.json()["id"])
        assert gateway.submitted == []
        assert snapshot["status"] == "done"
        assert len(snapshot["models"]) == 2
        assert all(row["status"] == "error" for row in snapshot["search"])
        assert all("выключен" in row["error"] for row in snapshot["search"])
