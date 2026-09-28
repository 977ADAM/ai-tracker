"""Exact-name brand matching against a model answer.

Two matchers live here on purpose. `mentions_brand` is the behavior of the old
`/api/check` flow and stays exactly as it was. `mentions_phrase` is the SEO
matcher: it normalizes Unicode NFKC, casefolds, folds `ё` to `е`, collapses
whitespace, and then looks for the whole phrase between word boundaries.
"""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Fold one string to the comparable SEO form.

    Unicode NFKC, `casefold`, `ё`→`е`, and collapsed whitespace: the shapes a
    model may return for the same name compare equal, while punctuation stays
    in place so it can act as a word boundary.
    """
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return _WHITESPACE.sub(" ", text).strip()


def mentions_brand(answer: str, brand: str) -> bool:
    """Return True when the answer contains the brand as a whole word or phrase."""
    folded_answer = answer.casefold()
    folded_brand = brand.strip().casefold()
    if not folded_brand:
        return False
    return re.search(rf"(?<!\w){re.escape(folded_brand)}(?!\w)", folded_answer) is not None


def mentions_phrase(answer: str, phrase: str) -> bool:
    """Return True when the answer contains the whole phrase on word boundaries.

    Matching is literal after `normalize_text`: no morphology, translation,
    transliteration, or aliases. Punctuation separates words, so `«Ромашка»`
    contains `ромашка` while `Суперромашка` does not.
    """
    normalized_phrase = normalize_text(phrase)
    if not normalized_phrase:
        return False
    normalized_answer = normalize_text(answer)
    if not normalized_answer:
        return False
    return re.search(rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)", normalized_answer) is not None
