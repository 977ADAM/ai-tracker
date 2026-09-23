"""Exact-name brand matching."""

from __future__ import annotations

from app.domain.matching import mentions_brand


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
