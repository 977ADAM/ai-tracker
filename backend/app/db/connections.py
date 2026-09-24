"""Metadata persistence in `providers.json` plus key access through the credential store."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.core.config import ConnectionPreset
from app.core.errors import ConfigurationError, StorageError
from app.db.secrets import SecretStore
from app.domain.connections import connection_from_preset
from app.domain.models import Connection
from app.domain.provider_groups import ProviderGroup, ProviderModel

CUSTOM_KEY = "custom"
PRESET_OVERRIDES_KEY = "presets"
METADATA_FILE = "providers.json"
GROUPS_KEY = "groups"
CURRENT_VERSION = 2


class ConnectionRepository:
    """Stores non-secret metadata on disk and API keys in the credential store.

    A key is never written to `providers.json`, never returned to a caller, and
    never included in an error message.
    """

    def __init__(
        self,
        config_dir: Path,
        secrets: SecretStore,
        *,
        presets: Iterable[ConnectionPreset] = (),
        env_api_key: Callable[[str], str | None] | None = None,
        service_name: str = "ai-tracker",
    ) -> None:
        self.config_dir = Path(config_dir)
        self.path = self.config_dir / METADATA_FILE
        self.secrets = secrets
        self.presets = tuple(presets)
        self.service_name = service_name
        self._env_api_key = env_api_key or (lambda _connection_id: None)

    # -- metadata ---------------------------------------------------------

    def all(self) -> list[Connection]:
        data = self._read()
        overrides = data[PRESET_OVERRIDES_KEY]
        connections = [self._apply_override(self._preset_connection(preset), overrides.get(preset.id))
                       for preset in self.presets]
        if data.get("version") == CURRENT_VERSION:
            for group in self.groups():
                connections.extend(
                    Connection(id=model.id, name=f"{group.name} · {model.name}", kind=group.kind,
                               model=model.model, endpoint=group.endpoint)
                    for model in group.models
                )
        else:
            connections.extend(self._custom_connection(item) for item in data[CUSTOM_KEY])
        return [connection for connection in connections if connection is not None]

    def groups(self) -> list[ProviderGroup]:
        data = self._read()
        if data.get("version") == CURRENT_VERSION:
            return [self._group_from_metadata(item) for item in data[GROUPS_KEY]]
        groups: list[ProviderGroup] = []
        for item in data[CUSTOM_KEY]:
            if not isinstance(item, dict) or not all(isinstance(item.get(field), str) and item[field]
                                                      for field in ("id", "name", "model", "endpoint")):
                raise StorageError("Не удалось прочитать настройки подключений")
            groups.append(ProviderGroup(
                id=item["id"], name=item["name"], endpoint=item["endpoint"],
                models=(ProviderModel(id=item["id"], model=item["model"], name=item["model"]),),
            ))
        return groups

    def group(self, group_id: str) -> ProviderGroup | None:
        return next((group for group in self.groups() if group.id == group_id), None)

    def group_key(self, group_id: str) -> str | None:
        return self.key(group_id)

    def save_group(self, group: ProviderGroup, api_key: str | None = None) -> None:
        data = self._read()
        previous_key = self._saved_key(group.id)
        if api_key is not None:
            self._store_key(group.id, api_key)
        try:
            groups = [item for item in self.groups() if item.id != group.id]
            self._write({"version": CURRENT_VERSION, GROUPS_KEY: [item.metadata() for item in (*groups, group)],
                         PRESET_OVERRIDES_KEY: data[PRESET_OVERRIDES_KEY]})
        except StorageError:
            self._restore_key(group.id, previous_key)
            raise

    def delete_group(self, group_id: str) -> None:
        data = self._read()
        previous_key = self._saved_key(group_id)
        if previous_key:
            self._drop_key(group_id)
        try:
            groups = [item for item in self.groups() if item.id != group_id]
            self._write({"version": CURRENT_VERSION, GROUPS_KEY: [item.metadata() for item in groups],
                         PRESET_OVERRIDES_KEY: data[PRESET_OVERRIDES_KEY]})
        except StorageError:
            if previous_key:
                self._restore_key(group_id, previous_key)
            raise

    def find(self, connection_id: str) -> Connection | None:
        return next((item for item in self.all() if item.id == connection_id), None)

    def save(self, connection: Connection, api_key: str | None = None) -> None:
        """Persist metadata and, when a new key is given, the key itself."""
        data = self._read()
        if data.get("version") == CURRENT_VERSION and not connection.preset:
            group = next((item for item in self.groups() if any(model.id == connection.id for model in item.models)), None)
            if group is not None:
                models = tuple(replace(model, model=connection.model) if model.id == connection.id else model
                               for model in group.models)
                self.save_group(replace(group, endpoint=connection.endpoint or group.endpoint, models=models), api_key)
                return
        previous_key = self._saved_key(connection.id)
        if api_key is not None:
            self._store_key(connection.id, api_key)

        updated = self._with_connection(data, connection)
        try:
            self._write(updated)
        except StorageError:
            self._restore_key(connection.id, previous_key)
            raise

    def delete(self, connection_id: str) -> None:
        """Remove a connection and its saved key."""
        data = self._read()
        if data.get("version") == CURRENT_VERSION:
            group = next((item for item in self.groups() if any(model.id == connection_id for model in item.models)), None)
            if group is not None:
                remaining = tuple(model for model in group.models if model.id != connection_id)
                if remaining:
                    self.save_group(replace(group, models=remaining))
                else:
                    self.delete_group(group.id)
                return
        previous_key = self._saved_key(connection_id)
        if previous_key:
            self._drop_key(connection_id)

        updated = self._without_connection(data, connection_id)
        try:
            self._write(updated)
        except StorageError:
            if previous_key:
                self._restore_key(connection_id, previous_key)
            raise

    # -- keys -------------------------------------------------------------

    def key(self, connection_id: str) -> str | None:
        """A saved key wins; otherwise the environment fallback applies."""
        data = self._read()
        if data.get("version") == CURRENT_VERSION:
            group = next((item for item in self.groups() if any(model.id == connection_id for model in item.models)), None)
            if group is not None:
                connection_id = group.id
        try:
            saved = self._saved_key(connection_id)
        except ConfigurationError:
            fallback = self._env_api_key(connection_id)
            if fallback:
                return fallback
            raise
        return saved or self._env_api_key(connection_id)

    def saved_key(self, connection_id: str) -> str | None:
        return self._saved_key(connection_id)

    def _saved_key(self, connection_id: str) -> str | None:
        try:
            return self.secrets.get_password(self.service_name, connection_id)
        except Exception as exc:
            raise ConfigurationError("Системное хранилище ключей недоступно") from exc

    def _store_key(self, connection_id: str, key: str) -> None:
        try:
            self.secrets.set_password(self.service_name, connection_id, key)
        except Exception as exc:
            raise ConfigurationError("Не удалось сохранить ключ в системном хранилище") from exc

    def _drop_key(self, connection_id: str) -> None:
        try:
            self.secrets.delete_password(self.service_name, connection_id)
        except Exception as exc:
            raise ConfigurationError("Не удалось удалить ключ из системного хранилища") from exc

    def _restore_key(self, connection_id: str, previous_key: str | None) -> None:
        # Best effort: the metadata write already failed, so a rollback error
        # must not hide the original, user-readable failure.
        try:
            if previous_key:
                self.secrets.set_password(self.service_name, connection_id, previous_key)
            else:
                self.secrets.delete_password(self.service_name, connection_id)
        except Exception:
            pass

    # -- file I/O ---------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {CUSTOM_KEY: [], PRESET_OVERRIDES_KEY: {}}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("not an object")
        except (OSError, ValueError) as exc:
            raise StorageError("Не удалось прочитать настройки подключений") from exc
        return self._normalize(raw)

    def _normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Return the current layout, absorbing the older top-level preset format."""
        if raw.get("version") == CURRENT_VERSION:
            groups = raw.get(GROUPS_KEY)
            overrides = raw.get(PRESET_OVERRIDES_KEY)
            if not isinstance(groups, list) or not isinstance(overrides, dict):
                raise StorageError("Не удалось прочитать настройки подключений")
            return {"version": CURRENT_VERSION, GROUPS_KEY: groups, PRESET_OVERRIDES_KEY: overrides}
        custom = raw.get(CUSTOM_KEY)
        overrides = raw.get(PRESET_OVERRIDES_KEY)
        normalized: dict[str, Any] = {
            CUSTOM_KEY: list(custom) if isinstance(custom, list) else [],
            PRESET_OVERRIDES_KEY: dict(overrides) if isinstance(overrides, dict) else {},
        }
        for preset in self.presets:
            legacy = raw.get(preset.id)
            if (
                preset.id not in normalized[PRESET_OVERRIDES_KEY]
                and isinstance(legacy, dict)
                and isinstance(legacy.get("scope"), str)
            ):
                normalized[PRESET_OVERRIDES_KEY][preset.id] = {"scope": legacy["scope"]}
        return normalized

    @staticmethod
    def _group_from_metadata(item: object) -> ProviderGroup:
        if not isinstance(item, dict) or not all(isinstance(item.get(field), str) and item[field]
                                                  for field in ("id", "name", "endpoint")):
            raise StorageError("Не удалось прочитать настройки подключений")
        models = item.get("models")
        if not isinstance(models, list) or not models:
            raise StorageError("Не удалось прочитать настройки подключений")
        parsed: list[ProviderModel] = []
        for model in models:
            if not isinstance(model, dict) or not all(isinstance(model.get(field), str) and model[field]
                                                       for field in ("id", "model", "name")):
                raise StorageError("Не удалось прочитать настройки подключений")
            parsed.append(ProviderModel(id=model["id"], model=model["model"], name=model["name"]))
        return ProviderGroup(id=item["id"], name=item["name"], endpoint=item["endpoint"],
                             models=tuple(parsed), kind=item.get("kind", "openai"))

    def _write(self, data: dict[str, Any]) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".providers-", dir=self.config_dir)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise StorageError("Не удалось сохранить настройки подключения") from exc
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    # -- metadata mapping -------------------------------------------------

    def _preset_connection(self, preset: ConnectionPreset) -> Connection:
        return connection_from_preset(preset)

    @staticmethod
    def _apply_override(connection: Connection, override: object) -> Connection:
        if not isinstance(override, dict):
            return connection
        scope = override.get("scope")
        if not isinstance(scope, str):
            return connection
        return replace(connection, scope=scope)

    @staticmethod
    def _custom_connection(item: object) -> Connection | None:
        if not isinstance(item, dict):
            return None
        identifier = item.get("id")
        name = item.get("name")
        model = item.get("model")
        if not all(isinstance(value, str) and value for value in (identifier, name, model)):
            return None
        endpoint = item.get("endpoint")
        return Connection(
            id=identifier,
            name=name,
            kind=item.get("kind", "openai"),
            model=model,
            endpoint=endpoint if isinstance(endpoint, str) else None,
        )

    def _with_connection(self, data: dict[str, Any], connection: Connection) -> dict[str, Any]:
        if connection.preset:
            if connection.scope is None:
                return data
            overrides = dict(data[PRESET_OVERRIDES_KEY])
            if overrides.get(connection.id) == {"scope": connection.scope}:
                return data
            overrides[connection.id] = {"scope": connection.scope}
            return {**data, PRESET_OVERRIDES_KEY: overrides}
        others = [item for item in data[CUSTOM_KEY] if item.get("id") != connection.id]
        return {**data, CUSTOM_KEY: [*others, connection.metadata()]}

    @staticmethod
    def _without_connection(data: dict[str, Any], connection_id: str) -> dict[str, Any]:
        overrides = dict(data[PRESET_OVERRIDES_KEY])
        overrides.pop(connection_id, None)
        return {
            CUSTOM_KEY: [item for item in data[CUSTOM_KEY] if item.get("id") != connection_id],
            PRESET_OVERRIDES_KEY: overrides,
        }
