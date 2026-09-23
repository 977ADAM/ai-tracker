"""Shapes shared by every endpoint."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

ERROR_EXAMPLE = {"detail": "Выбрано неизвестное подключение"}


class ErrorResponse(BaseModel):
    """Тело ошибки любого эндпоинта.

    400 — некорректный запрос, настройки или неизвестное подключение,
    503 — недоступное локальное хранилище, 500 — непредвиденный сбой.
    """

    model_config = ConfigDict(json_schema_extra={"example": ERROR_EXAMPLE})

    detail: str = Field(description="Понятный пользователю текст без внутренних деталей")
