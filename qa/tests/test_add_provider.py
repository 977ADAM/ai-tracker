"""Provider groups and their models, managed from the settings dialog.

One custom provider owns an endpoint, a single key, and several separately
selectable models. The checks never assume an empty provider list: the suite runs
against a real instance where other providers may already exist, so every
assertion is scoped to the provider this run created.
"""

from __future__ import annotations

from uuid import uuid4

from playwright.sync_api import Page, expect

from app import Application
from pages.settings import SettingsPage

# A fresh name per run keeps a leftover from an earlier failure from colliding
# with this run, and makes the provider easy to recognise in the list.
RUN_MARK = uuid4().hex[:6]
NAME = f"QA провайдер {RUN_MARK}"
RENAMED = f"QA провайдер {RUN_MARK} н"
ENDPOINT = "https://api.example.com/v1/chat/completions"
MODEL = "qa-model"
MODEL_NAME = "Основная модель"
SECOND_MODEL = "qa-model-second"
SECOND_MODEL_NAME = "Вторая модель"
KEY = "qa-secret-key"

CONFIGURED = "Настроен"
NEEDS_KEY = "Ключ не задан"


def _option(provider: str, model_name: str) -> str:
    """The main page labels every model as «provider · model»."""
    return f"{provider} · {model_name}"


def _create(settings_page: SettingsPage, *, key: str = KEY) -> None:
    settings_page.add_provider(NAME, ENDPOINT, key, model_id=MODEL, model_name=MODEL_NAME)


def _create_with_second_model(settings_page: SettingsPage) -> None:
    """One provider holding two models, shared endpoint and key."""
    _create(settings_page)
    settings_page.configure(NAME)
    settings_page.add_model(NAME, api_id=SECOND_MODEL, display_name=SECOND_MODEL_NAME)
    settings_page.apply(NAME)
    expect(settings_page.notice).to_contain_text("Провайдер сохранён")


# -- the dialog itself --------------------------------------------------------


def test_dialog_offers_only_the_models_section(settings_page: SettingsPage) -> None:
    expect(settings_page.dialog.get_by_role("heading", name="Модели")).to_be_visible()
    expect(settings_page.rail.get_by_text("Модели")).to_be_visible()
    # «Модели» is the only section, and it marks the active one instead of being
    # yet another control that does nothing.
    expect(settings_page.rail.get_by_role("button")).to_have_count(0)
    expect(settings_page.rail.get_by_role("link")).to_have_count(0)
    expect(settings_page.dialog.get_by_role("button", name="Добавить провайдера")).to_be_visible()


def test_creation_form_offers_a_provider_and_its_first_model(settings_page: SettingsPage) -> None:
    settings_page.open_create_form()
    form = settings_page.create_form
    expect(form.get_by_label("Название провайдера")).to_be_enabled()
    expect(form.get_by_label("Адрес API")).to_be_enabled()
    expect(form.get_by_label("API-ключ")).to_be_enabled()
    expect(form.get_by_label("ID модели")).to_be_enabled()
    expect(form.get_by_label("Название модели")).to_be_enabled()
    expect(form.get_by_role("button", name="Создать")).to_be_enabled()
    # A provider must always keep at least one model, so its only row cannot go.
    expect(form.get_by_role("button", name="Удалить модель")).to_be_disabled()


def test_adds_a_provider_with_two_models(settings_page: SettingsPage) -> None:
    expect(settings_page.card(NAME)).to_have_count(0)

    _create_with_second_model(settings_page)

    card = settings_page.card(NAME)
    expect(card).to_be_visible()
    expect(card.get_by_role("img", name=CONFIGURED)).to_be_visible()
    assert NAME in settings_page.card_names()

    settings_page.configure(NAME)
    settings_page.expand_advanced(NAME)
    assert settings_page.model_ids(NAME) == [MODEL, SECOND_MODEL]
    expect(settings_page.model_row(NAME, SECOND_MODEL).get_by_label("Название модели")).to_have_value(SECOND_MODEL_NAME)
    expect(settings_page.endpoint_input).to_have_value(ENDPOINT)


# -- keys ---------------------------------------------------------------------


def test_never_shows_the_saved_key(settings_page: SettingsPage) -> None:
    _create(settings_page)
    expect(settings_page.notice).to_contain_text("Провайдер добавлен")

    settings_page.configure(NAME)
    expect(settings_page.key_input).to_have_value("")
    expect(settings_page.page.locator("body")).not_to_contain_text(KEY)
    # The whole document, not just the visible text: a key must not reach the
    # serialized page data the server sends to the browser either.
    assert KEY not in settings_page.page.content()


