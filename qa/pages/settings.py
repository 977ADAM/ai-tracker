"""The connection settings page at `/settings`."""

from __future__ import annotations

from playwright.sync_api import Locator, Page, expect


class SettingsPage:
    """Adding, editing, and removing an API connection."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url

    def open(self) -> SettingsPage:
        self.page.goto(f"{self.base_url}/settings")
        expect(self.page.get_by_role("heading", name="Подключения API")).to_be_visible()
        return self

    # -- form controls ----------------------------------------------------

    @property
    def name_input(self) -> Locator:
        return self.page.get_by_label("Название подключения", exact=True)

    @property
    def endpoint_input(self) -> Locator:
        return self.page.get_by_label("Адрес API", exact=True)

    @property
    def model_input(self) -> Locator:
        return self.page.get_by_label("Модель", exact=True)

    @property
    def key_input(self) -> Locator:
        return self.page.get_by_label("API-ключ", exact=True)

    @property
    def submit_button(self) -> Locator:
        return self.page.get_by_role("button", name="Сохранить подключение")

    @property
    def alert(self) -> Locator:
        return self.page.get_by_role("alert")

    @property
    def notice(self) -> Locator:
        return self.page.get_by_role("status")

    # -- connections list -------------------------------------------------

    @property
    def connections(self) -> Locator:
        return self.page.locator("article")

    @property
    def empty_state(self) -> Locator:
        return self.page.get_by_text("Подключения пока не загружены")

    def connection(self, name: str) -> Locator:
        return self.connections.filter(has=self.page.get_by_role("heading", name=name, exact=True))

    def connection_names(self) -> list[str]:
        return [heading.strip() for heading in self.connections.get_by_role("heading").all_inner_texts()]

    # -- actions ----------------------------------------------------------

    def fill_connection(
        self,
        *,
        name: str,
        endpoint: str,
        model: str,
        key: str,
    ) -> SettingsPage:
        self.name_input.fill(name)
        self.endpoint_input.fill(endpoint)
        self.model_input.fill(model)
        self.key_input.fill(key)
        return self

    def save(self) -> SettingsPage:
        self.submit_button.click()
        return self

    def add_connection(self, *, name: str, endpoint: str, model: str, key: str) -> SettingsPage:
        return self.fill_connection(name=name, endpoint=endpoint, model=model, key=key).save()

    def accept_next_dialog(self) -> None:
        """Removal asks for confirmation through a native dialog."""
        self.page.once("dialog", lambda dialog: dialog.accept())

    def remove(self, name: str) -> SettingsPage:
        self.accept_next_dialog()
        self.connection(name).get_by_role("button", name=f"Удалить {name}").click()
        return self
