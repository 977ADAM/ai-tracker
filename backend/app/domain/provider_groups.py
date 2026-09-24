"""Provider groups and their selectable models, without secrets or I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.core.errors import ValidationError
from app.domain.endpoints import validate_endpoint
from app.domain.limits import MAX_MODEL_LENGTH, MAX_NAME_LENGTH


@dataclass(frozen=True)
class ProviderModel:
    id: str
    model: str
    name: str

    def metadata(self) -> dict[str, str]:
        return {"id": self.id, "model": self.model, "name": self.name}


@dataclass(frozen=True)
class ProviderGroup:
    id: str
    name: str
    endpoint: str
    models: tuple[ProviderModel, ...]
    kind: str = "openai"

    def metadata(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "kind": self.kind,
            "endpoint": self.endpoint, "models": [model.metadata() for model in self.models],
        }


def _short_text(value: object, limit: int, message: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
        raise ValidationError(message)
    return value.strip()


def build_group(
    payload: object,
    previous: ProviderGroup | None = None,
    used_model_ids: set[str] | None = None,
) -> ProviderGroup:
    """Validate one write and preserve IDs for its existing model rows."""
    if not isinstance(payload, dict):
        raise ValidationError("Некорректные настройки провайдера")
    name = _short_text(payload.get("name"), MAX_NAME_LENGTH, "Укажите название до 100 символов")
    endpoint = validate_endpoint(payload.get("endpoint"))
    raw_models = payload.get("models")
    if not isinstance(raw_models, list) or not raw_models or len(raw_models) > 50:
        raise ValidationError("Добавьте от 1 до 50 моделей")
    reserved = used_model_ids or set()
    previous_ids = {model.id for model in previous.models} if previous else set()
    seen: set[str] = set()
    models: list[ProviderModel] = []
    for raw in raw_models:
        if not isinstance(raw, dict):
            raise ValidationError("Некорректная модель")
        identifier = raw.get("id") or str(uuid4())
        if not isinstance(identifier, str) or not identifier or len(identifier) > 64:
            raise ValidationError("Некорректный ID модели")
        if (raw.get("id") and identifier not in previous_ids) or identifier in seen or identifier in reserved:
            raise ValidationError("Повторяющийся или неизвестный ID модели")
        seen.add(identifier)
        models.append(ProviderModel(
            id=identifier,
            model=_short_text(raw.get("model"), MAX_MODEL_LENGTH, "Укажите ID модели до 100 символов"),
            name=_short_text(raw.get("name"), MAX_NAME_LENGTH, "Укажите название модели до 100 символов"),
        ))
    return ProviderGroup(id=previous.id if previous else str(uuid4()), name=name, endpoint=endpoint,
                         models=tuple(models))