def test_a_provider_without_a_key_is_marked_and_can_be_given_one(settings_page: SettingsPage) -> None:
    settings_page.add_provider(NAME, ENDPOINT, "", model_id=MODEL, model_name=MODEL_NAME)
    expect(settings_page.notice).to_contain_text("Провайдер добавлен")
    expect(settings_page.card(NAME).get_by_role("img", name=NEEDS_KEY)).to_be_visible()

    settings_page.configure(NAME)
    settings_page.key_input.fill(KEY)
    settings_page.apply(NAME)

    expect(settings_page.notice).to_contain_text("Провайдер сохранён")
    expect(settings_page.card(NAME).get_by_role("img", name=CONFIGURED)).to_be_visible()


def test_a_blank_key_keeps_the_saved_one(settings_page: SettingsPage) -> None:
    _create(settings_page)
    expect(settings_page.card(NAME).get_by_role("img", name=CONFIGURED)).to_be_visible()

    settings_page.configure(NAME)
    settings_page.key_input.fill("")
    settings_page.apply(NAME)

    expect(settings_page.notice).to_contain_text("Провайдер сохранён")
    # A blank field must not have dropped the stored key.
    expect(settings_page.card(NAME).get_by_role("img", name=CONFIGURED)).to_be_visible()


def test_a_new_key_replaces_the_saved_one(settings_page: SettingsPage) -> None:
    _create(settings_page)

    settings_page.configure(NAME)
    settings_page.key_input.fill("qa-rotated-key")
    settings_page.apply(NAME)

    expect(settings_page.notice).to_contain_text("Провайдер сохранён")
    expect(settings_page.card(NAME).get_by_role("img", name=CONFIGURED)).to_be_visible()
    settings_page.configure(NAME)
    expect(settings_page.key_input).to_have_value("")
    expect(settings_page.page.locator("body")).not_to_contain_text("qa-rotated-key")


# -- editing ------------------------------------------------------------------


def test_applies_a_renamed_model(settings_page: SettingsPage) -> None:
    _create(settings_page)
    settings_page.configure(NAME)
    settings_page.rename_model(NAME, api_id=MODEL, display_name="Переименованная модель")
    settings_page.apply(NAME)
    expect(settings_page.notice).to_contain_text("Провайдер сохранён")

    settings_page.close()
    expect(settings_page.page.get_by_role("checkbox", name=_option(NAME, "Переименованная модель"))).to_be_visible()
    expect(settings_page.page.get_by_role("checkbox", name=_option(NAME, MODEL_NAME))).to_have_count(0)


def test_cancel_discards_edits(settings_page: SettingsPage) -> None:
    _create(settings_page)
    settings_page.configure(NAME)
    settings_page.rename_model(NAME, api_id=MODEL, display_name="Черновик")
    settings_page.cancel(NAME)

    # Reading the editor again proves the discarded value never reached the API.
    settings_page.configure(NAME)
    settings_page.expand_advanced(NAME)
    expect(settings_page.model_row(NAME, MODEL).get_by_label("Название модели")).to_have_value(MODEL_NAME)


def test_advanced_settings_start_collapsed(settings_page: SettingsPage) -> None:
    _create(settings_page)
    settings_page.configure(NAME)
    editor = settings_page.editor(NAME)
    expect(editor.locator("[data-models]")).to_have_count(0)

    settings_page.expand_advanced(NAME)

    expect(editor.locator("[data-models]")).to_be_visible()
    expect(settings_page.endpoint_input).to_have_value(ENDPOINT)


def test_renames_a_provider(settings_page: SettingsPage) -> None:
    _create(settings_page)
    settings_page.configure(NAME)
    settings_page.expand_advanced(NAME)
    settings_page.editor(NAME).get_by_label("Название провайдера").fill(RENAMED)
    settings_page.apply(NAME)

    expect(settings_page.notice).to_contain_text("Провайдер сохранён")
    expect(settings_page.card(RENAMED)).to_be_visible()
    expect(settings_page.card(NAME)).to_have_count(0)


def test_rejects_an_unsafe_endpoint(settings_page: SettingsPage) -> None:
    settings_page.open_create_form()
    settings_page.fill_provider(
        name=NAME,
        endpoint="http://localhost/chat/completions",
        key=KEY,
        model_id=MODEL,
        model_name=MODEL_NAME,
    )
    settings_page.create_form.get_by_role("button", name="Создать").click()

    expect(settings_page.alert).to_contain_text("HTTPS")
    expect(settings_page.card(NAME)).to_have_count(0)


