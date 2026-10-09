"""The chat screen: the dialogue, the proposal card, the run card, and the report.

The home page is a chat now. A user describes the task in words, the assistant
answers with a question or a parameter proposal, the run starts only after the
user confirms the proposal in the dialogue, and the finished run stays in the
feed as a card whose report is folded until it is opened. The settings dialog
keeps its third tab for the service LLM, including whether that model can call
tools.

Selectors stay on roles, labels, and the data attributes the components own, so a
styling change does not break the checks.
"""

from __future__ import annotations

import re

from playwright.sync_api import Locator, Page, expect

from app import configured_application

SETTINGS_DIALOG = "Настройки API"
SEO_TAB = "SEO-анализ"
SEO_PANEL = "SEO-анализ"
SHOW_MORE = "Показать ещё"

# The three card kinds of the feed, used to wait for a turn to be absorbed.
CARDS = "[data-chat-message], [data-chat-proposal], [data-chat-run]"
CARDS_IN_FEED = (
    "[data-chat-feed] :is([data-chat-message], [data-chat-proposal], [data-chat-run])"
)

# The five agents in their fixed supervisor-to-specialist order, with the
# labels the run card renders.
AGENT_IDS = ("supervisor", "site", "competitors", "queries", "checks")
AGENT_LABELS = {
    "supervisor": "Супервизор",
    "site": "Агент сайта",
    "competitors": "Агент конкурентов",
    "queries": "Агент запросов",
    "checks": "Агент проверок",
}

# The JS condition of `send`: the turn landed as a new card, or it failed into an
# alert. Waiting on either keeps a failing turn from hanging the check.
SETTLED = """([selector, cards, alerts]) => {
    const feed = document.querySelector('[data-chat-feed]');
    const now = feed ? feed.querySelectorAll(selector).length : 0;
    return now > cards || document.querySelectorAll('[role="alert"]').length > alerts;
}"""


