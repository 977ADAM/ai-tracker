"""Normalization and validation of a check request body."""

from __future__ import annotations

from typing import Any

from app.core.errors import ValidationError
from app.domain.limits import LIMITS, MAX_PROMPTS_TEXT_LENGTH
from app.domain.models import CheckInput


def normalize_check_request(payload: object) -> CheckInput:
    """Validate the brand, optional domain, and 1..N prompts of a check request."""
    if not isinstance(payload, dict):
        raise ValidationError("Некорректный запрос")

    brand = payload.get("brand")
    domain = payload.get("domain", "")
    prompts = payload.get("prompts")
    if "prompts_text" in payload:
        text = payload["prompts_text"]
        if not isinstance(text, str) or len(text) > MAX_PROMPTS_TEXT_LENGTH:
            raise ValidationError("Некорректный список запросов")
        prompts = [line.strip() for line in text.splitlines() if line.strip()]

    if not isinstance(brand, str) or not 1 <= len(brand.strip()) <= LIMITS["max_brand_length"]:
        raise ValidationError("Укажите бренд длиной до 100 символов")
    if not isinstance(domain, str) or len(domain.strip()) > LIMITS["max_domain_length"]:
        raise ValidationError("Домен должен быть строкой до 253 символов")
    if not isinstance(prompts, list) or not 1 <= len(prompts) <= LIMITS["max_prompts"]:
        raise ValidationError("Укажите от 1 до 20 запросов")

    normalized_prompts: list[str] = []
    for prompt in prompts:
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= LIMITS["max_prompt_length"]:
            raise ValidationError("Каждый запрос должен содержать от 1 до 500 символов")
        normalized_prompts.append(prompt.strip())

    return CheckInput(brand=brand.strip(), domain=domain.strip(), prompts=tuple(normalized_prompts))


def normalize_provider_ids(payload: object) -> list[str]:
    """Validate the selected connection IDs: 1..max, distinct, non-empty strings."""
    if not isinstance(payload, dict):
        raise ValidationError("Некорректный запрос")
    ids: Any = payload.get("provider_ids")
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= LIMITS["max_providers"]
        or any(not isinstance(item, str) or not item for item in ids)
        or len(ids) != len(set(ids))
    ):
        raise ValidationError("Выберите от 1 до 5 разных моделей")
    return list(ids)
