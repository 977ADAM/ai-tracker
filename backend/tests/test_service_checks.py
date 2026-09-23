"""The check use case: isolation between connections and safe failure messages."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.service.checks import MISSING_KEY_MESSAGE, CheckService
from app.service.connections import ConnectionService
from tests.fakes import ABSENT_ANSWER, MENTION_ANSWER, ProviderFactorySpy


@pytest.fixture
def connections(repository, settings) -> ConnectionService:
    return ConnectionService(repository, settings)


def configure(connections: ConnectionService, *connection_ids: str) -> None:
    for index, connection_id in enumerate(connection_ids):
        connections.save({"api_key": f"key-{index}"}, connection_id)


def check_service(connections: ConnectionService, factory=None) -> tuple[CheckService, ProviderFactorySpy]:
    spy = factory or ProviderFactorySpy()
    return CheckService(connections, spy), spy


def test_runs_the_same_prompts_against_every_selected_connection(connections):
    configure(connections, "gigachat", "deepseek")
    service, spy = check_service(connections)

    report = service.run(
        {"brand": " Ромашка ", "domain": " example.ru ", "prompts": ["успех", "другой"],
         "provider_ids": ["gigachat", "deepseek"]}
    )

    assert report["brand"] == "Ромашка"
    assert report["domain"] == "example.ru"
    assert [check["provider_id"] for check in report["checks"]] == ["gigachat", "deepseek"]
    assert spy.prompts == [
        ("gigachat", "успех"), ("gigachat", "другой"),
        ("deepseek", "успех"), ("deepseek", "другой"),
    ]
    assert report["summary"] == {
        "successful": 4, "failed": 0, "mentioned": 4, "mention_percent": 100,
        "visibility_label": "100%", "mentions_label": "4 из 4 успешных ответов", "errors_label": "0 ошибок API",
    }


def test_a_failing_connection_does_not_erase_another_one(connections):
    configure(connections, "gigachat", "deepseek")
    service, _spy = check_service(connections, ProviderFactorySpy(explode_ids=("gigachat",)))

    report = service.run({"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ["gigachat", "deepseek"]})

    assert report["checks"][0]["summary"] == {"successful": 0, "failed": 1, "mentioned": 0}
    assert report["checks"][1]["summary"] == {"successful": 1, "failed": 0, "mentioned": 1}
    assert "private path" not in str(report)


def test_a_failed_prompt_is_not_a_negative_mention(connections):
    configure(connections, "gigachat")
    service, _ = check_service(connections)

    report = service.run({"brand": "Ромашка", "prompts": ["успех", "ошибка"], "provider_ids": ["gigachat"]})

    assert report["summary"]["successful"] == 1
    assert report["summary"]["failed"] == 1
    assert report["summary"]["mentioned"] == 1
    assert report["checks"][0]["results"][1] == {
        "prompt": "ошибка",
        "answer": None,
        "mentioned": None,
        "error": "Сервис временно недоступен",
        "status": "error",
    }


def test_an_absent_mention_is_reported_separately(connections):
    configure(connections, "gigachat")
    service, _ = check_service(connections, ProviderFactorySpy(failing_ids=("gigachat",)))

    report = service.run({"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ["gigachat"]})

    assert report["checks"][0]["results"][0] == {
        "prompt": "вопрос",
        "answer": ABSENT_ANSWER,
        "mentioned": False,
        "error": None,
        "status": "absent",
    }


def test_a_missing_key_fails_every_prompt_without_building_a_provider(connections):
    service, spy = check_service(connections)

    report = service.run({"brand": "Ромашка", "prompts": ["раз", "два"], "provider_ids": ["gigachat"]})

    assert spy.keys == []
    assert report["checks"][0]["summary"] == {"successful": 0, "failed": 2, "mentioned": 0}
    assert {result["error"] for result in report["checks"][0]["results"]} == {MISSING_KEY_MESSAGE}
    assert report["summary"]["mention_percent"] is None


def test_a_key_lookup_failure_becomes_a_provider_error(connections, secrets):
    service, _ = check_service(connections)
    secrets.fail = True

    report = service.run({"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ["gigachat"]})

    assert report["checks"][0]["results"][0]["error"] == "Системное хранилище ключей недоступно"


def test_clients_are_closed_after_a_run(connections):
    configure(connections, "gigachat")
    service, spy = check_service(connections)

    service.run({"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ["gigachat"]})

    assert spy.providers["gigachat"].closed is True


def test_a_failing_close_does_not_break_the_report(connections):
    configure(connections, "gigachat")

    class RudeClose(ProviderFactorySpy):
        def __call__(self, connection, key):
            provider = super().__call__(connection, key)

            def explode() -> None:
                raise RuntimeError("close failed")

            provider.close = explode  # type: ignore[method-assign]
            return provider

    service, _ = check_service(connections, RudeClose())
    report = service.run({"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ["gigachat"]})

    assert report["checks"][0]["summary"]["successful"] == 1


def test_an_unknown_connection_is_rejected_before_any_call(connections):
    service, spy = check_service(connections)
    with pytest.raises(ValidationError):
        service.run({"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ["missing"]})
    assert spy.keys == []


def test_duplicate_or_oversized_selection_is_rejected(connections):
    configure(connections, "gigachat", "deepseek")
    service, spy = check_service(connections)
    for ids in (["gigachat", "gigachat"], ["gigachat"] * 6, [], None):
        with pytest.raises(ValidationError):
            service.run({"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ids})
    assert spy.keys == []


def test_a_non_string_answer_is_reported_as_an_error(connections):
    configure(connections, "gigachat")

    class Broken(ProviderFactorySpy):
        def __call__(self, connection, key):
            provider = super().__call__(connection, key)
            provider.answer = lambda prompt: None  # type: ignore[method-assign,assignment]
            return provider

    service, _ = check_service(connections, Broken())
    report = service.run({"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ["gigachat"]})

    assert report["checks"][0]["results"][0]["status"] == "error"
    assert report["checks"][0]["results"][0]["error"] == "Не удалось получить ответ API модели"


def test_rows_carry_the_provider_name(connections):
    configure(connections, "gigachat")
    service, _ = check_service(connections)

    report = service.run({"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ["gigachat"]})

    assert report["rows"] == [{
        "prompt": "вопрос",
        "answer": MENTION_ANSWER,
        "mentioned": True,
        "error": None,
        "status": "mentioned",
        "provider_name": "GigaChat",
    }]
