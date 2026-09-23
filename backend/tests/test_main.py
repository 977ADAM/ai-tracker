"""The assembled application, its host guard, and its API-only surface."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_check_service
from app.main import API_PREFIX, TITLE, app, container, settings


def test_the_module_level_app_is_ready_for_uvicorn():
    assert app.title == TITLE
    assert app.state.settings is settings
    assert app.state.container is container


def test_the_api_lives_under_a_prefix(client):
    assert API_PREFIX == "/api"
    assert client.get("/api/form").status_code == 200
    assert client.get("/form").status_code == 404


def test_the_service_exposes_api_routes_only(client):
    assert client.get("/").status_code == 404
    assert client.get("/settings").status_code == 404
    assert client.get("/static/app.js").status_code == 404
    assert client.get("/api/providers").status_code == 200


def test_an_unknown_host_is_rejected():
    client = TestClient(app, base_url="http://evil.example.com")
    assert client.get("/api/providers").status_code == 400


def test_a_loopback_host_is_allowed(client):
    assert client.get("/api/providers").status_code == 200


def test_an_application_error_is_reported_as_one_string(client):
    response = client.post(
        "/api/check",
        json={"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ["нет такого"]},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Выбрано неизвестное подключение"}


def test_an_unexpected_error_stays_json_shaped_and_silent(make_client):
    class Broken:
        def run(self, _payload: object) -> dict:
            raise RuntimeError("private traceback")

    client = make_client(client_options={"raise_server_exceptions": False})
    app.dependency_overrides[get_check_service] = lambda: Broken()

    response = client.post(
        "/api/check",
        json={"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ["x"]},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Внутренняя ошибка сервиса"}
    assert "private traceback" not in response.text
