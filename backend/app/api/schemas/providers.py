"""Schemas of the connection settings endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import KIND_OPENAI

PROVIDER_EXAMPLE = {
    "id": "5fd2833f-d515-4611-ac60-9a6de66a049d",
    "name": "DeepSeek",
    "kind": KIND_OPENAI,
    "endpoint": "https://api.deepseek.com/chat/completions",
    "model": "deepseek-chat",
    "configured": True,
    "editable_fields": ["name", "endpoint", "model", "api_key"],
    "can_reset": False,
    "can_delete": True,
    "status_label": "Готово к проверке",
    "delete_label": "Удалить",
    "delete_prompt": "Удалить подключение «DeepSeek» и его ключ?",
    "delete_success": "Подключение удалено",
}


class ProviderWriteRequest(BaseModel):
    """Тело создания подключения и его изменения.

    Новое подключение задаёт `name`, `endpoint`, `model` и `api_key`.
    Встроенное подключение принимает только `api_key`; лишнее поле отклоняет
    доменное правило, поэтому неизвестные поля не отбрасываются здесь.
    """

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "name": "DeepSeek",
                "kind": KIND_OPENAI,
                "endpoint": "https://api.deepseek.com/chat/completions",
                "model": "deepseek-chat",
                "api_key": "sk-...",
            }
        },
    )

    name: str | None = Field(default=None, description="Название подключения, до 100 символов")
    kind: str | None = Field(default=None, description=f"Тип адаптера: {KIND_OPENAI}")
    endpoint: str | None = Field(
        default=None,
        description="Публичный HTTPS-адрес, заканчивающийся на /chat/completions",
    )
    model: str | None = Field(default=None, description="Идентификатор модели, до 100 символов")
    api_key: str | None = Field(
        default=None,
        description="API-ключ. Пустая строка или отсутствие поля сохраняют прежний ключ",
    )


class ProviderResponse(BaseModel):
    """Одно подключение в том виде, в каком его видит браузер.

    Ключ не возвращается никогда: он лежит в системном хранилище и доступен
    только серверной части.
    """

    model_config = ConfigDict(json_schema_extra={"example": PROVIDER_EXAMPLE})

    id: str
    name: str
    kind: str
    endpoint: str | None = Field(description="Адрес API; у встроенных подключений может отсутствовать")
    model: str
    answer_mode: str = "text"
    configured: bool = Field(description="Найден ли API-ключ: сохранённый или из переменной среды")
    editable_fields: list[str] = Field(description="Поля, которые можно менять у этого подключения")
    can_reset: bool = Field(description="Встроенное подключение: ключ можно сбросить, но не удалить")
    can_delete: bool
    status_label: str
    delete_label: str
    delete_prompt: str
    delete_success: str


class DeletedResponse(BaseModel):
    """Ответ на удаление подключения."""

    deleted: bool
