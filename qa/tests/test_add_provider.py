"""Managing an OpenAI-compatible connection from the settings dialog.

The checks never assume an empty connection list: the suite runs against a real
instance where other connections may already exist, so every assertion is scoped
to the connection this run created.
"""

from __future__ import annotations

from uuid import uuid4

from playwright.sync_api import Page, expect

from app import Application
from pages.settings import SettingsPage

# A fresh name per run keeps a leftover from an earlier failure from colliding
# with this run, and makes the connection easy to recognise in the list.
RUN_MARK = uuid4().hex[:6]
NAME = f"QA проверка {RUN_MARK}"
ENDPOINT = "https://api.example.com/v1/chat/completions"
MODEL = "qa-model"
KEY = "qa-secret-key"


def test_settings_page_offers_the_add_form(settings_page: SettingsPage) -> None:
    settings_page.open_form()
    expect(settings_page.name_input).to_be_visible()
    expect(settings_page.name_input).to_be_enabled()
    expect(settings_page.endpoint_input).to_be_enabled()
    expect(settings_page.model_input).to_be_enabled()
    expect(settings_page.key_input).to_be_enabled()
    expect(settings_page.submit_button).to_be_enabled()
    # A new connection is OpenAI-compatible, so the GigaChat scope field stays away.
    expect(settings_page.page.get_by_label("Область доступа GigaChat")).to_have_count(0)


def test_adds_a_connection_and_shows_it_in_the_list(settings_page: SettingsPage) -> None:
    expect(settings_page.connection(NAME)).to_have_count(0)

    settings_page.add_connection(name=NAME, endpoint=ENDPOINT, model=MODEL, key=KEY)

    expect(settings_page.notice).to_have_text("Подключение сохранено")
    card = settings_page.connection(NAME)
    expect(card).to_be_visible()
    expect(card).to_contain_text(MODEL)
    expect(card).to_contain_text(ENDPOINT)
    expect(card).to_contain_text("Готово к проверке")
    assert NAME in settings_page.connection_names()


def test_never_shows_the_saved_key(settings_page: SettingsPage) -> None:
    settings_page.add_connection(name=NAME, endpoint=ENDPOINT, model=MODEL, key=KEY)
    expect(settings_page.notice).to_have_text("Подключение сохранено")

    settings_page.connection(NAME).get_by_role("button", name=f"Настроить {NAME}").click()
    expect(settings_page.key_input).to_have_value("")
    expect(settings_page.page.locator("body")).not_to_contain_text(KEY)
    # The whole document, not just the visible text: a key must not reach the
    # serialized page data the server sends to the browser either.
    assert KEY not in settings_page.page.content()


def test_rejects_an_unsafe_endpoint(settings_page: SettingsPage) -> None:
    settings_page.add_connection(
        name=NAME,
        endpoint="http://localhost/chat/completions",
        model=MODEL,
        key=KEY,
    )

    expect(settings_page.alert).to_contain_text("HTTPS")
    expect(settings_page.connection(NAME)).to_have_count(0)


def test_removes_a_saved_connection(settings_page: SettingsPage) -> None:
    settings_page.add_connection(name=NAME, endpoint=ENDPOINT, model=MODEL, key=KEY)
    expect(settings_page.connection(NAME)).to_be_visible()

    settings_page.remove(NAME)

    expect(settings_page.connection(NAME)).to_have_count(0)


def test_the_browser_can_reach_the_connection_api(settings_page: SettingsPage, application: Application) -> None:
    """The page talks to Python through the SvelteKit BFF, not directly."""
    response = settings_page.page.request.get(application.url("/api/providers"))
    assert response.status == 200, (
        f"BFF-роут /api/providers ответил {response.status}. "
        "Без него сохранение подключения из браузера недостижимо."
    )


def test_page_has_no_console_errors(settings_page: SettingsPage, page: Page) -> None:
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)

    settings_page.add_connection(name=NAME, endpoint=ENDPOINT, model=MODEL, key=KEY)
    expect(settings_page.notice).to_have_text("Подключение сохранено")

    assert errors == []


def test_dialog_closes_and_reopens_with_saved_connections(settings_page: SettingsPage) -> None:
    settings_page.add_connection(name=NAME, endpoint=ENDPOINT, model=MODEL, key=KEY)
    settings_page.dialog.get_by_role("button", name="Закрыть панель").click()
    expect(settings_page.dialog).to_have_count(0)

    settings_page.page.get_by_role("button", name="Настройки API").click()
    expect(settings_page.connection(NAME)).to_be_visible()


def test_saved_connection_is_available_for_checking(settings_page: SettingsPage) -> None:
    settings_page.add_connection(name=NAME, endpoint=ENDPOINT, model=MODEL, key=KEY)
    settings_page.dialog.get_by_role("button", name="Закрыть панель").click()

    expect(settings_page.page.get_by_role("checkbox", name=NAME)).to_be_visible()


def test_edit_saved_connection(settings_page: SettingsPage) -> None:
    settings_page.add_connection(name=NAME, endpoint=ENDPOINT, model=MODEL, key=KEY)
    settings_page.connection(NAME).get_by_role("button", name=f"Настроить {NAME}").click()
    settings_page.model_input.fill("qa-model-updated")
    settings_page.save()

    expect(settings_page.connection(NAME)).to_contain_text("qa-model-updated")


def test_legacy_settings_route_is_gone(settings_page: SettingsPage, application: Application) -> None:
    response = settings_page.page.request.get(application.url("/settings"))
    assert response.status == 404
