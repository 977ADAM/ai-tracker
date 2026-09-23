"""Input rules and brand matching for a single check."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class CheckInput:
    brand: str
    domain: str
    prompts: list[str]


def normalize_request(payload: object) -> CheckInput:
    if not isinstance(payload, dict):
        raise ValueError("Некорректный запрос")

    brand = payload.get("brand")
    domain = payload.get("domain", "")
    prompts = payload.get("prompts")

    if not isinstance(brand, str) or not (1 <= len(brand.strip()) <= 100):
        raise ValueError("Укажите бренд длиной до 100 символов")
    if not isinstance(domain, str) or len(domain.strip()) > 253:
        raise ValueError("Домен должен быть строкой до 253 символов")
    if not isinstance(prompts, list) or not (1 <= len(prompts) <= 20):
        raise ValueError("Укажите от 1 до 20 запросов")

    normalized_prompts = []
    for prompt in prompts:
        if not isinstance(prompt, str) or not (1 <= len(prompt.strip()) <= 500):
            raise ValueError("Каждый запрос должен содержать от 1 до 500 символов")
        normalized_prompts.append(prompt.strip())

    return CheckInput(brand.strip(), domain.strip(), normalized_prompts)


def mentions_brand(answer: str, brand: str) -> bool:
    folded_answer = answer.casefold()
    folded_brand = brand.strip().casefold()
    if not folded_brand:
        return False
    return re.search(rf"(?<!\w){re.escape(folded_brand)}(?!\w)", folded_answer) is not None
