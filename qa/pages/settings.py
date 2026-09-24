"""The provider and model settings dialog on the main page.

One custom provider owns an endpoint, one key, and a list of models. The dialog
shows a card per provider; «Настроить» expands an inline editor whose endpoint and
model rows live behind «Дополнительные настройки».
"""

from __future__ import annotations

import re

from playwright.sync_api import Locator, Page, expect

CREATE_FORM_NAME = "Новый провайдер"
ADVANCED_LABEL = "Дополнительные настройки"


def _slug(value: str) -> str:
    """A predictable model API ID for a provider created without one."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "model"


class SettingsPage:
    """Adding, editing, and removing providers and their models."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url

    # -- shell -------------------------------------------------------------

    def open(self) -> SettingsPage:
        self.page.goto(self.base_url, wait_until="networkidle")
        self.opener.click()
        expect(self.dialog).to_be_visible()
        return self

    @property
    def opener(self) -> Locator:
        """The header button that opens the dialog and takes focus back on close."""
        return self.page.get_by_role("button", name="Настройки API")

    @property
    def dialog(self) -> Locator:
        return self.page.get_by_role("dialog", name="Настройки API")

    @property
    def close_button(self) -> Locator:
        return self.dialog.get_by_role("button", name="Закрыть панель")

    @property
    def rail(self) -> Locator:
        return self.dialog.get_by_role("navigation", name="Разделы настроек")

    @property
    def configuration_file_button(self) -> Locator:
        return self.dialog.get_by_role("button", name="Открыть файл конфигурации")

    @property
    def configuration_dialog(self) -> Locator:
        return self.page.get_by_role("dialog", name="Файл конфигурации")

    def show_configuration_file(self) -> SettingsPage:
        self.configuration_file_button.click()
        expect(self.configuration_dialog).to_be_visible()
        return self

    def close_configuration_file(self) -> SettingsPage:
        self.configuration_dialog.get_by_role("button", name="Закрыть файл конфигурации").click()
        expect(self.configuration_dialog).to_have_count(0)
        expect(self.dialog).to_be_visible()
        return self

    def close(self) -> SettingsPage:
        self.close_button.click()
        expect(self.dialog).to_have_count(0)
        return self

    def dismiss_with_escape(self) -> SettingsPage:
        self.page.keyboard.press("Escape")
        expect(self.dialog).to_have_count(0)
        return self

    def dismiss_with_backdrop(self) -> SettingsPage:
        self.page.locator("[data-backdrop]").click(position={"x": 4, "y": 4})
        expect(self.dialog).to_have_count(0)
        return self

    # -- messages ----------------------------------------------------------

    @property
    def alert(self) -> Locator:
        return self.dialog.get_by_role("alert")

    @property
    def notice(self) -> Locator:
        return self.dialog.get_by_role("status")

    # -- provider cards ----------------------------------------------------

    @property
    def cards(self) -> Locator:
        return self.dialog.locator("article[data-provider]")

    def card(self, name: str) -> Locator:
        return self.dialog.get_by_role("article", name=name, exact=True)

    def card_count(self) -> int:
        return self.cards.count()

    def card_names(self) -> list[str]:
        return [value.strip() for value in self.cards.locator("h4").all_inner_texts()]

    def provider_ids(self) -> list[str]:
        return [value for value in self.cards.evaluate_all("cards => cards.map((card) => card.dataset.provider)") if value]

    @property
    def empty_state(self) -> Locator:
        return self.dialog.get_by_text("Провайдеры пока не добавлены")

    # -- editing one provider ---------------------------------------------

    def editor(self, provider: str) -> Locator:
        return self.card(provider).locator("[data-editor]")

    def configure(self, provider: str) -> SettingsPage:
        self.card(provider).get_by_role("button", name="Настроить").click()
        expect(self.editor(provider)).to_be_visible()
        return self

    def apply(self, provider: str) -> SettingsPage:
        """Apply the open editor. It closes only when the write succeeded."""
        self.editor(provider).get_by_role("button", name="Применить").click()
        expect(self.editor(provider)).to_have_count(0)
        return self

    def cancel(self, provider: str) -> SettingsPage:
        self.editor(provider).get_by_role("button", name="Отмена").click()
        expect(self.editor(provider)).to_have_count(0)
        return self

    def remove_provider(self, provider: str) -> SettingsPage:
        self.configure(provider)
        self.accept_next_dialog()
        self.editor(provider).get_by_role("button", name="Удалить провайдера").click()
        expect(self.card(provider)).to_have_count(0)
        return self

    @property
    def key_input(self) -> Locator:
        """The key field of the only open editor or creation card."""
        return self.dialog.get_by_label("API-ключ", exact=True)

    def expand_advanced(self, provider: str) -> SettingsPage:
        toggle = self.editor(provider).get_by_role("button", name=ADVANCED_LABEL)
        if toggle.get_attribute("aria-expanded") != "true":
            toggle.click()
        expect(self.editor(provider).locator("[data-models]")).to_be_visible()
        return self

    @property
    def endpoint_input(self) -> Locator:
        return self.dialog.get_by_label("Адрес API", exact=True)

    # -- model rows --------------------------------------------------------

    def model_rows(self, provider: str) -> Locator:
        return self.editor(provider).locator("[data-model-row]")

    def model_row(self, provider: str, api_id: str) -> Locator:
        rows = self.model_rows(provider)
        for index in range(rows.count()):
            row = rows.nth(index)
            if row.get_by_label("ID модели").input_value() == api_id:
                return row
        raise AssertionError(f"У модели {api_id!r} провайдера {provider!r} нет строки в редакторе")

    def model_ids(self, provider: str) -> list[str]:
        rows = self.model_rows(provider)
        return [rows.nth(index).get_by_label("ID модели").input_value() for index in range(rows.count())]

    def add_model(self, provider: str, *, api_id: str, display_name: str) -> SettingsPage:
        self.expand_advanced(provider)
        models = self.editor(provider).locator("[data-models]")
        models.get_by_role("button", name="Добавить модель").click()
        row = self.model_rows(provider).last
        row.get_by_label("ID модели").fill(api_id)
        row.get_by_label("Название модели").fill(display_name)
        return self

    def rename_model(self, provider: str, *, api_id: str, display_name: str) -> SettingsPage:
        self.expand_advanced(provider)
        self.model_row(provider, api_id).get_by_label("Название модели").fill(display_name)
        return self

    def remove_model(self, provider: str, api_id: str) -> SettingsPage:
        self.expand_advanced(provider)
        self.model_row(provider, api_id).get_by_role("button", name="Удалить модель").click()
        return self

    def retain_model_button(self, provider: str) -> Locator:
        """Disabled while a provider holds a single model: one must always remain."""
        return self.model_row(provider, self.model_ids(provider)[0]).get_by_role("button", name="Удалить модель")

    # -- creating a provider ----------------------------------------------

    @property
    def create_form(self) -> Locator:
        return self.dialog.get_by_role("article", name=CREATE_FORM_NAME, exact=True)

    def open_create_form(self) -> SettingsPage:
        self.dialog.get_by_role("button", name="Добавить провайдера").click()
        expect(self.create_form).to_be_visible()
        return self

    def fill_provider(
        self,
        *,
        name: str,
        endpoint: str,
        key: str,
        model_id: str | None = None,
        model_name: str | None = None,
    ) -> SettingsPage:
        form = self.create_form
        form.get_by_label("Название провайдера").fill(name)
        form.get_by_label("Адрес API").fill(endpoint)
        form.get_by_label("API-ключ").fill(key)
        first = form.locator("[data-model-row]").first
        first.get_by_label("ID модели").fill(model_id if model_id is not None else _slug(name))
        first.get_by_label("Название модели").fill(model_name if model_name is not None else name)
        return self

    def create_provider(self) -> SettingsPage:
        self.create_form.get_by_role("button", name="Создать").click()
        expect(self.create_form).to_have_count(0)
        return self

    def add_provider(
        self,
        name: str,
        endpoint: str,
        key: str,
        *,
        model_id: str | None = None,
        model_name: str | None = None,
    ) -> SettingsPage:
        self.open_create_form()
        self.fill_provider(name=name, endpoint=endpoint, key=key, model_id=model_id, model_name=model_name)
        return self.create_provider()

    def cancel_create_form(self) -> SettingsPage:
        self.create_form.get_by_role("button", name="Отмена").click()
        expect(self.create_form).to_have_count(0)
        return self

    # -- helpers -----------------------------------------------------------

    def accept_next_dialog(self) -> None:
        """Removal asks for confirmation through a native dialog."""
        self.page.once("dialog", lambda dialog: dialog.accept())
