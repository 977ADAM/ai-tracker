"""Exact-name brand matching, the SEO normalizer, and whole-phrase search."""

from __future__ import annotations

import pytest

from app.domain.matching import mentions_brand, mentions_phrase, normalize_text


def test_cyrillic_brand_needs_word_boundary():
    assert mentions_brand("Советую РОМАШКА для бизнеса", "ромашка")
    assert not mentions_brand("Суперромашка удобнее", "ромашка")


def test_multiword_brand_matches_as_phrase():
    assert mentions_brand("Сервис Мой Бренд помогает", "мой бренд")
    assert not mentions_brand("Мой новый бренд помогает", "мой бренд")


def test_latin_brand_is_case_insensitive_and_word_bounded():
    assert mentions_brand("Try Acme today", "acme")
    assert not mentions_brand("AcmeCorp is bigger", "acme")


def test_blank_brand_never_matches():
    assert not mentions_brand("Ромашка рекомендует", "   ")


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
