"""Input limits and GigaChat scope options exposed to the browser."""

from __future__ import annotations

LIMITS = {
    "max_prompts": 20,
    "max_providers": 5,
    "max_prompt_length": 500,
    "max_brand_length": 100,
    "max_domain_length": 253,
}

MAX_PROMPTS_TEXT_LENGTH = 20_000
MAX_API_KEY_LENGTH = 10_000
MAX_NAME_LENGTH = 100
MAX_MODEL_LENGTH = 100
MAX_ENDPOINT_LENGTH = 2048

SCOPE_OPTIONS = [
    {"value": "GIGACHAT_API_PERS", "label": "Персональный"},
    {"value": "GIGACHAT_API_B2B", "label": "Бизнес"},
    {"value": "GIGACHAT_API_CORP", "label": "Корпоративный"},
]

SCOPE_VALUES = frozenset(option["value"] for option in SCOPE_OPTIONS)
