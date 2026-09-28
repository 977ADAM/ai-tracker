"""Schemas of the deferred Yandex search endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RowStatus = Literal["submitting", "waiting", "found", "absent", "error"]
JobStatus = Literal["pending", "done"]

SEARCH_EXAMPLE = {
    "domain": "example.ru",
    "prompts_text": "Где заказать цветы?",
    "regions": [1, 213],
    "region_targets": [{"region": 1, "engine": "yandex"}, {"region": 213, "engine": "yandex"}],
}


class SearchRequest(BaseModel):
    """Тело запроса на поиск в Яндексе.

    Вопросы передаются списком `prompts` или текстом `prompts_text`, по одному в
    строке. Здесь действует лимит поисковой выдачи: до 400 символов на вопрос,
    тогда как проверка моделей допускает 500.
    """

    model_config = ConfigDict(json_schema_extra={"example": SEARCH_EXAMPLE})

    domain: str = Field(description="Сайт: домен или ссылка http(s); совпадение ищется по хосту")
    prompts: list[str] | None = Field(default=None, description="От 1 до 20 вопросов")
    prompts_text: str | None = Field(
        default=None,
        description="Те же вопросы текстом, по одному в строке; заменяет `prompts`",
    )
    regions: list[int] | None = Field(
        default=None,
        description="От 1 до 5 разных регионов из справочника `/api/search/regions`",
    )
    region_targets: list[dict[str, object]] | None = Field(
        default=None,
        description="Поисковая система для каждого региона; пока поддерживается только yandex",
    )


class SearchRegionResponse(BaseModel):
    """Один регион справочника."""

    id: int = Field(description="Числовой ID региона Яндекса")
    name: str


class SearchCreatedResponse(BaseModel):
    """Ответ на создание задачи: сам поиск идёт в фоне."""

    id: str = Field(description="Непрозрачный идентификатор задачи; живёт, пока открыта страница")
    total: int = Field(description="Число пар «вопрос × регион»")
    status: JobStatus


class SearchResultResponse(BaseModel):
    """Результат одной пары «вопрос × регион»."""

    prompt: str
    region_id: int
    region_name: str
    engine: str = Field(description="Выбранная поисковая система")
    status: RowStatus = Field(
        description="submitting/waiting — ещё считаем, found — сайт в первой десятке, absent — нет, error — запрос не удался"
    )
    position: int | None = Field(description="Место в первой десятке; null, если сайт не найден или была ошибка")
    url: str | None = Field(description="Ссылка на найденную страницу; null, если совпадения нет")
    error: str | None = Field(description="Понятное сообщение об ошибке; у ошибки пара не считается отсутствием сайта")


class SearchSummaryResponse(BaseModel):
    """Счётчики поиска: ошибка никогда не считается отсутствием сайта."""

    successful: int = Field(description="Пары, по которым получен вердикт: найден или отсутствует")
    found: int
    failed: int


class SearchSnapshotResponse(BaseModel):
    """Состояние задачи на момент запроса."""

    id: str
    domain: str = Field(description="Сайт в том виде, в каком его ввёл пользователь")
    regions: list[int] = Field(description="Выбранные регионы в порядке формы")
    total: int
    completed: int = Field(description="Пары, дошедшие до конечного состояния")
    status: JobStatus
    summary: SearchSummaryResponse
    results: list[SearchResultResponse] = Field(description="Пары в порядке «вопрос → регион»")
