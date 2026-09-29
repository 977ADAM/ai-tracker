"""The SEO run screen, driven by controlled browser responses.

The home page now runs the one-shot SEO analysis on the agent runtime instead of
the old brand check. Every `/api/seo/analyses` response is answered through
`page.route`, so the checks observe the six agents, their budget, the trace feed
with its cursor, the conclusions block, the counters, the actual estimates and the
cancel action without starting a run and without reaching Yandex or a model API.

An analysis without agent rows exercises the pre-agent screen: the six saved stages
stay the honest view of a run that the agent runtime never touched.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from uuid import uuid4

from playwright.sync_api import Page, Route, expect

from app import Application
from pages.seo import AGENT_IDS, SeoPage
from pages.settings import SettingsPage

ANALYSIS_ID = "qa-seo-run"
GENERATED = 3
TRACE_CURSOR = "cursor-trace-2"
PROVIDER_NAME = f"QA прогон {uuid4().hex[:6]}"
MODEL_ID = "qa-run-model"
MODEL_NAME = "Модель"
CONCLUSIONS_SUMMARY = "Ромашка видна в половине ответов моделей."
CONCLUSIONS_MODEL = "qa-service-model"
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
        "estimate": {"search_upper": 43, "model_upper": 40, "generated_limit": 40, "connections": 1},
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
    """A snapshot of the agent runtime: six agents, their budget, and conclusions."""
    data = snapshot(status)
    running = status == "running"
    data["estimate"] = {"search_upper": 43, "model_upper": 40, "generated_limit": 40, "connections": 1}
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
        "pages": {"used": 1, "limit": 20},
        "searches": {"used": 2, "limit": 43},
        "model_answers": {"used": 1, "limit": 40},
        "tool_calls": {"used": 5, "limit": 120},
        "handoffs": {"used": 1, "limit": 15},
        "seed_searches": 0, "model_rows": 1, "steps": 7,
        "agent_steps": {agent: 1 for agent in AGENT_IDS},
    }
    data["budget_exhausted"] = exhausted
    data["conclusions"] = None if running else {
        "summary": CONCLUSIONS_SUMMARY,
        "recommendations": "Усилить страницы услуг и показать цены.",
        "model": CONCLUSIONS_MODEL,
    }
    return data


def seeded_agent_run(page: Page, state: dict) -> None:
    """Answer the agent resource locally, including the paginated trace."""
    page.route("**/api/seo/analyses**", lambda route: _answer_agent(route, state))


def _answer_agent(route: Route, state: dict) -> None:
    request = route.request
    url = request.url
    path = url.split("?", 1)[0]
    query = url.split("?", 1)[1] if "?" in url else ""
    if path.endswith("/api/seo/analyses") and request.method == "POST":
        state["posts"] += 1
        route.fulfill(status=202, json={
            "id": ANALYSIS_ID, "status": "running",
            "estimate": {"search_upper": 43, "model_upper": 40, "generated_limit": 40, "connections": 1},
        })
    elif path.endswith("/api/seo/analyses") and request.method == "GET":
        route.fulfill(json={"items": [], "next_cursor": None})
    elif path.endswith(f"/api/seo/analyses/{ANALYSIS_ID}/trace"):
        state["traces"].append(query)
        if "cursor=" in query:
            route.fulfill(json={"items": [trace_step(
                2, "site", "tool", "fetch_site", {"max_pages": 2}, '{"pages":2}', "done", None,
            )], "next_cursor": None})
        else:
            route.fulfill(json={"items": [trace_step(
                1, "supervisor", "handoff", "handoff_to", {"agent": "site"},
                '{"status":"accepted"}', "done", None,
            )], "next_cursor": TRACE_CURSOR})
    elif path.endswith("/rows"):
        route.fulfill(json={"items": [], "next_cursor": None})
    elif path.endswith(f"/api/seo/analyses/{ANALYSIS_ID}"):
        state["polls"] += 1
        finished = state["polls"] >= 2
        route.fulfill(json=agent_snapshot("completed" if finished else "running", exhausted=finished))
    else:
        route.fulfill(status=404, json={"detail": "Не найдено"})


def seeded_run(page: Page, state: dict) -> None:
    """Answer the whole SEO resource locally: no real analysis ever starts."""

    def answer(route: Route) -> None:
        request = route.request
        path = request.url.split("?", 1)[0]
        method = request.method
        if path.endswith("/api/seo/analyses") and method == "POST":
            state["posts"] += 1
            route.fulfill(status=202, json={
                "id": ANALYSIS_ID, "status": "running",
                "estimate": {"search_upper": 43, "model_upper": 40, "generated_limit": 40, "connections": 1},
            })
        elif path.endswith("/api/seo/analyses") and method == "GET":
            route.fulfill(json={"items": [], "next_cursor": None})
        elif path.endswith(f"/api/seo/analyses/{ANALYSIS_ID}/cancel"):
            state["cancels"] += 1
            route.fulfill(json=snapshot("cancelled"))
        elif path.endswith(f"/api/seo/analyses/{ANALYSIS_ID}"):
            state["polls"] += 1
            route.fulfill(json=snapshot("running" if state["polls"] < 2 else "completed"))
        elif path.endswith("/rows"):
            route.fulfill(json={"items": [], "next_cursor": None})
        else:
            route.fulfill(status=404, json={"detail": "Не найдено"})

    page.route("**/api/seo/analyses**", answer)


def seeded_cancel(page: Page, state: dict) -> None:
    """Answer the same resource for a run that is cancelled by the user."""

    def answer(route: Route) -> None:
        request = route.request
        path = request.url.split("?", 1)[0]
        if path.endswith("/api/seo/analyses") and request.method == "POST":
            state["posts"] += 1
            route.fulfill(status=202, json={
                "id": ANALYSIS_ID, "status": "running",
                "estimate": {"search_upper": 43, "model_upper": 40, "generated_limit": 40, "connections": 1},
            })
        elif path.endswith("/api/seo/analyses") and request.method == "GET":
            route.fulfill(json={"items": [], "next_cursor": None})
        elif path.endswith(f"/api/seo/analyses/{ANALYSIS_ID}/cancel"):
            state["cancels"] += 1
            state["cancel_body"] = request.post_data
            route.fulfill(json=snapshot("cancelled"))
        elif path.endswith(f"/api/seo/analyses/{ANALYSIS_ID}"):
            route.fulfill(json=snapshot("running"))
        else:
            route.fulfill(json={"items": [], "next_cursor": None})

    page.route("**/api/seo/analyses**", answer)


def prepare(
    page: Page, settings_page: SettingsPage, application: Application, mock: Callable[[], None]
) -> None:
    settings_page.add_provider(
        PROVIDER_NAME, "https://api.example.com/v1/chat/completions", "qa-run-key",
        model_id=MODEL_ID, model_name=MODEL_NAME,
    )
    settings_page.close()
    # The route and the fake clock are installed before the page loads: the run
    # resource is answered locally, and the 30-second poll is advanced by
    # `fast_forward` instead of waiting for real seconds.
    mock()
    page.clock.install()
    page.goto(application.base_url, wait_until="networkidle")
    page.get_by_role("checkbox", name=re.compile(PROVIDER_NAME)).check()
    page.get_by_label("Адрес главной страницы").fill("https://example.ru/")
    page.get_by_label("Сфера бизнеса").fill("Цветы")
    for index, seed in enumerate(["купить цветы", "доставка букетов", "цветочный магазин"], start=1):
        page.get_by_label(["Первый", "Второй", "Третий"][index - 1] + " ключевой запрос").fill(seed)
    page.get_by_label("Услуги").fill("Доставка цветов")


def test_seo_run_shows_six_stages_and_the_report(page: Page, settings_page: SettingsPage, application: Application) -> None:
    state = {"posts": 0, "polls": 0, "cancels": 0}
    prepare(page, settings_page, application, lambda: seeded_run(page, state))
    page.get_by_role("button", name="Запустить анализ").click()

    expect(page.locator("#seo-run")).to_be_visible()
    assert state["posts"] == 1
    stages = page.locator("[data-stage]")
    expect(stages).to_have_count(6)
    for index, name in enumerate(STAGE_NAMES, start=1):
        expect(stages.nth(index - 1)).to_contain_text(name)
    expect(stages.nth(3)).to_contain_text("Выполняется")
    expect(page.locator("[data-analysis-status]")).to_have_text("Выполняется")
    expect(page.locator("[aria-label='Счётчики строк']")).to_contain_text("Запросы: 3")
    expect(page.locator("[aria-label='Счётчики строк']")).to_contain_text("ошибок 1")
    estimate = page.locator("[aria-label='Фактическая оценка вызовов']")
    expect(estimate).to_contain_text("3 запросов")
    expect(estimate).to_contain_text("6 поисковых")
    expect(estimate).to_contain_text("3 модельных")

    page.clock.fast_forward(30_000)
    expect(page.locator("[data-analysis-status]")).to_have_text("Завершён")
    expect(page.get_by_role("button", name="Отменить анализ")).to_have_count(0)
    expect(page.locator("[data-seo-report]")).to_be_visible()
    assert page.locator("[data-metric='site-overall']").inner_text().strip() == "50 %"
    assert page.locator("[data-metric='category-informational']").inner_text().strip() == "—"


def test_agent_run_shows_agents_budget_trace_and_conclusions(
    page: Page, settings_page: SettingsPage, application: Application
) -> None:
    state = {"posts": 0, "polls": 0, "traces": []}
    prepare(page, settings_page, application, lambda: seeded_agent_run(page, state))
    page.get_by_role("button", name="Запустить анализ").click()

    # The agent screen replaces the stage list: six agents with their statuses.
    expect(page.locator("[data-agent-panel]")).to_be_visible()
    expect(page.locator("[data-stage]")).to_have_count(0)
    expect(page.locator("[data-agent]")).to_have_count(6)
    expect(page.locator("[data-agent='supervisor']")).to_contain_text("Супервизор")
    expect(page.locator("[data-agent-status='supervisor']")).to_have_text("Выполняется")
    expect(page.locator("[data-agent-status='site']")).to_have_text("Ожидает")

    # The budget pairs what was spent with the caps of the run.
    assert page.locator("[data-budget-used='pages']").inner_text().strip() == "1 / 20"
    assert page.locator("[data-budget-used='searches']").inner_text().strip() == "2 / 43"
    assert page.locator("[data-budget-used='tool_calls']").inner_text().strip() == "5 / 120"
    assert page.locator("[data-budget-used='handoffs']").inner_text().strip() == "1 / 15"
    expect(page.locator("[data-budget-exhausted]")).to_have_count(0)

    # The trace feed shows the first page and loads the next one through the cursor.
    expect(page.locator("[data-trace-step='1']")).to_contain_text("handoff_to")
    expect(page.locator("[data-trace-step='1']")).to_contain_text('{"agent":"site"}')
    page.locator("[data-trace-feed]").get_by_role("button", name="Показать ещё").click()
    expect(page.locator("[data-trace-step='2']")).to_contain_text("fetch_site")
    expect(page.locator("[data-trace-feed]").get_by_role("button", name="Показать ещё")).to_have_count(0)
    assert state["traces"] == ["", f"cursor={TRACE_CURSOR}"]

    # The finished run reports its exhaustion and shows the model-written conclusions.
    page.clock.fast_forward(30_000)
    expect(page.locator("[data-analysis-status]")).to_have_text("Завершён")
    expect(page.locator("[data-budget-exhausted]")).to_contain_text("остановлен по лимиту")
    expect(page.locator("[data-agent-status='report']")).to_have_text("Готово")
    conclusions = page.locator("[data-report-conclusions]")
    expect(conclusions).to_be_visible()
    expect(conclusions).to_contain_text("Текст модели")
    expect(conclusions).to_contain_text(CONCLUSIONS_MODEL)
    expect(page.locator("[data-conclusions-summary]")).to_have_text(CONCLUSIONS_SUMMARY)
    # The numbers stay server-computed next to the labelled model text.
    assert page.locator("[data-metric='site-overall']").inner_text().strip() == "50 %"


def test_cancel_stops_the_run_without_a_body(page: Page, settings_page: SettingsPage, application: Application) -> None:
    state = {"posts": 0, "polls": 0, "cancels": 0, "cancel_body": "not called"}
    prepare(page, settings_page, application, lambda: seeded_cancel(page, state))
    page.get_by_role("button", name="Запустить анализ").click()
    expect(page.get_by_role("button", name="Отменить анализ")).to_be_visible()
    page.get_by_role("button", name="Отменить анализ").click()

    expect(page.locator("[data-analysis-status]")).to_have_text("Отменён")
    expect(page.get_by_text("Анализ отменён")).to_be_visible()
    expect(page.get_by_role("button", name="Отменить анализ")).to_have_count(0)
    assert state["cancels"] == 1
    assert state["cancel_body"] is None