def test_asks_for_a_model_before_creating_a_provider(settings_page: SettingsPage) -> None:
    settings_page.open_create_form()
    settings_page.fill_provider(name=NAME, endpoint=ENDPOINT, key=KEY)
    settings_page.create_form.get_by_label("ID модели").fill("")
    settings_page.create_form.get_by_role("button", name="Создать").click()

    expect(settings_page.alert).to_contain_text("модел")
    expect(settings_page.card(NAME)).to_have_count(0)


# -- removing -----------------------------------------------------------------


def test_removes_a_model_from_its_provider(settings_page: SettingsPage) -> None:
    _create_with_second_model(settings_page)

    settings_page.configure(NAME)
    settings_page.remove_model(NAME, SECOND_MODEL)
    settings_page.apply(NAME)
    expect(settings_page.notice).to_contain_text("Провайдер сохранён")

    settings_page.configure(NAME)
    settings_page.expand_advanced(NAME)
    assert settings_page.model_ids(NAME) == [MODEL]
    expect(settings_page.retain_model_button(NAME)).to_be_disabled()


def test_removes_a_provider_with_confirmation(settings_page: SettingsPage) -> None:
    _create_with_second_model(settings_page)
    expect(settings_page.card(NAME)).to_be_visible()

    settings_page.remove_provider(NAME)

    expect(settings_page.card(NAME)).to_have_count(0)
    settings_page.close()
    expect(settings_page.page.get_by_role("checkbox", name=_option(NAME, MODEL_NAME))).to_have_count(0)
    expect(settings_page.page.get_by_role("checkbox", name=_option(NAME, SECOND_MODEL_NAME))).to_have_count(0)


# -- the main page ------------------------------------------------------------


def test_every_model_is_a_separate_check_option(settings_page: SettingsPage) -> None:
    _create_with_second_model(settings_page)
    settings_page.close()

    expect(settings_page.page.get_by_role("checkbox", name=_option(NAME, MODEL_NAME))).to_be_visible()
    expect(settings_page.page.get_by_role("checkbox", name=_option(NAME, SECOND_MODEL_NAME))).to_be_visible()


def test_a_removed_model_leaves_the_check_list(settings_page: SettingsPage) -> None:
    _create_with_second_model(settings_page)
    settings_page.configure(NAME)
    settings_page.remove_model(NAME, SECOND_MODEL)
    settings_page.apply(NAME)
    settings_page.close()

    expect(settings_page.page.get_by_role("checkbox", name=_option(NAME, MODEL_NAME))).to_be_visible()
    expect(settings_page.page.get_by_role("checkbox", name=_option(NAME, SECOND_MODEL_NAME))).to_have_count(0)


# -- closing ------------------------------------------------------------------


def test_escape_returns_focus_to_the_opener(settings_page: SettingsPage) -> None:
    settings_page.dismiss_with_escape()
    expect(settings_page.opener).to_be_focused()


def test_close_button_returns_focus_to_the_opener(settings_page: SettingsPage) -> None:
    settings_page.close()
    expect(settings_page.opener).to_be_focused()


def test_the_backdrop_closes_the_dialog(settings_page: SettingsPage) -> None:
    settings_page.dismiss_with_backdrop()
    expect(settings_page.opener).to_be_focused()


def test_keyboard_focus_stays_inside_the_open_dialog(settings_page: SettingsPage) -> None:
    settings_page.open_create_form()
    for _ in range(12):
        settings_page.page.keyboard.press("Tab")
        assert settings_page.dialog.evaluate("dialog => dialog.contains(document.activeElement)"), (
            "Фокус вышел за пределы открытого диалога"
        )


def test_dialog_reopens_with_the_saved_provider(settings_page: SettingsPage) -> None:
    _create(settings_page)
    settings_page.close()
    settings_page.opener.click()

    expect(settings_page.card(NAME)).to_be_visible()


# -- the service boundary -----------------------------------------------------


def test_the_browser_can_reach_the_settings_api(settings_page: SettingsPage, application: Application) -> None:
    """The page talks to Python through the SvelteKit BFF, not directly."""
    response = settings_page.page.request.get(application.url("/api/providers/settings"))
    assert response.status == 200, (
        f"BFF-роут /api/providers/settings ответил {response.status}. "
        "Без него сохранение провайдера из браузера недостижимо."
    )
    assert "api_key" not in response.text()


def test_page_has_no_console_errors(settings_page: SettingsPage, page: Page) -> None:
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)

    _create_with_second_model(settings_page)

    assert errors == []


def test_legacy_settings_route_is_gone(settings_page: SettingsPage, application: Application) -> None:
    response = settings_page.page.request.get(application.url("/settings"))
    assert response.status == 404
