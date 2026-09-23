"""Schemas of `GET /api/form`."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FormLimits(BaseModel):
    """Границы, которые страница проверяет до отправки запроса."""

    max_prompts: int = Field(description="Сколько запросов принимает одна проверка")
    max_providers: int = Field(description="Сколько подключений можно выбрать за раз")
    max_prompt_length: int = Field(description="Длина одного запроса в символах")
    max_brand_length: int = Field(description="Длина названия бренда в символах")
    max_domain_length: int = Field(description="Длина домена в символах")


class ScopeOption(BaseModel):
    """Область доступа встроенного подключения GigaChat."""

    value: str = Field(description="Значение, которое уходит в API")
    label: str = Field(description="Подпись для пользователя")


class FormResponse(BaseModel):
    """Что нужно странице проверки перед первым запросом."""

    limits: FormLimits
    new_provider_fields: list[str] = Field(description="Поля формы нового подключения, по порядку")
    scope_options: list[ScopeOption]
    default_provider_ids: list[str] = Field(
        description="Что выбрать по умолчанию; пустой список означает, что готовых подключений нет"
    )
