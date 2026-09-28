"""Manual JSON parsing of SEO service-LLM answers.

The chat contract is a text answer that contains one JSON object, so the parser
tolerates Markdown fences and surrounding prose and otherwise reports a safe
domain error.
"""

from __future__ import annotations

import json
import re

from app.core.errors import ValidationError

FENCED_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
EMPTY_ANSWER = "Модель вернула пустой ответ"
INVALID_JSON = "Не удалось разобрать JSON-ответ модели"
NOT_AN_OBJECT = "Модель вернула JSON не в виде объекта"

_MISSING = object()


def parse_json_object(text: str) -> dict[str, object]:
    """Return the JSON object inside an answer, ignoring fences and prose."""
    if not isinstance(text, str) or not text.strip():
        raise ValidationError(EMPTY_ANSWER)
    candidate = _unfenced(text.strip())
    parsed = _parse(candidate)
    if parsed is _MISSING:
        braced = _outer_braces(candidate)
        parsed = _parse(braced) if braced is not None else _MISSING
    if parsed is _MISSING:
        raise ValidationError(INVALID_JSON)
    if not isinstance(parsed, dict):
        raise ValidationError(NOT_AN_OBJECT)
    return parsed


def _unfenced(text: str) -> str:
    match = FENCED_BLOCK.search(text)
    return match.group(1).strip() if match else text


def _outer_braces(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    return text[start : end + 1]


def _parse(candidate: str) -> object:
    try:
        return json.loads(candidate)
    except ValueError:
        return _MISSING
