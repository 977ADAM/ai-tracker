"""The brand normalizer and whole-phrase search."""

from __future__ import annotations

import pytest

from app.domain.matching import mentions_phrase, normalize_text


def test_normalize_text_folds_unicode_and_whitespace():
    assert normalize_text("  Мой\xa0 Бренд  ") == "мой бренд"
    assert normalize_text("ＡＣＭＥ") == "acme"
    assert normalize_text("Ёлка\tи\nёжик") == "елка и ежик"
    assert normalize_text("Мой,  бренд!") == "мой, бренд!"
    assert normalize_text("") == ""


@pytest.mark.parametrize(
    ("answer", "phrase"),
    [
        ("«Ромашка» — лучшая клиника", "ромашка"),
        ("Сервис Мой\nБренд помогает", "мой бренд"),
        ("Ёлка рекомендует", "елка"),
        ("ＡＣＭＥ советует", "acme"),
        ("Мы — Acme, и это хорошо", "acme"),
        ("бренд.ромашка", "ромашка"),
    ],
)
def test_mentions_phrase_matches_a_whole_phrase(answer, phrase):
    assert mentions_phrase(answer, phrase) is True


@pytest.mark.parametrize(
    ("answer", "phrase"),
    [
        ("Суперромашка удобнее", "ромашка"),
        ("Мой новый бренд помогает", "мой бренд"),
        ("AcmeCorp is bigger", "acme"),
        ("Ромашка рекомендует", "   "),
        ("", "ромашка"),
    ],
)
def test_mentions_phrase_rejects_partial_or_blank_matches(answer, phrase):
    assert mentions_phrase(answer, phrase) is False
