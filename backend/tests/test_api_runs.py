"""Run history, snapshots, conflicts and CSV over HTTP."""

from __future__ import annotations

import csv
import io
import time

from tests.fakes import FakeSearchGateway, ProviderFactorySpy

BODY = {"brand": "Ромашка", "domain": "example.ru", "prompts_text": "цветы\nподарки",
        "provider_ids": ["gigachat"], "regions": [1]}


def wait_done(client, run_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}")
        if response.json()["status"] != "pending":
            return response.json()
        time.sleep(0.01)
    raise AssertionError("run did not finish")


def test_combined_run_history_snapshot_and_csv(make_client):
    gateway = FakeSearchGateway(pending_polls=0)
    with make_client(search_gateway=gateway, provider_factory=ProviderFactorySpy()) as client:
        created = client.post("/api/runs", json=BODY)
        assert created.status_code == 202
        assert set(created.json()) == {"id", "status"}
        run_id = created.json()["id"]
        snapshot = wait_done(client, run_id)
        assert len(snapshot["summary_rows"]) == 4
        assert [row["source"] for row in snapshot["summary_rows"]] == ["Яндекс", "Яндекс", "GigaChat", "GigaChat"]
        assert set(snapshot) == {"id", "created_at", "finished_at", "status", "brand", "domain",
                                 "prompts", "provider_ids", "regions", "models", "search", "summary_rows"}
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


def test_active_run_refuses_delete_and_export(make_client):
    gateway = FakeSearchGateway(pending_polls=1000)
    with make_client(search_gateway=gateway) as client:
        created = client.post("/api/runs", json={**BODY, "provider_ids": []})
        run_id = created.json()["id"]
        assert client.delete(f"/api/runs/{run_id}").status_code == 409
        assert client.get(f"/api/runs/{run_id}/export.csv").status_code == 409


def test_invalid_run_and_cursor_errors(make_client):
    with make_client(search_gateway=FakeSearchGateway()) as client:
        assert client.post("/api/runs", json={**BODY, "provider_ids": [], "regions": []}).status_code == 400
        assert client.get("/api/runs?cursor=!!!").status_code == 400
        assert client.get("/api/runs/missing").status_code == 404
        assert client.delete("/api/runs/missing").status_code == 404
