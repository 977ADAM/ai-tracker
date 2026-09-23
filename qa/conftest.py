"""Fixtures for the browser checks.

The suite does not manage the services. Bring them up yourself, and a run
against a stopped app reports which service is missing instead of failing with
a browser timeout:

    make backend     # Python API on 127.0.0.1:8000
    make frontend    # SvelteKit on 127.0.0.1:5173
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Iterator

import pytest
from playwright.sync_api import Page

from app import Application, configured_application, missing_services
from pages.settings import SettingsPage

# The browser window is visible by default; set QA_HEADLESS=1 for a headless run.
HEADLESS_VARIABLE = "QA_HEADLESS"

SERVICES_DOWN_MESSAGE = (
    "Сервисы не подняты: {missing}. Ожидались {base_url} и {api_url}. "
    "Запустите `make backend` и `make frontend` — или укажите свои адреса "
    "через QA_BASE_URL и QA_API_URL."
)


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict) -> dict:
    """Show the browser window unless the run asks for headless.

    The plugin's own fixture is requested by name and merged back, so
    `--browser-channel` and `--slowmo` keep working. An explicit `--headed`
    still wins over `QA_HEADLESS=1`.
    """
    headless = os.getenv(HEADLESS_VARIABLE) == "1"
    if browser_type_launch_args.get("headless") is False:
        headless = False
    return {**browser_type_launch_args, "headless": headless}


@pytest.fixture(scope="session")
def application() -> Application:
    return configured_application()


@pytest.fixture(scope="session", autouse=True)
def require_running_services(application: Application) -> None:
    """Warn and skip when there is nothing to check, rather than test nothing quietly."""
    missing = missing_services(application)
    if not missing:
        return
    message = SERVICES_DOWN_MESSAGE.format(
        missing=", ".join(missing),
        base_url=application.base_url,
        api_url=application.api_url,
    )
    warnings.warn(message, UserWarning, stacklevel=1)
    pytest.skip(message)


@pytest.fixture(autouse=True)
def no_connection_survives_a_test(application: Application) -> Iterator[None]:
    """Delete only what this test created, so no test key stays in the store.

    The suite talks to a real instance backed by a real credential store, so
    the cleanup is scoped to the difference: connections that already existed
    before the test are left untouched.
    """
    before = {str(item["id"]) for item in _safe_connections(application)}
    yield
    for connection in _safe_connections(application):
        if str(connection["id"]) not in before and connection.get("can_delete"):
            application.forget(str(connection["id"]))


def _safe_connections(application: Application) -> list[dict]:
    try:
        return application.connections()
    except Exception:  # noqa: BLE001 - cleanup must not hide the test result
        return []


@pytest.fixture
def settings_page(page: Page, application: Application) -> SettingsPage:
    return SettingsPage(page, application.base_url).open()
