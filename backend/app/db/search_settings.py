"""Private Yandex metadata with a separate keyring credential override."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from app.core.errors import ConfigurationError, StorageError, ValidationError
from app.db.secrets import SecretStore
from app.domain.search_settings import SearchSettings

METADATA_FILE = "search-settings.json"
KEYRING_ACCOUNT = "yandex-search"


class SearchSettingsRepository:
    """Resolve UI overrides over environment credentials and persist them safely."""

    def __init__(
        self,
        config_dir: Path,
        secrets: SecretStore,
        *,
        env_api_key: str | None,
        env_folder_id: str | None,
        service_name: str,
    ) -> None:
        self.config_dir = Path(config_dir)
        self.path = self.config_dir / METADATA_FILE
        self.secrets = secrets
        self.env_api_key = env_api_key
        self.env_folder_id = env_folder_id
        self.service_name = service_name

    def load(self) -> SearchSettings:
        data = self._read()
        return self._resolve(data, self._saved_key())

    def update(self, payload: Mapping[str, object]) -> SearchSettings:
        """Apply supplied fields; empty credential strings leave overrides intact."""
        self._validate(payload)
        previous = self._read()
        old_key = self._saved_key()
        updated = dict(previous)
        if "enabled" in payload:
            updated["enabled"] = payload["enabled"]
        if isinstance(payload.get("folder_id"), str) and payload["folder_id"].strip():
            updated["folder_id"] = payload["folder_id"].strip()
        new_key = payload.get("api_key")
        write_key = isinstance(new_key, str) and bool(new_key.strip())
        if updated == previous and not write_key:
            return self._resolve(previous, old_key)

        saved_key = new_key.strip() if write_key else old_key
        if write_key:
            self._set_key(saved_key)
        try:
            if updated != previous:
                self._write(updated)
        except StorageError as storage_error:
            if write_key:
                try:
                    self._restore_key(old_key)
                except ConfigurationError as rollback_error:
                    raise rollback_error from storage_error
            raise
        return self._resolve(updated, saved_key)

    def reset_credentials(self) -> SearchSettings:
        """Delete both UI overrides, retaining enabled and environment fallbacks."""
        previous = self._read()
        old_key = self._saved_key()
        updated = {name: value for name, value in previous.items() if name != "folder_id"}
        if old_key is None and updated == previous:
            return self._resolve(previous, old_key)
        if old_key is not None:
            self._delete_key()
        try:
            if updated != previous:
                self._write(updated)
        except StorageError as storage_error:
            if old_key is not None:
                try:
                    self._restore_key(old_key)
                except ConfigurationError as rollback_error:
                    raise rollback_error from storage_error
            raise
        return self._resolve(updated, None)

    def _resolve(self, data: dict[str, object], saved_key: str | None) -> SearchSettings:
        return SearchSettings.resolve(
            enabled=data.get("enabled"),  # type: ignore[arg-type]
            ui_api_key=saved_key,
            ui_folder_id=data.get("folder_id"),  # type: ignore[arg-type]
            env_api_key=self.env_api_key,
            env_folder_id=self.env_folder_id,
        )

    @staticmethod
    def _validate(payload: Mapping[str, object]) -> None:
        if set(payload) - {"enabled", "api_key", "folder_id"}:
            raise ValidationError("Неизвестное поле настроек поиска")
        if "enabled" in payload and not isinstance(payload["enabled"], bool):
            raise ValidationError("Некорректное значение доступности поиска")
        for name in ("api_key", "folder_id"):
            if name in payload and not isinstance(payload[name], str):
                raise ValidationError("Некорректные учётные данные поиска")

    def _read(self) -> dict[str, object]:
        try:
            if not self.path.exists():
                return {}
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StorageError("Не удалось прочитать настройки поиска") from exc
        if not isinstance(raw, dict):
            raise StorageError("Не удалось прочитать настройки поиска")
        if "enabled" in raw and not isinstance(raw["enabled"], bool):
            raise StorageError("Не удалось прочитать настройки поиска")
        if "folder_id" in raw and (not isinstance(raw["folder_id"], str) or not raw["folder_id"].strip()):
            raise StorageError("Не удалось прочитать настройки поиска")
        return {name: raw[name] for name in ("enabled", "folder_id") if name in raw}

    def _write(self, data: dict[str, object]) -> None:
        temporary: str | None = None
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".search-settings-", dir=self.config_dir)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise StorageError("Не удалось сохранить настройки поиска") from exc
        finally:
            write_failed = sys.exc_info()[0] is not None
            if temporary is not None and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError as exc:
                    if not write_failed:
                        raise StorageError("Не удалось очистить временные настройки поиска") from exc

    def _saved_key(self) -> str | None:
        try:
            return self.secrets.get_password(self.service_name, KEYRING_ACCOUNT)
        except Exception as exc:
            raise ConfigurationError("Системное хранилище ключей недоступно") from exc

    def _set_key(self, key: str) -> None:
        try:
            self.secrets.set_password(self.service_name, KEYRING_ACCOUNT, key)
        except Exception as exc:
            raise ConfigurationError("Не удалось сохранить ключ в системном хранилище") from exc

    def _delete_key(self) -> None:
        try:
            self.secrets.delete_password(self.service_name, KEYRING_ACCOUNT)
        except Exception as exc:
            raise ConfigurationError("Не удалось удалить ключ из системного хранилища") from exc

    def _restore_key(self, previous: str | None) -> None:
        try:
            if previous is None:
                self.secrets.delete_password(self.service_name, KEYRING_ACCOUNT)
            else:
                self.secrets.set_password(self.service_name, KEYRING_ACCOUNT, previous)
        except Exception as exc:
            raise ConfigurationError("Не удалось восстановить ключ в системном хранилище") from exc
