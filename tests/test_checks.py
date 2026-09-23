import pytest

from ai_tracker.checks import mentions_brand, normalize_request


def test_normalizes_valid_request():
    result = normalize_request(
        {"brand": "  Ромашка  ", "domain": " example.ru ", "prompts": ["  Где купить?  ", "Кого выбрать?"]}
    )
    assert result.brand == "Ромашка"
    assert result.domain == "example.ru"
    assert result.prompts == ["Где купить?", "Кого выбрать?"]


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
    ],
)
def test_rejects_invalid_request(payload):
    with pytest.raises(ValueError):
        normalize_request(payload)


def test_cyrillic_brand_needs_word_boundary():
    assert mentions_brand("Советую РОМАШКА для бизнеса", "ромашка")
    assert not mentions_brand("Суперромашка удобнее", "ромашка")


def test_multiword_brand_matches_as_phrase():
    assert mentions_brand("Сервис Мой Бренд помогает", "мой бренд")
    assert not mentions_brand("Мой новый бренд помогает", "мой бренд")
