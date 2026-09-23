"""Schemas of `POST /api/check`."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import ResultStatus

CHECK_EXAMPLE = {
    "brand": "Ромашка",
    "domain": "example.ru",
    "prompts_text": "Где заказать цветы?",
    "provider_ids": ["gigachat"],
}


class CheckRequest(BaseModel):
    """Тело запроса на проверку.

    Запросы можно передать списком `prompts` или текстом `prompts_text`, по
    одному запросу в строке. Пустые строки отбрасываются, длина и количество
    проверяются доменными правилами.
    """

    model_config = ConfigDict(json_schema_extra={"example": CHECK_EXAMPLE})

    brand: str = Field(description="Название бренда: ищем точное совпадение в ответе")
    domain: str = Field(default="", description="Необязательный контекст; ссылки не проверяются")
    prompts: list[str] | None = Field(default=None, description="От 1 до 20 запросов")
    prompts_text: str | None = Field(
        default=None,
        description="Те же запросы текстом, по одному в строке; заменяет `prompts`",
    )
    provider_ids: list[str] | None = Field(
        default=None,
        description="От 1 до 5 разных идентификаторов сохранённых подключений",
    )


class PromptResultResponse(BaseModel):
    """Результат одного запроса у одного подключения."""

    prompt: str
    answer: str | None = Field(description="Ответ модели; при ошибке — null")
    mentioned: bool | None = Field(description="Найден ли бренд; при ошибке — null")
    error: str | None = Field(description="Текст ошибки; у успешного ответа — null")
    status: ResultStatus = Field(description="mentioned — бренд найден, absent — нет, error — вызов не удался")


class ProviderCheckSummary(BaseModel):
    """Счётчики одного подключения."""

    successful: int
    failed: int
    mentioned: int


class ProviderCheckResponse(BaseModel):
    """Группа результатов одного подключения. Падение одного не затрагивает другие."""

    provider_id: str
    provider_name: str
    summary: ProviderCheckSummary
    results: list[PromptResultResponse]


class CheckSummaryResponse(BaseModel):
    """Итоги всей проверки вместе с готовыми подписями."""

    successful: int
    failed: int
    mentioned: int
    mention_percent: int | None = Field(description="Доля упоминаний; null, если успешных ответов не было")
    visibility_label: str
    mentions_label: str
    errors_label: str


class CheckRowResponse(PromptResultResponse):
    """Строка плоского списка: тот же результат плюс имя подключения."""

    provider_name: str


class CheckResponse(BaseModel):
    """Ответ на проверку."""

    brand: str
    domain: str
    checks: list[ProviderCheckResponse] = Field(description="Результаты по каждому выбранному подключению")
    summary: CheckSummaryResponse
    rows: list[CheckRowResponse] = Field(description="Все результаты одним списком")
