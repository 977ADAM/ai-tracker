"""Input rules and brand matching for a single check."""

from dataclasses import dataclass
import re


LIMITS = {"max_prompts": 20, "max_providers": 5, "max_prompt_length": 500, "max_brand_length": 100, "max_domain_length": 253}


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
    if "prompts_text" in payload:
        text = payload["prompts_text"]
        if not isinstance(text, str) or len(text) > 20_000:
            raise ValueError("Некорректный список запросов")
        prompts = [line.strip() for line in text.splitlines() if line.strip()]

    if not isinstance(brand, str) or not (1 <= len(brand.strip()) <= LIMITS["max_brand_length"]):
        raise ValueError("Укажите бренд длиной до 100 символов")
    if not isinstance(domain, str) or len(domain.strip()) > LIMITS["max_domain_length"]:
        raise ValueError("Домен должен быть строкой до 253 символов")
    if not isinstance(prompts, list) or not (1 <= len(prompts) <= LIMITS["max_prompts"]):
        raise ValueError("Укажите от 1 до 20 запросов")

    normalized_prompts = []
    for prompt in prompts:
        if not isinstance(prompt, str) or not (1 <= len(prompt.strip()) <= LIMITS["max_prompt_length"]):
            raise ValueError("Каждый запрос должен содержать от 1 до 500 символов")
        normalized_prompts.append(prompt.strip())

    return CheckInput(brand.strip(), domain.strip(), normalized_prompts)


def mentions_brand(answer: str, brand: str) -> bool:
    folded_answer = answer.casefold()
    folded_brand = brand.strip().casefold()
    if not folded_brand:
        return False
    return re.search(rf"(?<!\w){re.escape(folded_brand)}(?!\w)", folded_answer) is not None
