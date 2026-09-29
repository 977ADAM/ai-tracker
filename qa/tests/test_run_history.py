"""The SEO history and the saved report, driven by controlled browser responses.

The old mixed-run history screen is gone: the home page keeps a separate SEO
history instead. Every `/api/seo/analyses` response is answered through
`page.route`, so the check observes the cursor pages, the saved report with its
detail rows, the delete confirmation and the empty state without starting a run,
reading the real database or reaching a paid API.
"""

from __future__ import annotations

from playwright.sync_api import Page, Route, expect

from app import Application
from pages.seo import SeoPage

FIRST_ID = "qa-seo-first"
SECOND_ID = "qa-seo-second"
THIRD_ID = "qa-seo-third"
CURSOR = "cursor-page-2"
ROWS_CURSOR = "cursor-rows-2"
CANDIDATE_HOST = "flower-shop.example"


def metric(denominator: int, successes: int, average: float | None = None) -> dict:
    return {
        "denominator": denominator,
        "successes": successes,
        "share": round(successes / denominator, 4) if denominator else None,
        "average_position": average,
    }


def history_item(analysis_id: str, *, status: str, sphere: str, created_at: str) -> dict:
    return {
        "id": analysis_id, "created_at": created_at,
        "finished_at": None if status == "running" else "2026-09-28T01:00:00Z",
        "status": status, "sphere": sphere, "host": "example.ru", "company_name": "Ромашка",
        "counters": {"queries": 3, "search_rows": 2, "model_rows": 2, "search_errors": 0, "model_errors": 0},
    }


def snapshot(status: str = "completed") -> dict:
    return {
        "id": FIRST_ID,
        "status": status,
        "created_at": "2026-09-28T00:00:00Z",
        "updated_at": "2026-09-28T01:00:00Z",
        "finished_at": "2026-09-28T01:00:00Z",
        "input": {
            "url": "https://example.ru/", "host": "example.ru", "sphere": "Цветы",
            "seeds": ["купить цветы", "доставка букетов", "цветочный магазин"],
            "services": ["Доставка цветов"], "connection_ids": ["model-1"],
        },
        "estimate": {"search_upper": 43, "model_upper": 40, "generated_limit": 40, "connections": 1},
        "company_name": "Ромашка",
        "services": ["Доставка цветов"],
        "pages": [],
        "stages": [
            {"stage": stage, "status": "done", "error": None, "counters": {}, "updated_at": "2026-09-28T01:00:00Z"}
            for stage in range(1, 7)
        ],
        "candidates": [
            {"host": CANDIDATE_HOST, "title": "Цветочный магазин — доставка", "occurrences": 2,
             "average_position": 2.5, "seed_indexes": [0, 1], "recurring": True},
        ],
        "queries": [
            {"index": index, "text": f"запрос {index + 1}", "category": "commercial",
             "service": "Доставка цветов",
             "flags": {"mentions_company_name": False, "mentions_company_host": False,
                       "mentions_candidate_host": False, "branded": False}}
            for index in range(3)
        ],
        "summary": "Ромашка упоминается в половине ответов.",
        "counters": {"queries": 3, "search_rows": 2, "model_rows": 2, "search_errors": 0, "model_errors": 0},
        "readiness": {
            "report_ready": True, "summary_ready": True, "queries_ready": True,
            "has_submitted_search_rows": False, "has_unsubmitted_search_rows": False,
            "has_unfinished_model_rows": False, "search_rows": 2, "model_rows": 2,
        },
        "aggregates": {
            "site": {
                "search": {"overall": metric(2, 1, 3), "branded": metric(1, 1, 3), "unbranded": metric(1, 0)},
                "ai": {"model-1": {
                    "name": metric(2, 1), "host": metric(2, 1), "combined": metric(2, 1),
                    "branded": {"name": metric(1, 1), "host": metric(1, 1), "combined": metric(1, 1)},
                    "unbranded": {"name": metric(1, 0), "host": metric(1, 1), "combined": metric(1, 1)},
                }},
            },
            "competitors": [
                {"host": CANDIDATE_HOST, "title": "Цветочный магазин — доставка", "occurrences": 2,
                 "average_position": 2.5, "seed_indexes": [0, 1],
                 "search": {"overall": metric(2, 1, 2), "branded": metric(0, 0), "unbranded": metric(2, 1, 2)},
                 "ai": {"model-1": {"host": metric(2, 1)}}},
            ],
            "categories": {
                "commercial": {"search": metric(2, 1, 3), "ai": {"model-1": metric(2, 1)}},
                "informational": {"search": metric(0, 0), "ai": {"model-1": metric(0, 0)}},
                "comparative": {"search": metric(0, 0), "ai": {"model-1": metric(0, 0)}},
            },
            "services": {"Доставка цветов": {"search": metric(2, 1, 3), "ai": {"model-1": metric(2, 1)}}},
            "counts": {"queries": 3, "search_rows": 2, "model_rows": 2, "search_errors": 0, "model_errors": 0},
        },
    }


