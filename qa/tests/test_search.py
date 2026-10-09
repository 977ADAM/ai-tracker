"""The SEO run card inside the chat, driven by controlled browser responses.

The run screen is no longer a page of its own: the chat feed holds it, and a run
appears only after the dialogue confirms a proposal. Every chat turn and every
`/api/seo/analyses` response is answered by the `api` fake through `page.route`,
so the checks observe the five agents, their budget, the trace feed with its
cursor, the counters, the actual estimates and the cancel action
without starting a run and without reaching Yandex or a model API.

An analysis without agent rows exercises the pre-agent screen: the six saved
stages stay the honest view of a run that the agent runtime never touched.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from pages.fake_api import ANALYSIS_ID, model_row
from pages.seo import AGENT_IDS, SeoChatPage

DESCRIPTION = (
    "Проанализируй https://example.ru, доставка цветов, запросы: "
    "букеты москва, доставка цветов, цветы с доставкой, услуги: букеты"
)
# The service model's answer to «да»: the fake server takes the launch decision.
CONFIRM_JSON = '{"reply": "Запускаю прогон.", "intent": "confirm", "params": {}}'
TRACE_CURSOR = "cursor-trace-2"
GENERATED = 3
MODEL_ID = "qa-run-connection"
STAGE_NAMES = [
    "Анализ сайта",
    "Поиск конкурентов",
    "Генерация запросов",
    "Проверки в ИИ и Поиске",
    "Анализ результатов",
    "Отчёт",
]


def metric(denominator: int, successes: int, average: float | None = None) -> dict:
    return {
        "denominator": denominator,
        "successes": successes,
        "share": round(successes / denominator, 4) if denominator else None,
        "average_position": average,
    }


def cover(denominator: int, successes: int) -> dict:
    return {
        "name": metric(denominator, successes),
        "host": metric(denominator, successes),
        "combined": metric(denominator, successes),
        "branded": {"name": metric(1, 1), "host": metric(1, 1), "combined": metric(1, 1)},
        "unbranded": {"name": metric(1, 0), "host": metric(1, 1), "combined": metric(1, 1)},
    }


def snapshot(status: str) -> dict:
    finished = status != "running"
    return {
        "id": ANALYSIS_ID,
        "status": status,
        "created_at": "2026-09-28T00:00:00Z",
        "updated_at": "2026-09-28T01:00:00Z",
        "finished_at": "2026-09-28T01:00:00Z" if finished else None,
        "input": {
            "url": "https://example.ru/", "host": "example.ru", "sphere": "Цветы",
            "seeds": ["купить цветы", "доставка букетов", "цветочный магазин"],
            "services": ["Доставка цветов"], "connection_ids": [MODEL_ID],
        },
        "estimate": {"search_upper": 5, "model_upper": 5, "generated_limit": 2, "connections": 1},
        "company_name": "Ромашка",
        "services": ["Доставка цветов"],
        "pages": [],
        "stages": [
            {
                "stage": stage,
                "status": "done" if stage < 4 or finished else ("running" if stage == 4 else "pending"),
                "error": None,
                "counters": {},
                "updated_at": "2026-09-28T01:00:00Z",
            }
            for stage in range(1, 7)
        ],
        "candidates": [],
        "queries": [
            {
                "index": index, "text": f"запрос {index + 1}", "category": "commercial",
                "service": "Доставка цветов",
                "flags": {
                    "mentions_company_name": False, "mentions_company_host": False,
                    "mentions_candidate_host": False, "branded": False,
                },
            }
            for index in range(GENERATED)
        ],
        "summary": "Ромашка упоминается в половине ответов." if finished else None,
        "counters": {"queries": GENERATED, "search_rows": 2, "model_rows": 1, "search_errors": 1, "model_errors": 0},
        "readiness": {
            "report_ready": finished, "summary_ready": finished, "queries_ready": True,
            "has_submitted_search_rows": True, "has_unsubmitted_search_rows": False,
            "has_unfinished_model_rows": False, "search_rows": 2, "model_rows": 1,
        },
        "aggregates": {
            "site": {"search": {"overall": metric(2, 1, 3), "branded": metric(1, 1, 3), "unbranded": metric(1, 0)},
                     "ai": {MODEL_ID: cover(1, 1)}},
            "competitors": [],
            "categories": {
                "commercial": {"search": metric(2, 1, 3), "ai": {MODEL_ID: metric(1, 1)}},
                "informational": {"search": metric(0, 0), "ai": {MODEL_ID: metric(0, 0)}},
                "comparative": {"search": metric(0, 0), "ai": {MODEL_ID: metric(0, 0)}},
            },
            "services": {"Доставка цветов": {"search": metric(2, 1, 3), "ai": {MODEL_ID: metric(1, 1)}}},
            "sources": [],
            "counts": {"queries": GENERATED, "search_rows": 2, "model_rows": 1, "search_errors": 1, "model_errors": 0},
        },
    }


def trace_step(
    index: int, agent: str, kind: str, name: str, arguments: dict,
    result: str | None, status: str, error: str | None,
) -> dict:
    return {
        "step_index": index, "agent": agent, "kind": kind, "name": name,
        "arguments": arguments, "result_summary": result, "status": status,
        "error": error, "created_at": "2026-09-28T01:00:00Z",
    }


def agent_snapshot(status: str, *, exhausted: bool = False) -> dict:
    """A snapshot of the agent runtime: five agents, their budget, and numbers."""
    data = snapshot(status)
    running = status == "running"
    # The connection answers with a completed web search: the citation share sits
    # on the connection block and the brand position is its own split.
    data["aggregates"]["site"]["ai"][MODEL_ID] = {
        **cover(1, 1),
        "citation": metric(2, 1, 4),
        "position": {
            "first": metric(10, 3),
            "early": metric(10, 2),
            "late": metric(10, 1),
            "absent": metric(10, 4),
            "ahead": metric(10, 1),
        },
    }
    data["aggregates"]["sources"] = [
        {"domain": "habr.com", "answers": 2, "citations": 3},
        {"domain": "vc.ru", "answers": 1, "citations": 1},
    ]
    data["estimate"] = {"search_upper": 5, "model_upper": 5, "generated_limit": 2, "connections": 1}
    data["agents"] = [
        {
            "agent": agent,
            "status": "running" if running and agent == "supervisor" else ("done" if not running else "pending"),
            "error": None,
            "updated_at": "2026-09-28T01:00:00Z",
        }
        for agent in AGENT_IDS
    ]
    data["budget"] = {
        "pages": {"used": 1, "limit": 5},
        "searches": {"used": 2, "limit": 5},
        "model_answers": {"used": 1, "limit": 5},
        "tool_calls": {"used": 5, "limit": 120},
        "handoffs": {"used": 1, "limit": 15},
        "seed_searches": 0, "model_rows": 1, "steps": 7,
        "agent_steps": {agent: 1 for agent in AGENT_IDS},
    }
    data["budget_exhausted"] = exhausted
    return data


def start_run(page: Page, api) -> SeoChatPage:
    """Drive the dialogue to a run: describe the task, then confirm the proposal."""
    chat = SeoChatPage(page).open()
    chat.send(DESCRIPTION)
    expect(chat.proposal()).to_be_visible()
    api.route_completion(answer=CONFIRM_JSON)
    chat.send("да")
    expect(chat.run_card()).to_be_visible()
    return chat


def test_the_run_card_shows_six_stages_and_reaches_the_report(page: Page, api) -> None:
    api.route_snapshots(snapshot("running"), snapshot("completed"))
    page.clock.install()
    chat = start_run(page, api)

    # The run appears in the chat feed, funded by exactly one chat and one turn.
    assert api.requests.count("POST /api/seo/chats") == 1
    stages = page.locator("[data-stage]")
    expect(stages).to_have_count(6)
    for index, name in enumerate(STAGE_NAMES, start=1):
        expect(stages.nth(index - 1)).to_contain_text(name)
    expect(stages.nth(3)).to_contain_text("Выполняется")
    expect(page.locator("[data-analysis-status]")).to_have_text("Выполняется")
    expect(chat.counters).to_contain_text("Запросы: 3")
    expect(chat.counters).to_contain_text("ошибок 1")
    expect(chat.actual_estimate).to_contain_text("3 запросов")
    expect(chat.actual_estimate).to_contain_text("6 поисковых")
    expect(chat.actual_estimate).to_contain_text("3 модельных")

    page.clock.fast_forward(30_000)
    expect(page.locator("[data-run-status]")).to_have_text("Завершён")
    expect(chat.cancel_button).to_have_count(0)
    expect(chat.report()).to_be_visible()
    assert chat.metric_text("site-overall") == "50 %"
    # The report is numbers-only and compact: no breakdown table, no counters block.
    expect(page.locator("[data-report-counters]")).to_have_count(0)
    expect(page.get_by_role("table", name="Разрезы по категориям")).to_have_count(0)
    expect(chat.report_status).to_have_text("Завершён")


def test_the_agent_run_shows_agents_budget_trace_and_numbers(page: Page, api) -> None:
    api.route_snapshots(agent_snapshot("running", exhausted=True), agent_snapshot("completed"))
    api.route_rows("model", {None: {"items": [model_row(MODEL_ID)], "next_cursor": None}})
    api.route_trace({
        None: {
            "items": [trace_step(
                1, "supervisor", "handoff", "handoff_to", {"agent": "site"},
                '{"status":"accepted"}', "done", None,
            )],
            "next_cursor": TRACE_CURSOR,
        },
        TRACE_CURSOR: {
            "items": [trace_step(
                2, "site", "tool", "fetch_site", {"max_pages": 2}, '{"pages":2}', "done", None,
            )],
            "next_cursor": None,
        },
    })
    page.clock.install()
    chat = start_run(page, api)

    # The agent screen replaces the stage list: five agents with their statuses.
    expect(chat.agents_panel).to_be_visible()
    expect(page.locator("[data-stage]")).to_have_count(0)
    expect(page.locator("[data-agent]")).to_have_count(5)
    expect(chat.agent("supervisor")).to_contain_text("Супервизор")
    expect(chat.agent_status("supervisor")).to_have_text("Выполняется")
    expect(chat.agent_status("site")).to_have_text("Ожидает")

    # The budget pairs what was spent with the caps of the run, and the live card
    # is where an exhausted run says so.
    assert chat.budget_text("pages") == "1 / 5"
    assert chat.budget_text("searches") == "2 / 5"
    assert chat.budget_text("tool_calls") == "5 / 120"
    assert chat.budget_text("handoffs") == "1 / 15"
    expect(chat.budget_exhausted).to_contain_text("остановлен по лимиту")

    # The trace feed starts folded: the header counts the steps, the toggle opens them.
    feed = chat.trace_feed
    expect(chat.trace_toggle).to_have_attribute("aria-expanded", "false")
    expect(chat.trace_step(1)).to_have_count(0)
    expect(page.locator("[data-trace-summary]")).to_contain_text("1 шаг")
    chat.open_trace()
    expect(chat.trace_step(1)).to_contain_text("handoff_to")
    expect(chat.trace_step(1)).to_contain_text('{"agent":"site"}')
    feed.get_by_role("button", name="Показать ещё").click()
    expect(chat.trace_step(2)).to_contain_text("fetch_site")
    expect(feed.get_by_role("button", name="Показать ещё")).to_have_count(0)
    assert api.trace_cursors == [None, TRACE_CURSOR]

    # The finished run shows server-computed numbers only: there is no
    # model-written block in the report any more.
    page.clock.fast_forward(30_000)
    expect(page.locator("[data-run-status]")).to_have_text("Завершён")
    expect(chat.report()).to_be_visible()
    expect(page.locator("[data-report-conclusions]")).to_have_count(0)
    assert chat.metric_text("site-overall") == "50 %"

    # The report carries the cited sources, the brand position and the poll
    # coverage of the saved answers; the citation share is per connection.
    expect(chat.source_domain("habr.com")).to_contain_text("2")
    expect(chat.brand_position("first")).to_have_text("30 %")
    expect(chat.model_coverage).to_contain_text("из")
    assert chat.metric_text("ai-qa-run-connection-all-citation") == "50 %"
    # The saved answer shows its web-search mode and how many sources it cites.
    row = chat.model_detail_rows.first
    expect(row.locator("[data-answer-mode]")).to_have_text("веб-поиск")
    expect(row.locator("[data-answer-sources-count]")).to_have_text("2")


def test_cancel_stops_the_run_without_a_body(page: Page, api) -> None:
    api.route_snapshots(snapshot("running"))
    api.route_cancel(snapshot("cancelled"))
    page.clock.install()
    chat = start_run(page, api)

    expect(chat.cancel_button).to_be_visible()
    chat.cancel()

    expect(page.locator("[data-run-status]")).to_have_text("Отменён")
    expect(page.get_by_text("Анализ отменён")).to_be_visible()
    expect(chat.cancel_button).to_have_count(0)
    assert api.requests.count(f"POST /api/seo/analyses/{ANALYSIS_ID}/cancel") == 1
    assert api.cancel_body is None
