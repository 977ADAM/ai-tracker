"""Rules for connection payloads and for the public connection view."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.config import ConnectionPreset
from app.core.errors import ValidationError
from app.domain.endpoints import validate_endpoint
from app.domain.limits import (
    MAX_API_KEY_LENGTH,
    MAX_MODEL_LENGTH,
    MAX_NAME_LENGTH,
    SCOPE_VALUES,
)
from app.domain.models import KIND_GIGACHAT, KIND_OPENAI, Connection

PRESET_SCOPE_FIELD = "scope"

CUSTOM_FIELDS = ("name", "endpoint", "model", "api_key")
NEW_PROVIDER_FIELDS = ["name", "endpoint", "model", "api_key"]


def connection_from_preset(preset: ConnectionPreset) -> Connection:
    return Connection(
        id=preset.id,
        name=preset.name,
        kind=preset.kind,
        model=preset.model,
        endpoint=preset.endpoint,
        scope=preset.scope,
        thinking_disabled=preset.thinking_disabled,
        preset=True,
    )


def editable_fields(connection: Connection) -> list[str]:
    if connection.kind == KIND_GIGACHAT:
        return [PRESET_SCOPE_FIELD, "api_key"]
    if connection.preset:
        return ["api_key"]
    return list(CUSTOM_FIELDS)


def can_reset(connection: Connection) -> bool:
    """A built-in template keeps its metadata forever, so only its key can be reset."""
    return connection.preset


def can_delete(connection: Connection) -> bool:
    return not connection.preset


def _delete_copy(connection: Connection) -> dict[str, str]:
    if connection.preset:
        return {
            "delete_label": "Сбросить ключ",
            "delete_prompt": (
                f"Удалить сохранённый ключ «{connection.name}»? "
                "Ключ из переменной среды может сохранить подключение активным."
            ),
            "delete_success": "Сохранённый ключ сброшен",
        }
    return {
        "delete_label": "Удалить",
        "delete_prompt": f"Удалить подключение «{connection.name}» и его ключ?",
        "delete_success": "Подключение удалено",
    }


def public_view(connection: Connection, configured: bool) -> dict[str, Any]:
    """The only connection shape the API is allowed to expose. It never holds a key."""
    view: dict[str, Any] = {
        "id": connection.id,
        "name": connection.name,
        "kind": connection.kind,
        "endpoint": connection.endpoint,
        "model": connection.model,
        "configured": configured,
        "editable_fields": editable_fields(connection),
        "can_reset": can_reset(connection),
        "can_delete": can_delete(connection),
        "status_label": "Готово к проверке" if configured else "Нужен API-ключ",
    }
    if connection.scope is not None:
        view["scope"] = connection.scope
    view.update(_delete_copy(connection))
    return view


def api_key_from_payload(payload: dict[str, Any]) -> str | None:
    """Validate the optional key field. A blank key means "keep the saved key"."""
    if "api_key" not in payload:
        return None
    key = payload["api_key"]
    if key is None:
        return None
    if not isinstance(key, str) or len(key) > MAX_API_KEY_LENGTH:
        raise ValidationError("Некорректный API-ключ")
    return key.strip() or None


def _validated_name(model: Any) -> str:
    if not isinstance(model, str) or not 1 <= len(model.strip()) <= MAX_NAME_LENGTH:
        raise ValidationError("Укажите название до 100 символов")
    return model.strip()


def _validated_model(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= MAX_MODEL_LENGTH:
        raise ValidationError("Укажите модель до 100 символов")
    return value.strip()


def new_custom_connection(payload: dict[str, Any], connection_id: str | None = None) -> Connection:
    """Build a user-created OpenAI-compatible connection from a create request."""
    kind = payload.get("kind", KIND_OPENAI)
    if kind != KIND_OPENAI:
        raise ValidationError("Поддерживается только OpenAI-совместимый API")
    return Connection(
        id=connection_id or str(uuid4()),
        name=_validated_name(payload.get("name")),
        kind=KIND_OPENAI,
        endpoint=validate_endpoint(payload.get("endpoint")),
        model=_validated_model(payload.get("model")),
    )


def updated_custom_connection(previous: Connection, payload: dict[str, Any]) -> Connection:
    """Merge an edit request into a saved custom connection."""
    merged = {**previous.metadata(), **payload}
    kind = merged.get("kind", KIND_OPENAI)
    if kind != KIND_OPENAI:
        raise ValidationError("Поддерживается только OpenAI-совместимый API")
    return Connection(
        id=previous.id,
        name=_validated_name(merged.get("name")),
        kind=KIND_OPENAI,
        endpoint=validate_endpoint(merged.get("endpoint")),
        model=_validated_model(merged.get("model")),
    )


def updated_preset(previous: Connection, payload: dict[str, Any], default_scope: str) -> Connection:
    """Apply the only two fields a built-in template may change: its key and its scope."""
    allowed = {PRESET_SCOPE_FIELD, "api_key"} if previous.kind == KIND_GIGACHAT else {"api_key"}
    if any(field not in allowed for field in payload):
        raise ValidationError("У встроенного подключения можно изменить только ключ и область доступа")
    scope = previous.scope or default_scope
    if PRESET_SCOPE_FIELD in payload:
        scope = payload[PRESET_SCOPE_FIELD]
        if scope not in SCOPE_VALUES:
            raise ValidationError("Некорректная область доступа GigaChat")
    return Connection(
        id=previous.id,
        name=previous.name,
        kind=previous.kind,
        model=previous.model,
        endpoint=previous.endpoint,
        scope=scope,
        thinking_disabled=previous.thinking_disabled,
        preset=True,
    )