class SeoChatPage:
    """Driving one SEO dialogue from the first message to the saved report."""

    def __init__(self, page: Page, base_url: str | None = None) -> None:
        self.page = page
        self.base_url = base_url or configured_application().base_url

    # -- shell -------------------------------------------------------------

    def open(self) -> SeoChatPage:
        """Open the screen and start a fresh dialogue.

        The chat list comes from the server-side load of the live API, so the
        newest stored chat may open by itself. Starting a new dialogue keeps a
        check independent of whatever the instance already holds.
        """
        self.page.goto(self.base_url, wait_until="networkidle")
        expect(self.composer).to_be_visible()
        return self.new_chat()

    def new_chat(self) -> SeoChatPage:
        """Reset the dialogue without creating a chat: the first message does that."""
        self.page.get_by_role("button", name="Новый чат").click()
        expect(self.page.locator("[data-chat-empty]")).to_be_visible()
        return self

    # -- the dialogue ------------------------------------------------------

    @property
    def composer(self) -> Locator:
        return self.page.locator("#chat-composer")

    def send(self, text: str) -> SeoChatPage:
        """Write one message and wait until the turn has painted something.

        A successful turn adds a card; a refused one adds an alert. Either is the
        end of the turn, so a check never reads the feed mid-flight.
        """
        cards = self.page.locator(CARDS_IN_FEED).count()
        alerts = self.page.locator('[role="alert"]').count()
        self.composer.fill(text)
        self.composer.press("Enter")
        self.page.wait_for_function(SETTLED, arg=[CARDS, cards, alerts])
        return self

    def message(self, text: str) -> Locator:
        """The rendered text of one message, found by a fragment of its words."""
        return self.page.locator("[data-chat-message-text]").filter(has_text=text)

    def error_text(self) -> str:
        """The whole visible error text of the dialogue, joined into one string."""
        return "\n".join(self.page.locator('main [role="alert"]').all_inner_texts())

    def proposal(self) -> Locator:
        """The newest parameter proposal of the dialogue."""
        return self.page.locator("[data-chat-proposal]").last

    def run_card(self) -> Locator:
        """The newest run card of the dialogue."""
        return self.page.locator("[data-chat-run]").last

    def run_cards(self) -> Locator:
        return self.page.locator("[data-chat-run]")

    # -- the sidebar -------------------------------------------------------

    @property
    def chats(self) -> Locator:
        return self.page.get_by_role("list", name="Чаты").get_by_role("listitem")

    def chat_row(self, title_fragment: str) -> Locator:
        """The sidebar row of one chat, found by a fragment of its title."""
        return self.page.get_by_role("button", name=re.compile("Открыть чат")).filter(
            has_text=title_fragment
        )

    def open_chat(self, title_fragment: str) -> SeoChatPage:
        """Open one stored chat from the sidebar by a fragment of its title."""
        self.chat_row(title_fragment).click()
        expect(self.page.locator("[data-chat-feed]")).to_be_visible()
        return self

    def delete_chat(self, chat_id: str) -> SeoChatPage:
        """Deletion asks for confirmation through a native dialog."""
        self.page.once("dialog", lambda dialog: dialog.accept())
        self.page.get_by_role("button", name=f"Удалить чат {chat_id}").click()
        return self

    # -- the run card ------------------------------------------------------

    @property
    def run_screen(self) -> Locator:
        return self.page.locator("[data-chat-run]")

    @property
    def analysis_status(self) -> Locator:
        """The status pill: live progress and the terminal card both carry one."""
        return self.page.locator("[data-analysis-status], [data-run-status]").last

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

    def open_trace(self) -> SeoChatPage:
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

    def cancel(self) -> SeoChatPage:
        self.cancel_button.click()
        return self

    # -- the report --------------------------------------------------------

    @property
    def report_toggle(self) -> Locator:
        return self.page.locator("[data-report-toggle]").last

    def report(self) -> Locator:
        """Unfold the report of the newest run card and return it."""
        toggle = self.report_toggle
        expect(toggle).to_be_visible()
        if toggle.get_attribute("aria-expanded") != "true":
            toggle.click()
        expect(self.page.locator("[data-seo-report]").last).to_be_visible()
        return self.page.locator("[data-seo-report]").last

    @property
    def report_status(self) -> Locator:
        return self.page.locator("[data-report-status]").last

    def metric(self, key: str) -> Locator:
        """One report cell, for example `site-overall` or `category-comparative`."""
        return self.page.locator(f"[data-metric='{key}']")

    def metric_text(self, key: str) -> str:
        return (self.metric(key).inner_text() or "").strip()

    @property
    def model_coverage(self) -> Locator:
        """The «N из M пар» poll-coverage line above the per-connection AI tables."""
        return self.page.locator("[data-model-coverage]")

    def brand_position(self, key: str) -> Locator:
        """One brand-position share of a connection, for example `first` or `ahead`."""
        return self.page.locator(f"[data-brand-position='{key}']")

    def source_domain(self, domain: str) -> Locator:
        """The row of one cited domain.

        `data-source-domain` sits on the row's `<th>`, so the locator matches the
        whole row: an assertion then sees the answers and citations of that domain.
        """
        return self.page.locator(f'[data-source-row]:has([data-source-domain="{domain}"])')

    def candidate(self, host: str) -> Locator:
        return self.page.locator(f"[data-candidate='{host}']")

    @property
    def search_detail_rows(self) -> Locator:
        return self.page.locator("[data-search-detail]")

    @property
    def model_detail_rows(self) -> Locator:
        return self.page.locator("[data-model-detail]")

    def show_more(self, table: str) -> SeoChatPage:
        """Load the next page of one detail table: «Проверки в Яндексе» or «Ответы моделей»."""
        wrapper = self.report().get_by_role("table", name=table).locator("..")
        wrapper.get_by_role("button", name=SHOW_MORE).click()
        return self

    # -- settings ----------------------------------------------------------

    def open_seo_settings(self) -> SeoChatPage:
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

    def save_seo_settings(self, *, endpoint: str, model: str, key: str = "") -> SeoChatPage:
        self.seo_endpoint_input.fill(endpoint)
        self.seo_model_input.fill(model)
        if key:
            self.seo_key_input.fill(key)
        self.seo_save_button.click()
        return self

    def test_seo_connection(self) -> SeoChatPage:
        self.seo_test_button.click()
        return self
