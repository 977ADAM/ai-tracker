"""Saved mixed runs in a real browser, with controlled API responses."""

from __future__ import annotations

import re
from uuid import uuid4

from playwright.sync_api import Page, expect

from app import Application
from pages.settings import SettingsPage

RUN_ID = "qa-run-1"
PROMPT = "где купить цветы"
REGIONS = [1, 213]
PROVIDER_NAME = f"QA история {uuid4().hex[:6]}"
MODEL_NAME = "Основная модель"
MODEL_ID = "qa-history-model"
FOUND_URL = "https://shop.example.ru/catalog"


def model(status: str) -> dict:
    return {"provider_id": MODEL_ID, "prompt_index": 0, "provider_name": f"{PROVIDER_NAME} · {MODEL_NAME}",
            "prompt": PROMPT, "status": status, "answer": "Ромашка рекомендует цветы" if status == "mentioned" else None,
            "mentioned": True if status == "mentioned" else None, "error": None}


def search(index: int, status: str) -> dict:
    return {"search_index": index, "prompt_index": 0, "region_index": index,
            "prompt": PROMPT, "region_id": REGIONS[index],
            "region_name": "Москва и Московская область" if index == 0 else "Москва",
            "status": status, "position": 2 if status == "found" else None,
            "url": FOUND_URL if status == "found" else None, "error": None}


def summary(source: str, status: str, *, region: str = "—", site: str = "—", brand: str = "—", position: str = "—") -> dict:
    return {"prompt": PROMPT, "source": source, "language": "ru" if source == "Яндекс" else "",
            "region": region, "ai_answer": "Да" if source != "Яндекс" and status == "Готово" else "—",
            "site_found": site, "position": position, "brand_found": brand, "status": status}


def snapshot(status: str) -> dict:
    pending = status == "pending"
    return {"id": RUN_ID, "created_at": "2026-09-25T14:00:00Z",
            "finished_at": None if pending else "2026-09-25T14:01:00Z", "status": status,
            "brand": "Ромашка", "domain": "example.ru", "prompts": [PROMPT],
            "provider_ids": [MODEL_ID], "regions": REGIONS,
            "models": [model("mentioned")],
            "search": [search(0, "found"), search(1, "waiting" if pending else "interrupted")],
            "summary_rows": [
                summary("Яндекс", "Готово", region="Москва и Московская область", site="Да", position="2"),
                summary("Яндекс", "Выполняется" if pending else "Прервано", region="Москва"),
                summary(f"{PROVIDER_NAME} · {MODEL_NAME}", "Готово", brand="Да"),
            ]}


def test_mixed_run_history_export_and_delete(page: Page, settings_page: SettingsPage, application: Application) -> None:
    settings_page.add_provider(PROVIDER_NAME, "https://api.example.com/v1/chat/completions",
                               "qa-secret-key", model_id=MODEL_ID, model_name=MODEL_NAME)
    settings_page.close()
    page.clock.install()
    state = {"created": False, "deleted": False, "finished": False, "posts": 0, "legacy": []}

    def route_runs(route) -> None:
        path = route.request.url.split("?", 1)[0]
        method = route.request.method
        if path.endswith("/api/runs") and method == "POST":
            state["posts"] += 1
            state["created"] = True
            route.fulfill(status=202, json={"id": RUN_ID, "status": "pending"})
        elif path.endswith("/api/runs") and method == "GET":
            items = [] if not state["created"] or state["deleted"] else [{
                "id": RUN_ID, "created_at": "2026-09-25T14:00:00Z",
                "status": "interrupted" if state["finished"] else "pending", "prompts": [PROMPT]}]
            route.fulfill(json={"items": items, "next_cursor": None})
        elif path.endswith(f"/api/runs/{RUN_ID}/export.csv"):
            route.fulfill(status=200, body=b"\xef\xbb\xbf\xd0\x97\xd0\xb0\xd0\xbf\xd1\x80\xd0\xbe\xd1\x81\n",
                          headers={"content-type": "text/csv; charset=utf-8",
                                   "content-disposition": 'attachment; filename="ai-serp-results-2026-09-25.csv"'})
        elif path.endswith(f"/api/runs/{RUN_ID}") and method == "DELETE":
            state["deleted"] = True
            route.fulfill(status=204, body="")
        elif path.endswith(f"/api/runs/{RUN_ID}") and method == "GET":
            route.fulfill(json=snapshot("interrupted" if state["finished"] else "pending"))
        else:
            route.fulfill(status=404, json={"detail": "Нет прогона"})

    def legacy(route) -> None:
        state["legacy"].append(route.request.url)
        route.fulfill(status=500, json={"detail": "Не используйте старые маршруты"})

    page.route("**/api/runs**", route_runs)
    page.route("**/api/check", legacy)
    page.route("**/api/search", legacy)
    page.goto(application.base_url, wait_until="networkidle")
    page.get_by_role("checkbox", name=re.compile(PROVIDER_NAME)).check()
    page.get_by_label("Название бренда").fill("Ромашка")
    page.get_by_label("Сайт").fill("example.ru")
    page.get_by_label("Вопросы клиентов").fill(PROMPT)
    for _ in range(2):
        page.get_by_role("button", name="Добавить регион").click()
    page.get_by_label("Регион 1", exact=True).select_option("1")
    page.get_by_label("Регион 2", exact=True).select_option("213")
    page.get_by_role("button", name="Проверить бренд").click()

    expect(page.get_by_role("heading", name="Таблица результатов")).to_be_visible()
    expect(page.get_by_text("Выполняется", exact=True).first).to_be_visible()
    expect(page.get_by_role("link", name="Экспорт")).to_have_count(0)
    expect(page.get_by_role("button", name="Проверка выполняется")).to_be_disabled()
    page.locator("form").evaluate("form => form.requestSubmit()")
    assert state["posts"] == 1
    assert state["legacy"] == []

    state["finished"] = True
    page.clock.fast_forward(30_000)
    expect(page.get_by_text("Прервано", exact=True).first).to_be_visible()
    expect(page.get_by_role("link", name="Экспорт")).to_be_visible()
    page.set_viewport_size({"width": 375, "height": 800})
    table = page.get_by_role("table", name="Таблица результатов")
    assert table.evaluate("table => table.scrollWidth > table.parentElement.clientWidth")
    expect(page.get_by_role("link", name="Экспорт")).to_be_visible()
    page.set_viewport_size({"width": 1440, "height": 900})
    with page.expect_download() as download_info:
        page.get_by_role("link", name="Экспорт").click()
    assert download_info.value.suggested_filename == "ai-serp-results-2026-09-25.csv"

    page.reload(wait_until="networkidle")
    page.get_by_role("button", name="Посмотреть задачу").first.click()
    expect(page.get_by_role("heading", name="Таблица результатов")).to_be_visible()
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name=f"Удалить прогон {RUN_ID}").click()
    expect(page.get_by_text("Сохранённых прогонов пока нет.")).to_be_visible()
