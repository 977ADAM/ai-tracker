"""The SEO analysis page: form, run screen, trace, report, history, and the LLM settings tab.

The home page is a one-shot SEO scenario: five form fields start an analysis, a
supervisor agent hands work to five specialists whose statuses, budget usage, and
trace steps appear on the run screen, the finished run shows a saved report with
its model-written conclusions, and the SEO history opens or deletes a saved
analysis. The settings dialog keeps the provider sections and adds a third tab for
the service LLM, including whether that model can call tools.

Selectors stay on roles, labels, and the data attributes the components own, so a
styling change does not break the checks.
"""

from __future__ import annotations

import re

from playwright.sync_api import Locator, Page, expect

SETTINGS_DIALOG = "Настройки API"
SEO_TAB = "SEO-анализ"
SEO_PANEL = "SEO-анализ"
SUBMIT = "Запустить анализ"
OPEN_REPORT = "Открыть отчёт"
DELETE_ANALYSIS = "Удалить"
SHOW_MORE = "Показать ещё"

# The six agents in their fixed supervisor-to-report order, with the labels the
# run screen renders.
AGENT_IDS = ("supervisor", "site", "competitors", "queries", "checks", "report")
AGENT_LABELS = {
    "supervisor": "Супервизор",
    "site": "Агент сайта",
    "competitors": "Агент конкурентов",
    "queries": "Агент запросов",
    "checks": "Агент проверок",
    "report": "Агент отчёта",
}


