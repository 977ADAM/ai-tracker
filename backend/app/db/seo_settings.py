"""Private SEO service-LLM metadata with a separate keyring credential override."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from app.core.errors import ConfigurationError, StorageError, ValidationError
from app.db.secrets import SecretStore
from app.domain.seo_settings import SeoSettings, validate_seo_endpoint

METADATA_FILE = "seo-settings.json"
KEYRING_ACCOUNT = "seo-llm"
FIELDS = ("endpoint", "model")

READ_ERROR = "Не удалось прочитать настройки SEO-анализа"
WRITE_ERROR = "Не удалось сохранить настройки SEO-анализа"


class SeoSettingsRepository:
    """Resolve UI overrides over environment values and persist them safely."""

    def __init__(
        self,
        config_dir: Path,
        secrets: SecretStore,
        *,
        env_endpoint: str | None,
        env_model: str | None,
        env_api_key: str | None,
        service_name: str,
    ) -> None:
        self.config_dir = Path(config_dir)
        self.path = self.config_dir / METADATA_FILE
        self.secrets = secrets
        self.env_endpoint = env_endpoint
        self.env_model = env_model
        self.env_api_key = env_api_key
        self.service_name = service_name

    def load(self) -> SeoSettings:
        return self._resolve(self._read(), self._saved_key())

    def update(self, payload: Mapping[str, object]) -> SeoSettings:
        """Apply supplied fields; empty strings leave saved values intact."""
        self._validate(payload)
        previous = self._read()
        old_key = self._saved_key()
        updated = dict(previous)
        for name in FIELDS:
            value = payload.get(name)
            if isinstance(value, str) and value.strip():
                updated[name] = value.strip()
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

    def reset_credentials(self) -> SeoSettings:
        """Delete the UI overrides, retaining the environment fallbacks."""
        previous = self._read()
        old_key = self._saved_key()
        if old_key is None and not previous:
            return self._resolve(previous, old_key)
        if old_key is not None:
            self._delete_key()
        try:
            self._write({})
        except StorageError as storage_error:
            if old_key is not None:
                try:
                    self._restore_key(old_key)
                except ConfigurationError as rollback_error:
                    raise rollback_error from storage_error
            raise
        return self._resolve({}, None)

    def _resolve(self, data: dict[str, object], saved_key: str | None) -> SeoSettings:
        return SeoSettings.resolve(
            ui_endpoint=data.get("endpoint"),  # type: ignore[arg-type]
            ui_model=data.get("model"),  # type: ignore[arg-type]
            ui_api_key=saved_key,
            env_endpoint=self.env_endpoint,
            env_model=self.env_model,
            env_api_key=self.env_api_key,
        )

    @staticmethod
    def _validate(payload: Mapping[str, object]) -> None:
        if set(payload) - {*FIELDS, "api_key"}:
            raise ValidationError("Неизвестное поле настроек SEO-анализа")
        for name in (*FIELDS, "api_key"):
            if name in payload and not isinstance(payload[name], str):
                raise ValidationError("Некорректные настройки служебной LLM")
        endpoint = payload.get("endpoint")
        if isinstance(endpoint, str) and endpoint.strip():
            validate_seo_endpoint(endpoint.strip())

    def _read(self) -> dict[str, object]:
        try:
            if not self.path.exists():
                return {}
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StorageError(READ_ERROR) from exc
        if not isinstance(raw, dict):
            raise StorageError(READ_ERROR)
        data: dict[str, object] = {}
        for name in FIELDS:
            if name in raw:
                value = raw[name]
                if not isinstance(value, str) or not value.strip():
                    raise StorageError(READ_ERROR)
                data[name] = value.strip()
        endpoint = data.get("endpoint")
        if isinstance(endpoint, str):
            try:
                validate_seo_endpoint(endpoint)
            except ValidationError as exc:
                raise StorageError(READ_ERROR) from exc
        return data

    def _write(self, data: dict[str, object]) -> None:
        temporary: str | None = None
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".seo-settings-", dir=self.config_dir)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise StorageError(WRITE_ERROR) from exc
        finally:
            write_failed = sys.exc_info()[0] is not None
            if temporary is not None and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError as exc:
                    if not write_failed:
                        raise StorageError("Не удалось очистить временные настройки SEO-анализа") from exc

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
