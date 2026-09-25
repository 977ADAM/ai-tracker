"""Search rows within saved runs, driven by controlled browser responses."""

from __future__ import annotations

import re
from uuid import uuid4

from playwright.sync_api import Page, expect

from app import Application
from pages.settings import SettingsPage

PROMPT = "где купить цветы"
RUN_ID = "search-qa-run"
FOUND_URL = "https://shop.example.ru/catalog"
PROVIDER_NAME = f"QA поиск {uuid4().hex[:6]}"
MODEL_NAME = "Основная модель"
MODEL_ID = "qa-search-model"


def search_row(index: int, status: str, **extra: object) -> dict:
    return {"search_index": index, "prompt_index": 0, "region_index": index,
            "prompt": PROMPT, "region_id": [1, 213][index],
            "region_name": ["Москва и Московская область", "Москва"][index],
            "status": status, "position": None, "url": None, "error": None, **extra}


def summary_row(source: str, status: str, *, region: str = "—", site: str = "—", brand: str = "—", position: str = "—") -> dict:
    return {"prompt": PROMPT, "source": source, "language": "ru" if source == "Яндекс" else "",
            "region": region, "ai_answer": "Да" if source != "Яндекс" and status == "Готово" else "—",
            "site_found": site, "position": position, "brand_found": brand, "status": status}


def run_snapshot(rows: list[dict], *, model: bool = False) -> dict:
    pending = any(item["status"] in ("waiting", "submitting") for item in rows)
    models = [{"provider_id": MODEL_ID, "prompt_index": 0, "provider_name": f"{PROVIDER_NAME} · {MODEL_NAME}",
               "prompt": PROMPT, "status": "mentioned", "answer": "Ромашка рекомендует цветы",
               "mentioned": True, "error": None}] if model else []
    summary = [summary_row("Яндекс", "Готово" if row["status"] in ("found", "absent") else
                           "Ошибка" if row["status"] == "error" else "Выполняется",
                           region=row["region_name"], site="Да" if row["status"] == "found" else
                           "Нет" if row["status"] == "absent" else "—",
                           position=str(row["position"]) if row["position"] else "—") for row in rows]
    if model:
        summary.append(summary_row(f"{PROVIDER_NAME} · {MODEL_NAME}", "Готово", brand="Да"))
    return {"id": RUN_ID, "created_at": "2026-09-25T14:00:00Z", "finished_at": None if pending else "2026-09-25T14:01:00Z",
            "status": "pending" if pending else "done", "brand": "Ромашка" if model else "",
            "domain": "example.ru", "prompts": [PROMPT], "provider_ids": [MODEL_ID] if model else [],
            "regions": [1, 213], "models": models, "search": rows, "summary_rows": summary}


def mock_runs(page: Page, snapshots: list[dict], starts: list[dict]) -> None:
    def answer(route) -> None:
        path = route.request.url.split("?", 1)[0]
        method = route.request.method
        if path.endswith("/api/runs") and method == "POST":
            starts.append(route.request.post_data_json)
            route.fulfill(status=202, json={"id": RUN_ID, "status": "pending"})
        elif path.endswith("/api/runs"):
            route.fulfill(json={"items": [] if not starts else [{"id": RUN_ID, "created_at": "2026-09-25T14:00:00Z",
                "status": snapshots[0]["status"], "prompts": [PROMPT]}], "next_cursor": None})
        elif path.endswith(f"/api/runs/{RUN_ID}"):
            route.fulfill(json=snapshots.pop(0) if len(snapshots) > 1 else snapshots[0])
        else:
            route.fulfill(status=404, json={"detail": "Нет прогона"})
    page.route("**/api/runs**", answer)


def fill_search_form(page: Page, *, model: bool = False) -> None:
    if not model:
        for checkbox in page.get_by_role("checkbox").all():
            if checkbox.is_checked():
                checkbox.uncheck()
    else:
        page.get_by_label("Название бренда").fill("Ромашка")
    page.get_by_label("Сайт").fill("example.ru")
    page.get_by_label("Вопросы клиентов").fill(PROMPT)
    for _ in range(2):
        page.get_by_role("button", name="Добавить регион").click()
    page.get_by_label("Регион 1", exact=True).select_option("1")
    page.get_by_label("Регион 2", exact=True).select_option("213")


def test_search_only_run_polls_and_keeps_found_link(page: Page, application: Application) -> None:
    starts = []
    pending = run_snapshot([search_row(0, "waiting"), search_row(1, "found", position=2, url=FOUND_URL)])
    done = run_snapshot([search_row(0, "found", position=2, url=FOUND_URL),
                         search_row(1, "error", error="Не удалось получить выдачу Яндекса")])
    mock_runs(page, [pending, done], starts)
    page.clock.install()
    page.goto(application.base_url, wait_until="networkidle")
    fill_search_form(page)
    expect(page.get_by_text("2 запроса к Яндексу")).to_be_visible()
    page.get_by_role("button", name="Проверить бренд").click()
    expect(page.get_by_role("heading", name="Поиск в Яндексе")).to_be_visible()
    expect(page.get_by_text("Яндекс ещё считает результат.")).to_be_visible()
    expect(page.get_by_role("link", name="Открыть найденную страницу")).to_have_attribute("href", FOUND_URL)
    assert starts[0]["provider_ids"] == []
    page.clock.fast_forward(30_000)
    expect(page.get_by_text("Не удалось получить выдачу Яндекса")).to_be_visible()
    expect(page.get_by_role("link", name="Экспорт")).to_be_visible()


def test_pending_run_cannot_submit_twice(page: Page, application: Application) -> None:
    starts = []
    pending = run_snapshot([search_row(0, "waiting"), search_row(1, "waiting")])
    mock_runs(page, [pending], starts)
    page.goto(application.base_url, wait_until="networkidle")
    fill_search_form(page)
    page.get_by_role("button", name="Проверить бренд").click()
    expect(page.get_by_role("button", name="Проверка выполняется")).to_be_disabled()
    page.locator("form").evaluate("form => form.requestSubmit()")
    assert len(starts) == 1


def test_model_answer_survives_a_failed_search(page: Page, settings_page: SettingsPage, application: Application) -> None:
    settings_page.add_provider(PROVIDER_NAME, "https://api.example.com/v1/chat/completions",
                               "qa-secret-key", model_id=MODEL_ID, model_name=MODEL_NAME)
    settings_page.close()
    starts = []
    done = run_snapshot([search_row(0, "error", error="Поиск временно недоступен"),
                         search_row(1, "error", error="Поиск временно недоступен")], model=True)
    mock_runs(page, [done], starts)
    page.get_by_role("checkbox", name=re.compile(PROVIDER_NAME)).check()
    fill_search_form(page, model=True)
    page.get_by_role("button", name="Проверить бренд").click()
    expect(page.get_by_text("Ромашка рекомендует цветы")).to_be_visible()
    expect(page.get_by_text("Поиск временно недоступен").first).to_be_visible()
    assert len(starts[0]["provider_ids"]) == 1