class SeoPage:
    """Driving one SEO analysis from the form to the saved report."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url

    # -- shell -------------------------------------------------------------

    def open(self) -> SeoPage:
        self.page.goto(self.base_url, wait_until="networkidle")
        expect(self.form).to_be_visible()
        return self

    @property
    def form(self) -> Locator:
        return self.page.locator("form").filter(has=self.page.get_by_role("heading", name="Параметры анализа"))

    # -- form --------------------------------------------------------------

    @property
    def url_input(self) -> Locator:
        return self.page.get_by_label("Адрес главной страницы")

    @property
    def sphere_input(self) -> Locator:
        return self.page.get_by_label("Сфера бизнеса")

    def seed_input(self, index: int) -> Locator:
        return self.page.get_by_label(["Первый", "Второй", "Третий"][index - 1] + " ключевой запрос")

    @property
    def services_input(self) -> Locator:
        return self.page.get_by_label("Услуги")

    @property
    def submit_button(self) -> Locator:
        return self.page.get_by_role("button", name=SUBMIT)

    @property
    def form_error(self) -> Locator:
        """The validation or server message inside the form."""
        return self.form.get_by_role("alert")

    @property
    def estimate_search(self) -> Locator:
        return self.page.locator("[data-estimate-search]")

    @property
    def estimate_model(self) -> Locator:
        return self.page.locator("[data-estimate-model]")

    def connection_checkbox(self, name: str) -> Locator:
        return self.page.get_by_role("checkbox", name=re.compile(re.escape(name)))

    def uncheck_all_connections(self) -> SeoPage:
        for checkbox in self.page.get_by_role("checkbox").all():
            if checkbox.is_checked() and checkbox.is_enabled():
                checkbox.uncheck()
        return self

    def fill_form(
        self,
        *,
        url: str = "https://example.ru/",
        sphere: str = "Доставка цветов",
        seeds: list[str] | None = None,
        services: str = "Доставка цветов",
    ) -> SeoPage:
        self.url_input.fill(url)
        self.sphere_input.fill(sphere)
        values = seeds if seeds is not None else ["купить цветы", "доставка букетов", "цветочный магазин"]
        for index in range(1, 4):
            self.seed_input(index).fill(values[index - 1] if index <= len(values) else "")
        self.services_input.fill(services)
        return self

    def submit(self) -> SeoPage:
        self.submit_button.click()
        return self

    # -- run screen --------------------------------------------------------

    @property
    def run_screen(self) -> Locator:
        return self.page.locator("#seo-run")

    @property
    def analysis_status(self) -> Locator:
        return self.page.locator("[data-analysis-status]")

    def stage(self, number: int) -> Locator:
        return self.page.locator(f"[data-stage='{number}']")

    @property
    def agents_panel(self) -> Locator:
        """The six-agent panel shown for a run of the agent runtime."""
        return self.page.locator("[data-agent-panel]")

    def agent(self, agent: str) -> Locator:
        return self.page.locator(f"[data-agent='{agent}']")

    def agent_status(self, agent: str) -> Locator:
        """The Russian status label of one agent, for example «Выполняется»."""
        return self.page.locator(f"[data-agent-status='{agent}']")

    def budget_item(self, key: str) -> Locator:
        """One budget row, for example `tool_calls` or `seed_searches`."""
        return self.page.locator(f"[data-budget-used='{key}']")

    def budget_text(self, key: str) -> str:
        """The rendered «used / limit» of one metered resource."""
        return (self.budget_item(key).inner_text() or "").strip()

    @property
    def budget_exhausted(self) -> Locator:
        return self.page.locator("[data-budget-exhausted]")

    @property
    def trace_feed(self) -> Locator:
        return self.page.locator("[data-trace-feed]")

    def trace_step(self, index: int) -> Locator:
        return self.page.locator(f"[data-trace-step='{index}']")

    @property
    def trace_toggle(self) -> Locator:
        """The fold control of the trace feed; it exists only when steps are saved."""
        return self.trace_feed.get_by_role("button", name=re.compile("Показать трассу|Скрыть трассу"))

    def open_trace(self) -> SeoPage:
        """Unfold the trace feed: a folded feed renders no step at all."""
        toggle = self.trace_toggle
        if toggle.count() and toggle.get_attribute("aria-expanded") != "true":
            toggle.click()
            expect(self.page.locator("[data-trace-body]")).to_be_visible()
        return self

    @property
    def trace_show_more(self) -> Locator:
        """The trace cursor button, scoped to the feed so the report tables do not match."""
        return self.trace_feed.get_by_role("button", name=SHOW_MORE)

    @property
    def trace_error(self) -> Locator:
        return self.page.locator("[data-trace-error]")

    @property
    def counters(self) -> Locator:
        return self.page.locator("[aria-label='Счётчики строк']")

    @property
    def actual_estimate(self) -> Locator:
        return self.page.locator("[aria-label='Фактическая оценка вызовов']")

    @property
    def cancel_button(self) -> Locator:
        return self.page.get_by_role("button", name="Отменить анализ")

    def cancel(self) -> SeoPage:
        self.cancel_button.click()
        return self

    # -- report ------------------------------------------------------------

    @property
    def report(self) -> Locator:
        return self.page.locator("[data-seo-report]")

    @property
    def report_status(self) -> Locator:
        return self.page.locator("[data-report-status]")

    def metric(self, key: str) -> Locator:
        """One report cell, for example `site-overall` or `category-comparative`."""
        return self.page.locator(f"[data-metric='{key}']")

    def metric_text(self, key: str) -> str:
        return (self.metric(key).inner_text() or "").strip()

    def candidate(self, host: str) -> Locator:
        return self.page.locator(f"[data-candidate='{host}']")

    @property
    def conclusions(self) -> Locator:
        """The report agent's text, shown apart from the server-computed numbers."""
        return self.page.locator("[data-report-conclusions]")

    @property
    def conclusions_summary(self) -> Locator:
        return self.page.locator("[data-conclusions-summary]")

    @property
    def conclusions_recommendations(self) -> Locator:
        return self.page.locator("[data-conclusions-recommendations]")

    @property
    def search_detail_rows(self) -> Locator:
        return self.page.locator("[data-search-detail]")

    @property
    def model_detail_rows(self) -> Locator:
        return self.page.locator("[data-model-detail]")

    def show_more(self, table: str) -> SeoPage:
        """Load the next page of one detail table: «Проверки в Яндексе» or «Ответы моделей»."""
        wrapper = self.report.get_by_role("table", name=table).locator("..")
        wrapper.get_by_role("button", name=SHOW_MORE).click()
        return self

    # -- history -----------------------------------------------------------

    @property
    def history(self) -> Locator:
        return self.page.locator("section").filter(has=self.page.get_by_role("heading", name="SEO-история"))

    @property
    def history_rows(self) -> Locator:
        return self.history.locator("[data-seo-history]")

    def history_row(self, analysis_id: str) -> Locator:
        return self.history.locator(f"[data-seo-history][data-analysis='{analysis_id}']")

    def open_report(self, analysis_id: str) -> SeoPage:
        self.history_row(analysis_id).get_by_role("button", name=OPEN_REPORT).click()
        expect(self.report).to_be_visible()
        return self

    def delete_analysis(self, analysis_id: str) -> SeoPage:
        """Deletion asks for confirmation through a native dialog."""
        self.page.once("dialog", lambda dialog: dialog.accept())
        self.history_row(analysis_id).get_by_role("button", name=DELETE_ANALYSIS).click()
        return self

    def show_more_history(self) -> SeoPage:
        self.history.get_by_role("button", name=SHOW_MORE).click()
        return self

    # -- settings ----------------------------------------------------------

    def open_seo_settings(self) -> SeoPage:
        self.page.get_by_role("button", name="Настройки API").click()
        dialog = self.page.get_by_role("dialog", name=SETTINGS_DIALOG)
        expect(dialog).to_be_visible()
        dialog.get_by_role("tab", name=SEO_TAB).click()
        expect(self.seo_panel).to_be_visible()
        return self

    @property
    def seo_panel(self) -> Locator:
        return self.page.get_by_role("tabpanel", name=SEO_PANEL)

    @property
    def seo_endpoint_input(self) -> Locator:
        return self.seo_panel.get_by_label("Адрес (OpenAI Chat Completions)")

    @property
    def seo_model_input(self) -> Locator:
        return self.seo_panel.get_by_label("Модель")

    @property
    def seo_key_input(self) -> Locator:
        return self.seo_panel.get_by_label("Новый API-ключ")

    @property
    def seo_save_button(self) -> Locator:
        return self.seo_panel.get_by_role("button", name="Сохранить настройки")

    @property
    def seo_test_button(self) -> Locator:
        return self.seo_panel.get_by_role("button", name="Проверить подключение")

    @property
    def seo_status(self) -> Locator:
        """The safe success notice of the SEO settings panel."""
        return self.seo_panel.get_by_role("status")

    @property
    def seo_settings_alert(self) -> Locator:
        return self.seo_panel.get_by_role("alert")

    def save_seo_settings(self, *, endpoint: str, model: str, key: str = "") -> SeoPage:
        self.seo_endpoint_input.fill(endpoint)
        self.seo_model_input.fill(model)
        if key:
            self.seo_key_input.fill(key)
        self.seo_save_button.click()
        return self

    def test_seo_connection(self) -> SeoPage:
        self.seo_test_button.click()
        return self
