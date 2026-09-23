"""Exact-name brand matching against a model answer."""

from __future__ import annotations

import re


def mentions_brand(answer: str, brand: str) -> bool:
    """Return True when the answer contains the brand as a whole word or phrase."""
    folded_answer = answer.casefold()
    folded_brand = brand.strip().casefold()
    if not folded_brand:
        return False
    return re.search(rf"(?<!\w){re.escape(folded_brand)}(?!\w)", folded_answer) is not None
