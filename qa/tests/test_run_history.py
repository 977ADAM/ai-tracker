"""The saved report inside a chat run card, driven by controlled responses.

The separate SEO history is gone: the chats themselves are the history, and a
finished run keeps its report in the feed, folded until it is opened. Every chat
turn and every `/api/seo/analyses` response is answered by the `api` fake through
`page.route`, so the check observes the report, its detail rows with their
cursor, the full model answer and the deletion of the chat without a run, without
reading the real database and without reaching a paid API.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from pages.fake_api import ANALYSIS_ID, CHAT_ID, MODEL_ID
from pages.seo import SeoChatPage

DESCRIPTION = (
    "Проанализируй https://example.ru, доставка цветов, запросы: "
    "букеты москва, доставка цветов, цветы с доставкой, услуги: букеты"
)
CONFIRM_JSON = '{"reply": "Запускаю прогон.", "intent": "confirm", "params": {}}'
ROWS_CURSOR = "cursor-rows-2"
CANDIDATE_HOST = "flower-shop.example"
# The answer is Markdown, exactly as a model writes it: the table shows its
# preview as prose and the full text is rendered as Markdown in the dialog.
MODEL_ANSWER = (
    "Ромашка и flower-shop.example предлагают доставку цветов.\n\n"
    "### Что уточнить\n- **материалы** и сроки\n- бригада и смета\n\n"
    + "Подробности заказа: сроки, бригада, смета и материалы. " * 12
)


def metric(denominator: int, successes: int, average: float | None = None) -> dict:
    return {
        "denominator": denominator,
        "successes": successes,
        "share": round(successes / denominator, 4) if denominator else None,
        "average_position": average,
    }


def snapshot() -> dict:
    counts = {"queries": 3, "search_rows": 2, "model_rows": 2, "search_errors": 0, "model_errors": 0}
    return {
        "id": ANALYSIS_ID,
        "status": "completed",
        "created_at": "2026-09-28T00:00:00Z",
        "updated_at": "2026-09-28T01:00:00Z",
        "finished_at": "2026-09-28T01:00:00Z",
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
        "counters": counts,
        "readiness": {
            "report_ready": True, "summary_ready": True, "queries_ready": True,
            "has_submitted_search_rows": False, "has_unsubmitted_search_rows": False,
            "has_unfinished_model_rows": False, "search_rows": 2, "model_rows": 2,
        },
        "aggregates": {
            "site": {
                "search": {"overall": metric(2, 1, 3), "branded": metric(1, 1, 3), "unbranded": metric(1, 0)},
                "ai": {MODEL_ID: {
                    "name": metric(2, 1), "host": metric(2, 1), "combined": metric(2, 1),
                    "branded": {"name": metric(1, 1), "host": metric(1, 1), "combined": metric(1, 1)},
                    "unbranded": {"name": metric(1, 0), "host": metric(1, 1), "combined": metric(1, 1)},
                }},
            },
            "competitors": [
                {"host": CANDIDATE_HOST, "title": "Цветочный магазин — доставка", "occurrences": 2,
                 "average_position": 2.5, "seed_indexes": [0, 1],
                 "search": {"overall": metric(2, 1, 2), "branded": metric(0, 0), "unbranded": metric(2, 1, 2)},
                 "ai": {MODEL_ID: {"host": metric(2, 1)}}},
            ],
            "categories": {
                "commercial": {"search": metric(2, 1, 3), "ai": {MODEL_ID: metric(2, 1)}},
                "informational": {"search": metric(0, 0), "ai": {MODEL_ID: metric(0, 0)}},
                "comparative": {"search": metric(0, 0), "ai": {MODEL_ID: metric(0, 0)}},
            },
            "services": {"Доставка цветов": {"search": metric(2, 1, 3), "ai": {MODEL_ID: metric(2, 1)}}},
            "counts": counts,
        },
    }


def model_row(index: int, answer: str) -> dict:
    return {
        "query_index": index, "connection_id": MODEL_ID, "provider_name": "Модель",
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


def start_run(page: Page, api) -> SeoChatPage:
    """Drive the dialogue to a finished run whose report the check can open."""
    chat = SeoChatPage(page).open()
    chat.send(DESCRIPTION)
    expect(chat.proposal()).to_be_visible()
    api.route_completion(answer=CONFIRM_JSON)
    chat.send("да")
    expect(chat.run_card()).to_be_visible()
    return chat


def test_the_chat_report_pages_rows_and_the_chat_deletes(page: Page, api) -> None:
    api.route_snapshots(snapshot())
    api.route_rows("model", {
        None: {"items": [model_row(0, MODEL_ANSWER)], "next_cursor": ROWS_CURSOR},
        ROWS_CURSOR: {"items": [model_row(1, "Второй сохранённый ответ")], "next_cursor": None},
    })
    api.route_rows("search", {None: {"items": [search_row(0)], "next_cursor": None}})

    chat = start_run(page, api)
    # The chat itself is the history now: it appears in the sidebar and is "Готов".
    row = chat.chat_row("Проанализируй")
    expect(row).to_be_visible()
    expect(row).to_contain_text("Проанализируй")
    expect(row.locator("[data-chat-status]")).to_have_text("Готов")

    expect(chat.report()).to_be_visible()
    assert chat.metric_text("site-overall") == "50 %"
    # The candidate has no branded hit, so that share stays empty and the report shows «—».
    assert chat.metric_text(f"candidate-{CANDIDATE_HOST}-branded") == "—"
    candidate = chat.candidate(CANDIDATE_HOST)
    expect(candidate).to_contain_text("Цветочный магазин — доставка")
    expect(candidate.locator("[data-candidate-occurrences]")).to_have_text("2")

    # The saved detail shows the answer and pages the second row by cursor.
    expect(chat.model_detail_rows).to_have_count(1)
    expect(chat.model_detail_rows.first).to_contain_text("flower-shop.example")
    preview = chat.model_detail_rows.first.locator("[data-model-answer-preview]")
    # The preview is prose: the Markdown markers never reach the table cell.
    expect(preview).not_to_contain_text("**")
    expect(preview).not_to_contain_text("###")
    chat.show_more("Ответы моделей")
    expect(chat.model_detail_rows).to_have_count(2)
    expect(chat.model_detail_rows.nth(1)).to_contain_text("Второй сохранённый ответ")
    assert ("model", ROWS_CURSOR) in api.row_cursors

    # A long answer opens in full, rendered as Markdown rather than raw text.
    chat.model_detail_rows.first.get_by_role("button", name="Читать полностью").click()
    dialog = page.get_by_role("dialog", name="Ответ модели")
    expect(dialog).to_be_visible()
    expect(dialog.locator("[data-answer-full] h3")).to_contain_text("Что уточнить")
    expect(dialog.locator("[data-answer-full] strong")).to_contain_text("материалы")
    expect(dialog.locator("[data-answer-full] li")).to_have_count(2)
    expect(dialog.locator("[data-answer-full]")).not_to_contain_text("###")
    expect(dialog.locator("[data-answer-caption]")).to_contain_text("запрос 1")
    dialog.get_by_role("button", name="Закрыть").click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    # Deleting the chat asks for confirmation and resets the screen.
    chat.delete_chat(CHAT_ID)
    expect(chat.chat_row("Проанализируй")).to_have_count(0)
    expect(page.locator("[data-chat-empty]")).to_be_visible()
    assert api.requests.count(f"DELETE /api/seo/chats/{CHAT_ID}") == 1
