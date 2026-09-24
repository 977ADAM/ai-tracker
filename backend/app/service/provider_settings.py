"""Settings use case for custom provider groups."""

from __future__ import annotations

from typing import Any

from app.core.errors import ConfigurationError, StorageError, ValidationError
from app.db.connections import ConnectionRepository
from app.domain.connections import api_key_from_payload
from app.domain.provider_groups import ProviderGroup, build_group


MAX_CONFIGURATION_FILE_BYTES = 256 * 1024


class ProviderSettingsService:
    def __init__(self, repository: ConnectionRepository) -> None:
        self.repository = repository

    def _groups(self) -> list[ProviderGroup]:
        try:
            return self.repository.groups()
        except StorageError as exc:
            raise ConfigurationError(str(exc)) from exc

    def _public(self, group: ProviderGroup) -> dict[str, Any]:
        return {**group.metadata(), "configured": bool(self.repository.group_key(group.id))}

    def list_public(self) -> list[dict[str, Any]]:
        return [self._public(group) for group in self._groups()]

    def save(self, payload: object, group_id: str | None = None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValidationError("Некорректные настройки провайдера")
        groups = self._groups()
        previous = next((group for group in groups if group.id == group_id), None)
        if group_id is not None and previous is None:
            raise ValidationError("Провайдер не найден")
        reserved = {model.id for group in groups if group.id != group_id for model in group.models}
        group = build_group(payload, previous, reserved)
        key = api_key_from_payload(payload)
        try:
            self.repository.save_group(group, key)
        except StorageError as exc:
            raise ConfigurationError(str(exc)) from exc
        return self._public(group)

    def configuration_file(self) -> dict[str, Any]:
        """The on-disk metadata file, exactly as stored. Keys are not in it."""
        path = self.repository.path
        if not path.is_file():
            return {"path": str(path), "exists": False, "content": None}
        try:
            if path.stat().st_size > MAX_CONFIGURATION_FILE_BYTES:
                raise ConfigurationError("Файл конфигурации слишком большой")
            content = path.read_text(encoding="utf-8")
        except ConfigurationError:
            raise
        except (OSError, UnicodeError) as exc:
            raise ConfigurationError("Не удалось прочитать файл конфигурации") from exc
        return {"path": str(path), "exists": True, "content": content}

    def delete(self, group_id: str) -> None:
        if not any(group.id == group_id for group in self._groups()):
            raise ValidationError("Провайдер не найден")
        try:
            self.repository.delete_group(group_id)
        except StorageError as exc:
            raise ConfigurationError(str(exc)) from exc
