"""Connection settings use case: validation, persistence, and the public view."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.errors import ConfigurationError, StorageError, ValidationError
from app.db.connections import ConnectionRepository
from app.domain.connections import (
    api_key_from_payload,
    new_custom_connection,
    public_view,
    updated_custom_connection,
    updated_preset,
)
from app.domain.models import Connection


class ConnectionService:
    """The only way the API touches saved connections."""

    def __init__(self, repository: ConnectionRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def all(self) -> list[Connection]:
        return self.repository.all()

    def find(self, connection_id: str) -> Connection | None:
        return self.repository.find(connection_id)

    def require(self, connection_id: str) -> Connection:
        connection = self.find(connection_id)
        if connection is None:
            raise ValidationError("Подключение не найдено")
        return connection

    def api_key(self, connection_id: str) -> str | None:
        return self.repository.key(connection_id)

    def is_configured(self, connection_id: str) -> bool:
        try:
            return bool(self.repository.key(connection_id))
        except ConfigurationError:
            return False

    def list_public(self) -> list[dict[str, Any]]:
        return [public_view(connection, self.is_configured(connection.id)) for connection in self.all()]

    def save(self, payload: object, connection_id: str | None = None) -> dict[str, Any]:
        """Create a connection, or update an existing one, together with its key."""
        if not isinstance(payload, dict):
            raise ValidationError("Некорректные настройки подключения")
        key = api_key_from_payload(payload)
        try:
            connection = self._build(payload, connection_id)
            self.repository.save(connection, key)
        except StorageError as exc:
            raise ConfigurationError(str(exc)) from exc
        return public_view(connection, self.is_configured(connection.id))

    def delete(self, connection_id: str) -> None:
        try:
            self.require(connection_id)
            self.repository.delete(connection_id)
        except StorageError as exc:
            raise ConfigurationError(str(exc)) from exc

    def _build(self, payload: dict[str, Any], connection_id: str | None) -> Connection:
        if connection_id is None:
            return new_custom_connection(payload)
        previous = self.require(connection_id)
        if previous.preset:
            return updated_preset(previous, payload, self.settings.default_scope)
        return updated_custom_connection(previous, payload)
