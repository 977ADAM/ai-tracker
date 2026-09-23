"""Input normalization and the selection rules of a check request."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.domain.requests import normalize_check_request, normalize_provider_ids


def test_normalizes_valid_request():
    result = normalize_check_request(
        {"brand": "  Ромашка  ", "domain": " example.ru ", "prompts": ["  Где купить?  ", "Кого выбрать?"]}
    )
    assert result.brand == "Ромашка"
    assert result.domain == "example.ru"
    assert result.prompts == ("Где купить?", "Кого выбрать?")


def test_prompts_text_is_split_into_nonempty_lines():
    result = normalize_check_request({"brand": "Ромашка", "prompts_text": "первый\n\n  второй  \n"})
    assert result.prompts == ("первый", "второй")


@pytest.mark.parametrize(
    "payload",
    [
        {"brand": "", "prompts": ["вопрос"]},
        {"brand": "Ромашка", "prompts": []},
        {"brand": "Ромашка", "prompts": [" "]},
        {"brand": "Ромашка", "prompts": ["вопрос"] * 21},
        {"brand": "x" * 101, "prompts": ["вопрос"]},
        {"brand": "Ромашка", "prompts": ["x" * 501]},
        {"brand": "Ромашка", "domain": "x" * 254, "prompts": ["вопрос"]},
        {"brand": "Ромашка", "prompts": "вопрос"},
        {"brand": "Ромашка", "prompts_text": 42},
        "не объект",
    ],
)
def test_rejects_invalid_request(payload):
    with pytest.raises(ValidationError):
        normalize_check_request(payload)


def test_provider_ids_accept_a_distinct_selection():
    assert normalize_provider_ids({"provider_ids": ["gigachat", "deepseek"]}) == ["gigachat", "deepseek"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"provider_ids": []},
        {"provider_ids": "gigachat"},
        {"provider_ids": ["gigachat", "gigachat"]},
        {"provider_ids": ["gigachat"] * 6},
        {"provider_ids": [1]},
        {"provider_ids": [""]},
        {"provider_ids": [None]},
    ],
)
def test_rejects_invalid_provider_selection(payload):
    with pytest.raises(ValidationError):
        normalize_provider_ids(payload)
