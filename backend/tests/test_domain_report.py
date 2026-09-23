"""Run-wide counters, labels, and the flat rows the report shows."""

from __future__ import annotations

import pytest

from app.domain.models import (
    RESULT_ABSENT,
    RESULT_ERROR,
    RESULT_MENTIONED,
    CheckInput,
    CheckReport,
    PromptResult,
    ProviderCheck,
)
from app.domain.report import summarize


def found(prompt: str, answer: str = "Ромашка рекомендует") -> PromptResult:
    return PromptResult(prompt=prompt, answer=answer, mentioned=True, error=None, status=RESULT_MENTIONED)


def absent(prompt: str) -> PromptResult:
    return PromptResult(prompt=prompt, answer="Ничего не найдено", mentioned=False, error=None, status=RESULT_ABSENT)


def failed(prompt: str, message: str = "Сервис временно недоступен") -> PromptResult:
    return PromptResult(prompt=prompt, answer=None, mentioned=None, error=message, status=RESULT_ERROR)


def check(provider_id: str, *results: PromptResult, name: str | None = None) -> ProviderCheck:
    return ProviderCheck(
        provider_id=provider_id,
        provider_name=name or provider_id.title(),
        results=tuple(results),
    )


def test_counts_and_labels_of_a_successful_run():
    summary = summarize([check("gigachat", found("успех"), found("другой"))])
    assert summary.as_dict() == {
        "successful": 2,
        "failed": 0,
        "mentioned": 2,
        "mention_percent": 100,
        "visibility_label": "100%",
        "mentions_label": "2 из 2 успешных ответов",
        "errors_label": "0 ошибок API",
    }


def test_a_failed_call_is_not_a_negative_mention():
    summary = summarize([check("gigachat", found("успех"), failed("ошибка"))])
    assert summary.successful == 1
    assert summary.failed == 1
    assert summary.mentioned == 1
    assert summary.mention_percent == 100
    assert summary.errors_label == "1 ошибка API"


def test_percent_is_none_when_every_call_fails():
    summary = summarize([check("gigachat", failed("раз"), failed("два"))])
    assert summary.mention_percent is None
    assert summary.visibility_label == "—"
    assert summary.mentions_label == "Нет успешных ответов"


def test_absent_mentions_lower_the_percent():
    summary = summarize([check("gigachat", found("раз"), absent("два"))])
    assert summary.mention_percent == 50
    assert summary.visibility_label == "50%"


@pytest.mark.parametrize(
    ("failed_count", "word"),
    [(0, "ошибок"), (1, "ошибка"), (2, "ошибки"), (4, "ошибки"), (5, "ошибок"),
     (11, "ошибок"), (12, "ошибок"), (21, "ошибка"), (22, "ошибки"), (25, "ошибок"),
     (101, "ошибка"), (111, "ошибок")],
)
def test_error_label_uses_russian_plural(failed_count, word):
    results = [failed(f"ошибка {index}") for index in range(failed_count)]
    summary = summarize([check("gigachat", *results)])
    assert summary.errors_label == f"{failed_count} {word} API"


def test_counts_add_up_across_providers():
    summary = summarize([
        check("gigachat", found("раз"), failed("два")),
        check("deepseek", absent("три"), found("четыре")),
    ])
    assert (summary.successful, summary.failed, summary.mentioned) == (3, 1, 2)
    assert summary.mention_percent == 67


def test_report_rows_keep_provider_order_and_names():
    report = CheckReport(
        brand="Ромашка",
        domain="example.ru",
        checks=(
            check("gigachat", found("раз"), failed("два"), name="GigaChat"),
            check("deepseek", absent("три"), name="DeepSeek"),
        ),
        summary=summarize([
            check("gigachat", found("раз"), failed("два")),
            check("deepseek", absent("три")),
        ]),
    )
    body = report.as_dict()
    assert body["brand"] == "Ромашка"
    assert body["domain"] == "example.ru"
    assert [row["prompt"] for row in body["rows"]] == ["раз", "два", "три"]
    assert [row["provider_name"] for row in body["rows"]] == ["GigaChat", "GigaChat", "DeepSeek"]
    assert body["checks"][0]["summary"] == {"successful": 1, "failed": 1, "mentioned": 1}
    assert body["checks"][1]["results"][0]["status"] == RESULT_ABSENT


def test_check_input_is_a_plain_value_object():
    request = CheckInput(brand="Ромашка", domain="", prompts=("раз",))
    assert request.prompts == ("раз",)
