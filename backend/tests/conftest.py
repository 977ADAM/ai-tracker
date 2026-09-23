"""Shared fixtures: a temporary config dir, fake credentials, and an HTTP client."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.connections import ConnectionRepository
from app.main import create_app
from tests.fakes import TEST_PRESETS, MemorySecrets

TEST_HOST = "testserver"

ENV_KEY_VARIABLES = ("GIGACHAT_AUTH_KEY", "DEEPSEEK_API_KEY")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the API-key fallbacks out of every test unless it sets one itself."""
    for variable in ENV_KEY_VARIABLES:
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def secrets() -> MemorySecrets:
    return MemorySecrets()


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def settings(config_dir: Path) -> Settings:
    """A settings object that allows the test client host and ships test presets."""
    return Settings(config_dir=config_dir, allowed_hosts=(TEST_HOST,), presets=TEST_PRESETS)


@pytest.fixture
def repository(settings: Settings, secrets: MemorySecrets) -> ConnectionRepository:
    return ConnectionRepository(
        settings.config_dir,
        secrets,
        presets=settings.presets,
        env_api_key=settings.env_api_key,
        service_name=settings.service_name,
    )


@pytest.fixture
def make_client(
    settings: Settings,
    secrets: MemorySecrets,
) -> Callable[..., TestClient]:
    def build(**overrides: object) -> TestClient:
        return TestClient(create_app(settings, secrets=secrets, **overrides))

    return build


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()
