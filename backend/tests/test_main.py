"""The application factory, its host guard, and its API-only surface."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app, create_app


def test_the_module_level_app_is_ready_for_uvicorn():
    assert app.title == "ИИ-трекинг API"


def test_the_service_exposes_api_routes_only(client):
    assert client.get("/").status_code == 404
    assert client.get("/settings").status_code == 404
    assert client.get("/static/app.js").status_code == 404
    assert client.get("/api/providers").status_code == 200


def test_an_unknown_host_is_rejected(settings):
    client = TestClient(create_app(settings))
    response = client.get("/api/providers", headers={"host": "evil.example.com"})
    assert response.status_code == 400


def test_the_default_settings_allow_loopback_only(config_dir):
    settings = Settings(config_dir=config_dir)
    client = TestClient(create_app(settings))
    assert client.get("/api/providers").status_code == 400
    assert client.get("/api/providers", headers={"host": "127.0.0.1"}).status_code == 200
