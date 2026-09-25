"""The Yandex search branch of the brand check, driven in a real browser.

Yandex is never called: the suite intercepts the SvelteKit search routes and
answers with controlled snapshots, and a mixed run intercepts `/api/check` too.
A deferred search takes minutes or hours, so instead of waiting the test moves
Playwright's clock past the 30-second poll.
"""

from __future__ import annotations

from uuid import uuid4

from playwright.sync_api import Page, expect

from app import Application
from pages.settings import SettingsPage

POLL_INTERVAL_MS = 30_000
PROMPT = "где купить цветы"
DOMAIN = "example.ru"
FOUND_URL = "https://shop.example.ru/catalog"

MOSCOW_REGION = 1
CITY_REGION = 213

REGIONS = [
    {"id": MOSCOW_REGION, "name": "Москва и Московская область"},
    {"id": CITY_REGION, "name": "Москва"},
]

# A mixed run needs a temporary provider; the QA fixture deletes it afterwards.
RUN_MARK = uuid4().hex[:6]
PROVIDER_NAME = f"QA поиск {RUN_MARK}"
MODEL_NAME = "Основная модель"
ENDPOINT = "https://api.example.com/v1/chat/completions"
KEY = "qa-secret-key"
CHECK_ERROR = "Поиск временно недоступен"


def row(status: str, region: int, name: str, **extra: object) -> dict:
    return {
        "prompt": PROMPT,
        "region_id": region,
        "region_name": name,
        "status": status,
        "position": None,
        "url": None,
        "error": None,
        **extra,
    }


def snapshot(rows: list[dict], *, completed: int, status: str) -> dict:
    found = sum(1 for item in rows if item["status"] == "found")
    failed = sum(1 for item in rows if item["status"] == "error")
    successful = sum(1 for item in rows if item["status"] in ("found", "absent"))
    return {
        "id": "job-1",
        "domain": DOMAIN,
        "regions": [MOSCOW_REGION, CITY_REGION],
        "total": len(rows),
        "completed": completed,
        "status": status,
        "summary": {"successful": successful, "found": found, "failed": failed},
        "results": rows,
    }


PENDING_JOB = snapshot(
    [
        row("waiting", MOSCOW_REGION, "Москва и Московская область"),
        row("found", CITY_REGION, "Москва", position=2, url=FOUND_URL),
    ],
    completed=1,
    status="pending",
)

FINISHED_JOB = snapshot(
    [
        row("found", MOSCOW_REGION, "Москва и Московская область", position=2, url=FOUND_URL),
        row("error", CITY_REGION, "Москва", error="Не удалось получить выдачу Яндекса"),
    ],
    completed=2,
    status="done",
)

CHECK_REPORT = {
    "brand": "Ромашка",
    "domain": DOMAIN,
    "summary": {
        "successful": 1, "failed": 0, "mentioned": 1, "mention_percent": 100,
        "visibility_label": "100%", "mentions_label": "1 из 1 успешных ответов", "errors_label": "0 ошибок API",
    },
    "rows": [{
        "prompt": PROMPT, "answer": "Ромашка рекомендует этот вариант", "mentioned": True,
        "error": None, "status": "mentioned", "provider_name": f"{PROVIDER_NAME} · {MODEL_NAME}",
    }],
    "checks": [{
        "provider_id": "qa-model", "provider_name": f"{PROVIDER_NAME} · {MODEL_NAME}",
        "summary": {"successful": 1, "failed": 0, "mentioned": 1},
        "results": [{
            "prompt": PROMPT, "answer": "Ромашка рекомендует этот вариант", "mentioned": True,
            "error": None, "status": "mentioned",
        }],
    }],
}


def add_two_regions(page: Page) -> None:
    for _ in range(2):
        page.get_by_role("button", name="Добавить регион").click()
    # `exact` keeps the select apart from the remove button of the same row.
    page.get_by_label("Регион 1", exact=True).select_option(str(MOSCOW_REGION))
    page.get_by_label("Регион 2", exact=True).select_option(str(CITY_REGION))


def fill_questions(page: Page, *, brand: bool) -> None:
    if brand:
        page.get_by_label("Название бренда").fill("Ромашка")
    page.get_by_label("Сайт").fill(DOMAIN)
    page.get_by_label("Вопросы клиентов").fill(PROMPT)


