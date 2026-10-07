"""The SEO chat on the home page, without any paid external call.

What the checks cover: a full dialogue that reaches a run and its report, the
clear refusal of a «да» with no proposal behind it, the safe refusal when the
service LLM is not configured, and the «SEO-анализ» settings tab with its
tool-support probe.

No check reaches Yandex or a model API. The BFF is answered locally by the `api`
fixture: `POST /api/seo/chats`, the message and proposal resources,
`GET /api/seo/analyses/{id}` and its trace and rows pages all stay inside the
browser, so no run is funded and no row is written to the real database. The
service LLM itself is scripted: `api.route_completion` gives the answer the model
would write, and the fake server takes the same decision the backend takes.
"""

from __future__ import annotations

import json

from playwright.sync_api import Page, Route, expect

from app import Application
from pages.fake_api import CONCLUSIONS_SUMMARY, CONCLUSIONS_MODEL
from pages.seo import SeoChatPage

DESCRIPTION = (
    "Проанализируй https://example.ru, доставка цветов, запросы: "
    "букеты москва, доставка цветов, цветы с доставкой, услуги: букеты"
)

# The service LLM's answer to «да»: it names the intent, and the server decides.
CONFIRM_JSON = json.dumps({"reply": "Запускаю прогон.", "intent": "confirm", "params": {}}, ensure_ascii=False)

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


# -- the dialogue --------------------------------------------------------------


def test_dialogue_reaches_a_report(page: Page, api) -> None:
    chat = SeoChatPage(page)
    chat.open()
    chat.send(DESCRIPTION)
    assert chat.proposal().is_visible()
    api.route_completion(answer=CONFIRM_JSON)
    chat.send("да")
    assert chat.run_card().is_visible()

    # The confirmation funds exactly one run, and its card reaches the report.
    expect(chat.run_cards()).to_have_count(1)
    expect(chat.report()).to_be_visible()
    expect(chat.report_status).to_have_text("Завершён")
    assert chat.metric_text("site-overall") == "50 %"
    expect(chat.conclusions).to_contain_text("Текст модели")
    expect(chat.conclusions).to_contain_text(CONCLUSIONS_MODEL)
    expect(chat.conclusions_summary).to_have_text(CONCLUSIONS_SUMMARY)


def test_confirm_without_a_proposal_is_explained(page: Page, api) -> None:
    # «да» as the first message: there is no proposal to confirm and no parameters
    # to launch, so the assistant answers with the fixed sentence, not with a run.
    api.route_completion(answer=CONFIRM_JSON)
    chat = SeoChatPage(page).open()
    chat.send("да")

    expect(chat.message("Сейчас нечего запускать")).to_be_visible()
    expect(chat.run_cards()).to_have_count(0)
    expect(chat.page.locator("[data-chat-proposal]")).to_have_count(0)


# -- the service LLM -----------------------------------------------------------


def test_unconfigured_llm_is_explained(page: Page, api) -> None:
    api.route_error("/api/seo/chats", status=400, detail="Служебная LLM не настроена")
    chat = SeoChatPage(page)
    chat.open()
    chat.send("проверь сайт")
    assert "Служебная LLM" in chat.error_text()


# -- settings ------------------------------------------------------------------


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

    seo = SeoChatPage(page, application.base_url).open()
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
    # The probe always names tool support: the agent runtime needs native tool calling.
    expect(seo.seo_settings_alert).to_contain_text("Инструменты: не поддерживаются")

    # The same probe answered with a tool-capable model shows the positive result.
    page.route("**/api/seo/settings/test", lambda route: route.fulfill(
        status=200, json={"ok": True, "model": SEO_MODEL, "tools": True}
    ))
    seo.test_seo_connection()
    expect(seo.seo_status).to_contain_text(f"Подключение работает: {SEO_MODEL}")
    expect(seo.seo_status).to_contain_text("Инструменты: поддерживаются")

    # The public BFF response never carries the key itself; only its presence.
    response = page.request.get(application.url("/api/seo/settings"))
    assert response.status in (200, 503)
    assert '"api_key"' not in response.text()
