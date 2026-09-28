"""The manual JSON contract of the SEO service LLM answers."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.domain.seo_llm import parse_json_object

OBJECT = '{"company_name": "Ромашка", "services": ["доставка"]}'


def test_reads_a_plain_object():
    assert parse_json_object(OBJECT) == {"company_name": "Ромашка", "services": ["доставка"]}


@pytest.mark.parametrize(
    "text",
    [
        f"```json\n{OBJECT}\n```",
        f"```\n{OBJECT}\n```",
        f"```JSON {OBJECT} ```",
    ],
)
def test_reads_a_markdown_fenced_object(text):
    assert parse_json_object(text) == {"company_name": "Ромашка", "services": ["доставка"]}


@pytest.mark.parametrize(
    "text",
    [
        f"Вот результат:\n{OBJECT}\nГотово.",
        f"Вот результат:\n```json\n{OBJECT}\n```\nГотово.",
        f"Ответ модели: {OBJECT}",
    ],
)
def test_reads_an_object_wrapped_in_prose(text):
    assert parse_json_object(text) == {"company_name": "Ромашка", "services": ["доставка"]}


def test_reads_nested_values_unchanged():
    text = 'prefix {"a": {"b": [1, 2, {"c": null}]}, "d": true} suffix'

    assert parse_json_object(text) == {"a": {"b": [1, 2, {"c": None}]}, "d": True}


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "\n\t ",
        "not json at all",
        "{broken",
        '{"a": 1,}',
        "{'a': 1}",
        "```json\nnot json\n```",
    ],
)
def test_invalid_json_is_a_domain_error(text):
    with pytest.raises(ValidationError):
        parse_json_object(text)


@pytest.mark.parametrize(
    "text",
    [
        "[1, 2, 3]",
        "```json\n[1, 2, 3]\n```",
        "null",
        '"text"',
    ],
)
def test_non_object_json_is_a_domain_error(text):
    with pytest.raises(ValidationError):
        parse_json_object(text)


@pytest.mark.parametrize("value", [None, 42, ["{}"]])
def test_non_string_input_is_a_domain_error(value):
    with pytest.raises(ValidationError):
        parse_json_object(value)
