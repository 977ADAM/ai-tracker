"""The SEO run screen, driven by controlled browser responses.

The home page now runs the one-shot SEO analysis instead of the old brand check.
Every `/api/seo/analyses` response is answered through `page.route`, so the check
observes the six stages, the counters, the actual estimates and the cancel action
without starting a run and without reaching Yandex or a model API.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from uuid import uuid4

from playwright.sync_api import Page, Route, expect

from app import Application
from pages.settings import SettingsPage

ANALYSIS_ID = "qa-seo-run"
GENERATED = 3
PROVIDER_NAME = f"QA прогон {uuid4().hex[:6]}"
MODEL_ID = "qa-run-model"
MODEL_NAME = "Модель"
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
        "estimate": {"search_upper": 23, "model_upper": 20, "generated_limit": 20, "connections": 1},
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
                "estimate": {"search_upper": 23, "model_upper": 20, "generated_limit": 20, "connections": 1},
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
                "estimate": {"search_upper": 23, "model_upper": 20, "generated_limit": 20, "connections": 1},
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