def model_row(index: int, answer: str) -> dict:
    return {
        "query_index": index, "connection_id": "model-1", "provider_name": "Модель",
        "status": "found", "answer": answer, "name_mentioned": True, "host_mentioned": False,
        "error": None, "query": f"запрос {index + 1}", "category": "commercial",
        "service": "Доставка цветов",
    }


def search_row(index: int) -> dict:
    return {
        "query_index": index, "query": f"запрос {index + 1}", "category": "commercial",
        "service": "Доставка цветов", "status": "found", "site_position": 3,
        "site_url": "https://example.ru/catalog", "error": None,
    }


def seeded_browser(page: Page) -> dict:
    """Answer history, report, detail pages and deletion locally."""
    state = {"deleted": False, "model_cursors": []}

    def answer(route: Route) -> None:
        request = route.request
        url = request.url
        path = url.split("?", 1)[0]
        query = url.split("?", 1)[1] if "?" in url else ""
        if path.endswith("/api/seo/analyses") and request.method == "GET":
            if "cursor=" in query:
                route.fulfill(json={"items": [history_item(THIRD_ID, status="cancelled", sphere="Третий прогон",
                                                         created_at="2026-09-26T10:00:00Z")], "next_cursor": None})
            elif state["deleted"]:
                route.fulfill(json={"items": [], "next_cursor": None})
            else:
                route.fulfill(json={"items": [
                    history_item(FIRST_ID, status="completed", sphere="Первый прогон",
                                 created_at="2026-09-28T10:00:00Z"),
                    history_item(SECOND_ID, status="interrupted", sphere="Второй прогон",
                                 created_at="2026-09-27T10:00:00Z"),
                ], "next_cursor": CURSOR})
        elif path.endswith(f"/api/seo/analyses/{FIRST_ID}/rows"):
            if "kind=model" in query:
                if "cursor=" in query:
                    state["model_cursors"].append(query)
                    route.fulfill(json={"items": [model_row(1, "Второй сохранённый ответ")], "next_cursor": None})
                else:
                    route.fulfill(json={"items": [model_row(0, "Первый сохранённый ответ")], "next_cursor": ROWS_CURSOR})
            else:
                route.fulfill(json={"items": [search_row(0)], "next_cursor": None})
        elif path.endswith(f"/api/seo/analyses/{FIRST_ID}") and request.method == "DELETE":
            state["deleted"] = True
            route.fulfill(status=204, body="")
        elif path.endswith(f"/api/seo/analyses/{FIRST_ID}"):
            route.fulfill(json=snapshot())
        else:
            route.fulfill(status=404, json={"detail": "Не найдено"})

    page.route("**/api/seo/analyses**", answer)
    return state


def test_seo_history_pages_opens_the_report_and_deletes(page: Page, application: Application) -> None:
    state = seeded_browser(page)
    seo = SeoPage(page, application.base_url).open()

    rows = seo.history_rows
    expect(rows).to_have_count(2)
    expect(rows.nth(0)).to_contain_text("Первый прогон")
    expect(rows.nth(0)).to_contain_text("Завершён")
    expect(rows.nth(1)).to_contain_text("Прерван")
    # An active analysis cannot be deleted; the first page holds only terminal states.
    expect(seo.history_row(FIRST_ID).get_by_role("button", name="Удалить")).to_be_enabled()

    seo.show_more_history()
    expect(rows).to_have_count(3)
    expect(rows.nth(2)).to_contain_text("Третий прогон")
    expect(rows.nth(2)).to_contain_text("Отменён")

    seo.open_report(FIRST_ID)
    assert seo.metric_text("site-overall") == "50 %"
    assert seo.metric_text("category-comparative") == "—"
    expect(seo.candidate(CANDIDATE_HOST)).to_contain_text("Цветочный магазин — доставка")
    expect(seo.model_detail_rows).to_have_count(1)
    expect(seo.model_detail_rows.first).to_contain_text("Первый сохранённый ответ")

    seo.show_more("Ответы моделей")
    expect(seo.model_detail_rows).to_have_count(2)
    expect(seo.model_detail_rows.nth(1)).to_contain_text("Второй сохранённый ответ")
    assert state["model_cursors"], "Вторая страница ответов должна запрашиваться по курсору"

    seo.delete_analysis(FIRST_ID)
    expect(seo.history_row(FIRST_ID)).to_have_count(0)
    expect(rows).to_have_count(2)
