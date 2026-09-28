"""The SEO scenario on the home page, without any paid external call.

What the checks cover: the five fields and their client-side validation, the upper
call estimate, the «SEO-анализ» settings tab, the safe error of a start without a
configured service LLM, and a saved report with its SEO history.

No check reaches Yandex or a model API:

* the form validation checks never submit a complete form, and a route guard proves
  that no `POST /api/seo/analyses` leaves the browser;
* the settings checks answer the settings write and the connection probe locally,
  so «Проверить подключение» never spends a real completion;
* the report check prepares a finished analysis straight in `runs.sqlite3` — the
  page then reads it through the real API, and the record is deleted through the
  interface (and removed from the database again in a `finally`).
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import Page, Route, expect

from app import Application
from pages.seo import SeoPage
from pages.settings import SettingsPage

CONFIG_DIR_VARIABLE = "AI_TRACKER_CONFIG_DIR"
DATABASE_NAME = "runs.sqlite3"
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "ai-tracker"

PROVIDER_NAME = f"QA SEO {uuid4().hex[:6]}"
PROVIDER_ENDPOINT = "https://api.example.com/v1/chat/completions"
PROVIDER_KEY = "qa-seo-key"
MODEL_ID = "qa-seo-model"
MODEL_NAME = "Модель"

LLM_ERROR = "Не настроена служебная LLM для SEO-анализа"
LLM_TEST_ERROR = "Не удалось подключиться к служебной LLM"
SEO_ENDPOINT = "https://llm.example.com/v1/chat/completions"
SEO_MODEL = "qa-service-model"

PUBLIC_SEO_SETTINGS = {
    "endpoint": SEO_ENDPOINT,
    "model": SEO_MODEL,
    "has_api_key": True,
    "endpoint_source": "ui",
    "model_source": "ui",
    "api_key_source": "ui",
}

# The fixture analysis: one recurring candidate, one one-off domain, two finite
# Yandex rows and one failed row, and only one answer that names the company.
COMPANY = "Ромашка"
CANDIDATE_HOST = "flower-shop.example"
ONE_OFF_HOST = "one-off.example"
CONNECTION_ID = "qa-seo-connection"
SEEDS = ["купить цветы", "доставка букетов", "цветочный магазин"]
SERVICES = ["Доставка цветов", "Букеты"]
SUMMARY = "Ромашка упоминается в половине успешных ответов."
SEARCH_ERROR = "Не удалось получить выдачу Яндекса"
MODEL_ANSWER = "Ромашка и flower-shop.example предлагают доставку цветов"

ANALYSIS_TABLES = (
    "seo_candidate_hits",
    "seo_search_rows",
    "seo_seed_rows",
    "seo_model_rows",
    "seo_queries",
    "seo_candidates",
    "seo_pages",
    "seo_stages",
)

# The parent table keys its rows by `id`; every child table references it as
# `analysis_id`.
PARENT_TABLE = "seo_analyses"


# -- the database the application already reads -------------------------------


def database_path() -> Path:
    return Path(os.getenv(CONFIG_DIR_VARIABLE, str(DEFAULT_CONFIG_DIR))) / DATABASE_NAME


def seed_finished_analysis() -> str:
    """Insert one completed analysis with its rows, exactly as the schema stores them."""
    path = database_path()
    if not path.exists():
        pytest.skip(
            f"База {path} не найдена. Сквозной отчёт требует AI_TRACKER_CONFIG_DIR "
            "той же серверной части, что отвечает на QA_API_URL."
        )

    analysis_id = f"qa-seo-{uuid4().hex[:10]}"
    now = datetime.now(UTC).isoformat()
    estimate = {"search_upper": 23, "model_upper": 20, "generated_limit": 20, "connections": 1}

    with closing(sqlite3.connect(path, timeout=5)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO seo_analyses (id, status, created_at, updated_at, finished_at, url, host, "
            "sphere, seeds_json, input_services_json, connection_ids_json, estimate_json, "
            "company_name, services_json, summary_text) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                analysis_id, "completed", now, now, now, "https://example.ru/", "example.ru",
                "Цветы", json.dumps(SEEDS, ensure_ascii=False),
                json.dumps(["Доставка цветов"], ensure_ascii=False),
                json.dumps([CONNECTION_ID]), json.dumps(estimate), COMPANY,
                json.dumps(SERVICES, ensure_ascii=False), SUMMARY,
            ),
        )
        connection.executemany(
            "INSERT INTO seo_stages (analysis_id, stage, status, error, counters_json, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            [(analysis_id, stage, "done", None, "{}", now) for stage in range(1, 7)],
        )
        connection.execute(
            "INSERT INTO seo_pages (analysis_id, page_index, url, title) VALUES (?,?,?,?)",
            (analysis_id, 0, "https://example.ru/", "Ромашка — доставка цветов"),
        )
        connection.executemany(
            "INSERT INTO seo_candidates (analysis_id, candidate_index, host, title, occurrences, "
            "average_position, seed_indexes_json, recurring) VALUES (?,?,?,?,?,?,?,?)",
            [
                (analysis_id, 0, CANDIDATE_HOST, "Цветочный магазин — доставка", 2, 2.5,
                 json.dumps([0, 1]), 1),
                (analysis_id, 1, ONE_OFF_HOST, "Разовый результат", 1, 7.0, json.dumps([2]), 0),
            ],
        )
        connection.executemany(
            "INSERT INTO seo_queries (analysis_id, query_index, text, category, service, "
            "mentions_company_name, mentions_company_host, mentions_candidate_host, branded) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (analysis_id, 0, "купить цветы с доставкой", "commercial", "Доставка цветов", 1, 1, 1, 1),
                (analysis_id, 1, "как выбрать букет", "informational", None, 0, 0, 0, 0),
                (analysis_id, 2, "ромашка или другой магазин", "comparative", "Букеты", 1, 0, 0, 1),
            ],
        )
        connection.executemany(
            "INSERT INTO seo_search_rows (analysis_id, query_index, status, operation_id, "
            "site_position, site_url, error, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            [
                (analysis_id, 0, "found", None, 3, "https://example.ru/catalog", None, now),
                (analysis_id, 1, "absent", None, None, None, None, now),
                (analysis_id, 2, "error", None, None, None, SEARCH_ERROR, now),
            ],
        )
        connection.execute(
            "INSERT INTO seo_candidate_hits (analysis_id, query_index, host, position, url) "
            "VALUES (?,?,?,?,?)",
            (analysis_id, 0, CANDIDATE_HOST, 2, "https://flower-shop.example/catalog"),
        )
        connection.executemany(
            "INSERT INTO seo_model_rows (analysis_id, connection_id, provider_name, query_index, "
            "status, answer, name_mentioned, host_mentioned, error, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (analysis_id, CONNECTION_ID, "QA SEO модель", 0, "found", MODEL_ANSWER, 1, 1, None, now),
                (analysis_id, CONNECTION_ID, "QA SEO модель", 1, "found",
                 "Букет собирают из сезонных цветов", 0, 0, None, now),
                (analysis_id, CONNECTION_ID, "QA SEO модель", 2, "error", None, None, None,
                 "Модель недоступна", now),
            ],
        )
        connection.commit()
    return analysis_id


def drop_analysis(analysis_id: str) -> None:
    """Remove the fixture rows; a missing database or table is not a failure."""
    path = database_path()
    if not path.exists():
        return
    with closing(sqlite3.connect(path, timeout=5)) as connection:
        existing = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        for table in ANALYSIS_TABLES:
            if table in existing:
                connection.execute(f"DELETE FROM {table} WHERE analysis_id=?", (analysis_id,))
        if PARENT_TABLE in existing:
            connection.execute(f"DELETE FROM {PARENT_TABLE} WHERE id=?", (analysis_id,))
        connection.commit()


def stored_analyses(analysis_id: str) -> int:
    path = database_path()
    with closing(sqlite3.connect(path, timeout=5)) as connection:
        return connection.execute(
            "SELECT count(*) FROM seo_analyses WHERE id=?", (analysis_id,)
        ).fetchone()[0]


# -- the form -----------------------------------------------------------------


def test_seo_form_renders_and_validates_before_any_call(page: Page, application: Application) -> None:
    seo = SeoPage(page, application.base_url)
    starts: list[str] = []

    def guard(route: Route) -> None:
        if route.request.method == "POST":
            starts.append(route.request.url)
            route.fulfill(status=500, json={"detail": "Клиентская проверка не должна была отправить запрос"})
        else:
            route.fulfill(json={"items": [], "next_cursor": None})

    page.route("**/api/seo/analyses**", guard)
    seo.open()
    expect(seo.url_input).to_be_visible()
    expect(seo.sphere_input).to_be_visible()
    for index in (1, 2, 3):
        expect(seo.seed_input(index)).to_be_visible()
    expect(seo.services_input).to_be_visible()
    expect(seo.page.get_by_text("Инструменты")).to_be_visible()

    seo.uncheck_all_connections()

    seo.submit()
    expect(seo.form_error).to_contain_text("адрес главной страницы")

    seo.fill_form(seeds=["купить цветы", "доставка букетов"])
    seo.submit()
    expect(seo.form_error).to_contain_text("ровно 3")

    seo.fill_form(services="")
    seo.submit()
    expect(seo.form_error).to_contain_text("хотя бы одну услугу")

    seo.fill_form()
    seo.submit()
    expect(seo.form_error).to_contain_text("от 1 до 5")

    assert starts == [], "Клиентская проверка не должна отправлять запуск анализа"


def test_seo_form_shows_the_upper_call_estimate(
    page: Page, settings_page: SettingsPage, application: Application
) -> None:
    settings_page.add_provider(
        PROVIDER_NAME, PROVIDER_ENDPOINT, PROVIDER_KEY, model_id=MODEL_ID, model_name=MODEL_NAME
    )
    settings_page.close()
    seo = SeoPage(page, application.base_url)
    expect(seo.form).to_be_visible()

    seo.uncheck_all_connections()
    expect(seo.estimate_model).to_have_text("0")

    seo.connection_checkbox(PROVIDER_NAME).check()
    expect(seo.estimate_search).to_have_text("23")
    expect(seo.estimate_model).to_have_text("20")
    expect(seo.form).to_contain_text("платные вызовы")
    expect(seo.form).to_contain_text("отложенном режиме")
    expect(seo.form).to_contain_text("отдельно настроенную LLM")


def test_starting_without_a_service_llm_shows_a_safe_error(page: Page, application: Application) -> None:
    posts: list[str] = []

    def answer(route: Route) -> None:
        # The whole resource is answered locally: a valid form must never reach a
        # real orchestrator (and therefore never start a paid run).
        if route.request.method == "POST":
            posts.append(route.request.url)
            route.fulfill(status=400, json={"detail": LLM_ERROR})
        else:
            route.fulfill(json={"items": [], "next_cursor": None})

    page.route("**/api/seo/analyses**", answer)
    settings = SettingsPage(page, application.base_url)
    settings.open()
    settings.add_provider(
        PROVIDER_NAME, PROVIDER_ENDPOINT, PROVIDER_KEY, model_id=MODEL_ID, model_name=MODEL_NAME
    )
    settings.close()
    seo = SeoPage(page, application.base_url)
    seo.fill_form()
    seo.connection_checkbox(PROVIDER_NAME).check()
    seo.submit()

    expect(seo.form_error).to_contain_text(LLM_ERROR)
    expect(seo.run_screen).to_have_count(0)
    expect(seo.page.get_by_text("Пока нет SEO-анализа")).to_be_visible()
    assert len(posts) == 1


# -- settings -----------------------------------------------------------------


def test_seo_settings_tab_saves_and_probes_without_paying(page: Page, application: Application) -> None:
    writes: list[dict] = []

    def settings_write(route: Route) -> None:
        writes.append(route.request.post_data_json)
        route.fulfill(status=200, json=PUBLIC_SEO_SETTINGS)

    def settings_test(route: Route) -> None:
        # A safe result instead of a real completion: the probe must not cost money.
        route.fulfill(status=200, json={"ok": False, "model": None, "error": LLM_TEST_ERROR})

    page.route("**/api/seo/settings/test", settings_test)
    page.route("**/api/seo/settings", settings_write)

    seo = SeoPage(page, application.base_url).open()
    seo.open_seo_settings()
    expect(seo.seo_endpoint_input).to_be_visible()
    expect(seo.seo_model_input).to_be_visible()
    expect(seo.seo_key_input).to_have_value("")

    seo.save_seo_settings(endpoint=SEO_ENDPOINT, model=SEO_MODEL)
    expect(seo.seo_status).to_contain_text("Настройки служебной LLM сохранены")
    assert writes and writes[0]["endpoint"] == SEO_ENDPOINT
    assert writes[0]["model"] == SEO_MODEL
    assert "api_key" not in writes[0], "Пустое поле ключа не должно отправлять ключ"

    seo.test_seo_connection()
    expect(seo.seo_settings_alert).to_contain_text(LLM_TEST_ERROR)

    # The public BFF response never carries the key itself; only its presence.
    response = page.request.get(application.url("/api/seo/settings"))
    assert response.status in (200, 503)
    assert '"api_key"' not in response.text()


# -- the saved report and the SEO history -------------------------------------


def test_saved_report_opens_from_history_and_deletes(page: Page, application: Application) -> None:
    analysis_id = seed_finished_analysis()
    try:
        seo = SeoPage(page, application.base_url).open()
        row = seo.history_row(analysis_id)
        expect(row).to_be_visible()
        expect(row).to_contain_text("Завершён")

        seo.open_report(analysis_id)
        expect(seo.report_status).to_have_text("Завершён")
        expect(seo.report).to_contain_text(COMPANY)

        # Shares are fractions of the successful rows: 1 of 2 overall, 1 of 1 branded.
        assert seo.metric_text("site-overall") == "50 %"
        assert seo.metric_text("site-branded") == "100 %"
        assert seo.metric_text("site-unbranded") == "0 %"
        # The only comparative row failed, so the denominator is empty and the report shows «—».
        assert seo.metric_text("category-comparative") == "—"
        assert seo.metric_text("candidate-flower-shop.example-overall") == "50 %"
        assert seo.metric_text("candidate-flower-shop.example-ai-qa-seo-connection") == "50 %"

        candidate = seo.candidate(CANDIDATE_HOST)
        expect(candidate).to_contain_text("Цветочный магазин — доставка")
        expect(candidate.locator("[data-candidate-occurrences]")).to_have_text("2")
        # A one-off domain is evidence in the details, not a competitor metric.
        expect(seo.page.locator(f"[data-candidate='{ONE_OFF_HOST}']")).to_have_count(0)
        expect(seo.report).to_contain_text(SUMMARY)

        # The saved detail shows the answer and the failed row as they are.
        expect(seo.model_detail_rows.first).to_contain_text("flower-shop.example")
        expect(seo.model_detail_rows.nth(2)).to_contain_text("Модель недоступна")
        expect(seo.search_detail_rows.nth(2)).to_contain_text(SEARCH_ERROR)

        assert stored_analyses(analysis_id) == 1
        seo.delete_analysis(analysis_id)
        expect(seo.history_row(analysis_id)).to_have_count(0)
        assert stored_analyses(analysis_id) == 0
    finally:
        drop_analysis(analysis_id)