def select_no_models(page: Page) -> None:
    for checkbox in page.get_by_role("checkbox").all():
        if checkbox.is_checked():
            checkbox.uncheck()


def route_regions(page: Page) -> None:
    page.route("**/api/search/regions", lambda route: route.fulfill(json=REGIONS))


def test_a_search_only_run_polls_until_every_pair_is_finished(page: Page, application: Application) -> None:
    answers = [PENDING_JOB, FINISHED_JOB]
    page.clock.install()

    def answer_status(route) -> None:
        route.fulfill(json=answers.pop(0) if len(answers) > 1 else answers[0])

    route_regions(page)
    page.route("**/api/search", lambda route: route.fulfill(status=202, json={"id": "job-1", "total": 2, "status": "pending"}))
    page.route("**/api/search/job-1", answer_status)

    page.goto(application.base_url, wait_until="networkidle")
    select_no_models(page)
    add_two_regions(page)
    fill_questions(page, brand=False)

    expect(page.get_by_text("2 запроса к Яндексу")).to_be_visible()
    page.get_by_role("button", name="Проверить бренд").click()

    # The model branch never ran: the page shows the search report alone.
    expect(page.get_by_role("heading", name="Сайт в первой десятке")).to_be_visible()
    expect(page.get_by_text("Пока нет проверки")).to_have_count(0)
    expect(page.get_by_text("Готово 1 из 2")).to_be_visible()
    expect(page.get_by_text("Яндекс считает")).to_be_visible()
    found = page.locator("[data-search-row][data-status='found']")
    expect(found).to_have_count(1)
    expect(found.get_by_role("link")).to_have_attribute("href", FOUND_URL)
    expect(found).to_contain_text("2")

    # The next poll happens 30 seconds later; the clock moves instead of the test.
    page.clock.fast_forward(POLL_INTERVAL_MS)

    expect(page.get_by_text("Готово 2 из 2")).to_be_visible()
    failed = page.locator("[data-search-row][data-status='error']")
    expect(failed).to_contain_text("Ошибка запроса")
    expect(failed).to_contain_text("Не удалось получить выдачу Яндекса")
    expect(failed).not_to_contain_text("не найден")
    expect(page.locator("[data-search-row]")).to_have_count(2)


def test_a_pending_search_cannot_be_submitted_twice(page: Page, application: Application) -> None:
    starts = []

    def start_search(route) -> None:
        starts.append(1)
        route.fulfill(status=202, json={"id": "job-1", "total": 2, "status": "pending"})

    route_regions(page)
    page.route("**/api/search", start_search)
    page.route("**/api/search/job-1", lambda route: route.fulfill(json=PENDING_JOB))
    page.goto(application.base_url, wait_until="networkidle")
    select_no_models(page)
    add_two_regions(page)
    fill_questions(page, brand=False)

    submit = page.get_by_role("button", name="Проверить бренд")
    submit.click()
    expect(page.get_by_text("Готово 1 из 2")).to_be_visible()
    expect(submit).to_be_disabled()
    page.locator("form").evaluate("form => form.requestSubmit()")
    assert starts == [1]


def test_a_model_report_survives_a_failed_search(
    page: Page, settings_page: SettingsPage, application: Application
) -> None:
    settings_page.add_provider(PROVIDER_NAME, ENDPOINT, KEY, model_id="qa-model", model_name=MODEL_NAME)
    settings_page.close()
    expect(page.get_by_role("checkbox", name=f"{PROVIDER_NAME} · {MODEL_NAME}")).to_be_visible()

    route_regions(page)
    page.route("**/api/search", lambda route: route.fulfill(status=503, json={"detail": CHECK_ERROR}))
    page.route("**/api/check", lambda route: route.fulfill(json=CHECK_REPORT))

    page.get_by_role("checkbox", name=f"{PROVIDER_NAME} · {MODEL_NAME}").check()
    add_two_regions(page)
    fill_questions(page, brand=True)
    page.get_by_role("button", name="Проверить бренд").click()

    # Both branches ran: the paid search is mocked, and its failure is shown next
    # to the model report instead of replacing it.
    expect(page.get_by_role("heading", name="Сводка проверки")).to_be_visible()
    expect(page.get_by_text("Ромашка рекомендует этот вариант")).to_be_visible()
    expect(page.get_by_role("alert").filter(has_text=CHECK_ERROR)).to_be_visible()
    expect(page.get_by_text("Сайт не найден в первой десятке")).to_have_count(0)
