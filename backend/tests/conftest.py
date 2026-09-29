"""Shared fixtures: a temporary config dir, fake credentials, and an HTTP client.

`app.main` assembles the application at import, so the fixtures here swap its
container through FastAPI's dependency overrides instead of rebuilding the app.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import build_container, get_container
from app.core.config import Settings
from app.db.connections import ConnectionRepository
from app.main import app as application
from tests.fakes import TEST_PRESETS, MemorySecrets

# The trusted-host guard allows loopback only, so the test client speaks as 127.0.0.1.
TEST_BASE_URL = "http://127.0.0.1"

ENV_KEY_VARIABLES = (
    "DEEPSEEK_API_KEY",
    "YANDEX_SEARCH_API_KEY",
    "YANDEX_SEARCH_FOLDER_ID",
    # Legacy names for the same Yandex credentials.
    "API_KEY",
    "FOLDER_ID",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every credential fallback out of tests unless one sets it itself.

    The application reads the repository `.env` at import, so a developer's own
    keys would otherwise reach the tests and turn a "missing credentials" case
    into a real paid call.
    """
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
    """Test settings: a temporary config dir and injected built-in templates."""
    return Settings(config_dir=config_dir, presets=TEST_PRESETS)


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
) -> Iterator[Callable[..., TestClient]]:
    def build(
        *,
        client_options: dict[str, object] | None = None,
        **overrides: object,
    ) -> TestClient:
        # The container is built once, exactly like `app.main` builds it at
        # import: the search service keeps job state in memory, so every request
        # of one client must reach the same service.
        container = build_container(settings, secrets=secrets, **overrides)
        application.dependency_overrides[get_container] = lambda: container
        return TestClient(application, base_url=TEST_BASE_URL, **(client_options or {}))

    yield build
    application.dependency_overrides.clear()


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()
