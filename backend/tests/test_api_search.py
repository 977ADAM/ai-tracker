"""The deferred Yandex search endpoints."""

from __future__ import annotations

import time

from app.api.deps import get_container
from app.db.search_settings import SearchSettingsRepository
from tests.fakes import FakeSearchGateway

FOUND_REGION = 1
ABSENT_REGION = 213
ERROR_REGION = 65

BODY = {"domain": "example.ru", "prompts_text": "цветы", "regions": [FOUND_REGION]}


def wait_for(client, job_id: str, *, completed: int, timeout: float = 5.0) -> dict:
    """Poll the status route until the job reaches the expected number of finished pairs."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = client.get(f"/api/search/{job_id}").json()
        if snapshot["completed"] >= completed:
            return snapshot
        time.sleep(0.01)
    raise AssertionError("the job did not reach the expected state")


def test_creation_returns_202_and_an_immediate_snapshot(make_client):
    gateway = FakeSearchGateway(pending_polls=1)

    with make_client(search_gateway=gateway) as client:
        response = client.post("/api/search", json={**BODY, "regions": [FOUND_REGION, ERROR_REGION]})

        assert response.status_code == 202
        created = response.json()
        assert set(created) == {"id", "total", "status"}
        assert created["total"] == 2
        assert created["status"] == "pending"

        snapshot = client.get(f"/api/search/{created['id']}")
        assert snapshot.status_code == 200
        body = snapshot.json()
        assert body["id"] == created["id"]
        assert body["domain"] == "example.ru"
        assert body["regions"] == [FOUND_REGION, ERROR_REGION]
        assert body["total"] == 2
        assert body["completed"] == 0
        assert [row["region_id"] for row in body["results"]] == [FOUND_REGION, ERROR_REGION]
        assert body["results"][0]["prompt"] == "цветы"


def test_an_unknown_or_forged_job_id_is_not_found(make_client):
    with make_client(search_gateway=FakeSearchGateway()) as client:
        # `..%2Fproviders` stays inside the job-id segment: the route decodes it
        # and finds no such job instead of serving another resource.
        for job_id in ["no-such-job", "..%2Fproviders", "a" * 200, "%20"]:
            response = client.get(f"/api/search/{job_id}")

            assert response.status_code == 404, job_id
            assert isinstance(response.json()["detail"], str)
            assert "operation" not in response.text.lower()


def test_regions_come_from_the_catalog(make_client):
    with make_client(search_gateway=FakeSearchGateway()) as client:
        response = client.get("/api/search/regions")

    assert response.status_code == 200
    regions = response.json()
    assert {"id": FOUND_REGION, "name": "Москва и Московская область"} in regions
    assert {"id": ABSENT_REGION, "name": "Москва"} in regions
    assert len({region["id"] for region in regions}) == len(regions)
    assert set(regions[0]) == {"id", "name"}


def test_invalid_input_is_rejected_as_400_before_any_paid_request(make_client):
    gateway = FakeSearchGateway()

    with make_client(search_gateway=gateway) as client:
        payloads = [
            {**BODY, "regions": []},
            {**BODY, "regions": [FOUND_REGION, FOUND_REGION]},
            {**BODY, "regions": [999_999]},
            {**BODY, "regions": [FOUND_REGION, ABSENT_REGION, 2, 54, 65, 43]},
            {**BODY, "prompts_text": "x" * 401},
            {**BODY, "domain": "ftp://example.ru"},
            {**BODY, "domain": ""},
            {**BODY, "prompts_text": "вопрос\n" * 21},
        ]
        for payload in payloads:
            response = client.post("/api/search", json=payload)

            assert response.status_code == 400, payload
            assert isinstance(response.json()["detail"], str)

    assert gateway.submitted == []


def test_missing_credentials_reject_creation(make_client):
    with make_client() as client:
        response = client.post("/api/search", json=BODY)

    assert response.status_code == 400
    assert response.json() == {"detail": "Не заданы ключ и каталог для поиска Яндекса"}


def test_a_finished_job_reports_found_absent_and_failed_pairs(make_client):
    gateway = FakeSearchGateway({ABSENT_REGION: "absent", ERROR_REGION: "error"})

    with make_client(search_gateway=gateway) as client:
        created = client.post("/api/search", json={**BODY, "regions": [FOUND_REGION, ABSENT_REGION, ERROR_REGION]}).json()
        body = wait_for(client, created["id"], completed=3)

    assert body["completed"] == 3
    assert body["status"] == "done"
    assert [row["status"] for row in body["results"]] == ["found", "absent", "error"]
    assert body["summary"] == {"successful": 2, "found": 1, "failed": 1}
    assert body["results"][0]["position"] == 2
    assert body["results"][0]["url"] == "https://example.ru/page"
    assert body["results"][1]["url"] is None
    assert body["results"][2]["error"] == "Поиск Яндекса завершился ошибкой"


def test_a_public_response_carries_no_operation_id_or_credentials(make_client):
    gateway = FakeSearchGateway({ERROR_REGION: "error"}, message="Не удалось получить выдачу Яндекса")

    with make_client(search_gateway=gateway) as client:
        created = client.post("/api/search", json={**BODY, "regions": [FOUND_REGION, ERROR_REGION]})
        body = wait_for(client, created.json()["id"], completed=2)

    text = f"{created.text}{body}"
    assert "yandex-operation" not in text
    assert "api_key" not in text
    assert "folder_id" not in text
    assert "rawData" not in text


def test_disabled_yandex_rejects_direct_search_without_submission(make_client):
    gateway = FakeSearchGateway()
    with make_client(search_gateway=gateway) as client:
        assert client.put("/api/search/settings", json={"enabled": False}).status_code == 200
        response = client.post("/api/search", json=BODY)
        assert response.status_code == 400
        assert "выключен" in response.json()["detail"]
    assert gateway.submitted == []


def test_settings_get_preserves_injected_search_gateway(make_client, settings, secrets):
    gateway = FakeSearchGateway(pending_polls=0)
    repository = SearchSettingsRepository(
        settings.config_dir, secrets, env_api_key="env-key",
        env_folder_id="env-folder", service_name=settings.service_name,
    )
    with make_client(search_gateway=gateway, search_settings_repository=repository) as client:
        assert client.get("/api/search/settings").status_code == 200
        assert client.app.dependency_overrides[get_container]().search.gateway is gateway
        created = client.post("/api/search", json=BODY)
        assert created.status_code == 202
        assert wait_for(client, created.json()["id"], completed=1)["status"] == "done"
    assert gateway.submitted == [("цветы", FOUND_REGION)]


def test_injected_gateway_returns_after_search_settings_recover(make_client, config_dir):
    gateway = FakeSearchGateway(pending_polls=0)
    path = config_dir / "search-settings.json"
    path.write_text("{", encoding="utf-8")
    with make_client(search_gateway=gateway) as client:
        assert client.get("/api/search/settings").status_code == 503
        assert client.post("/api/search", json=BODY).status_code == 400
        assert gateway.submitted == []
        path.write_text('{"enabled": true}', encoding="utf-8")
        assert client.get("/api/search/settings").status_code == 200
        created = client.post("/api/search", json=BODY)
        assert created.status_code == 202
        wait_for(client, created.json()["id"], completed=1)
    assert gateway.submitted == [("цветы", FOUND_REGION)]


def test_injected_gateway_respects_disabled_setting_and_reenable(make_client):
    gateway = FakeSearchGateway(pending_polls=0)
    with make_client(search_gateway=gateway) as client:
        assert client.put("/api/search/settings", json={"enabled": False}).status_code == 200
        disabled = client.post("/api/search", json=BODY)
        assert disabled.status_code == 400
        assert "выключен" in disabled.json()["detail"]
        assert gateway.submitted == []
        assert client.put("/api/search/settings", json={"enabled": True}).status_code == 200
        created = client.post("/api/search", json=BODY)
        assert created.status_code == 202
        wait_for(client, created.json()["id"], completed=1)
    assert gateway.submitted == [("цветы", FOUND_REGION)]
