"""Local provider metadata and operating-system credential storage."""

import ipaddress
import json
import os
from pathlib import Path
import tempfile
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4


SERVICE = "ai-tracker"
PRESETS = {
    "gigachat": {"id": "gigachat", "name": "GigaChat", "kind": "gigachat", "endpoint": None, "model": "GigaChat", "scope": "GIGACHAT_API_PERS"},
    "deepseek": {"id": "deepseek", "name": "DeepSeek", "kind": "openai", "endpoint": "https://api.deepseek.com/chat/completions", "model": "deepseek-flash"},
}
SCOPE_OPTIONS = [
    {"value": "GIGACHAT_API_PERS", "label": "Персональный"},
    {"value": "GIGACHAT_API_B2B", "label": "Бизнес"},
    {"value": "GIGACHAT_API_CORP", "label": "Корпоративный"},
]


class ConnectionError(ValueError):
    """A safe, user-readable connection configuration error."""


class SecretStore(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


class KeyringSecrets:
    def get_password(self, service: str, username: str) -> str | None:
        import keyring
        return keyring.get_password(service, username)

    def set_password(self, service: str, username: str, password: str) -> None:
        import keyring
        keyring.set_password(service, username, password)

    def delete_password(self, service: str, username: str) -> None:
        import keyring
        keyring.delete_password(service, username)


def validate_endpoint(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ConnectionError("Укажите HTTPS-адрес Chat Completions API")
    try:
        url = urlsplit(value)
        hostname = url.hostname
        port = url.port
    except ValueError as exc:
        raise ConnectionError("Некорректный адрес API") from exc
    if (url.scheme != "https" or not hostname or port is not None or url.username or url.password
            or url.query or url.fragment or not url.path.endswith("/chat/completions")
            or "//" in url.path or "\\" in value or any(ch.isspace() for ch in value)):
        raise ConnectionError("Нужен публичный HTTPS-адрес, заканчивающийся на /chat/completions")
    host = hostname.rstrip(".").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ConnectionError("IP-адрес нельзя использовать для подключения")
    labels = host.split(".")
    if (len(labels) < 2 or any(not label or not all(c.isascii() and (c.isalnum() or c == "-") for c in label) or label.startswith("-") or label.endswith("-") for label in labels)
            or host.endswith((".local", ".internal", ".localhost", ".test", ".invalid"))
            or host in {"localhost", "local"} or url.netloc.endswith(".")):
        raise ConnectionError("Укажите публичный домен API")
    return value


class ConnectionStore:
    def __init__(self, config_dir: Path, secrets: SecretStore):
        self.config_dir = Path(config_dir)
        self.path = self.config_dir / "providers.json"
        self.secrets = secrets

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (OSError, ValueError) as exc:
            raise ConnectionError("Не удалось прочитать настройки подключений") from exc

    def _write(self, data: dict) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".providers-", dir=self.config_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def _saved_key(self, connection_id: str) -> str | None:
        try:
            return self.secrets.get_password(SERVICE, connection_id)
        except Exception as exc:
            raise ConnectionError("Системное хранилище ключей недоступно") from exc

    def get_key(self, connection_id: str) -> str | None:
        try:
            saved = self._saved_key(connection_id)
        except ConnectionError:
            if connection_id == "gigachat" and os.getenv("GIGACHAT_AUTH_KEY"):
                return os.getenv("GIGACHAT_AUTH_KEY")
            if connection_id == "deepseek" and os.getenv("DEEPSEEK_API_KEY"):
                return os.getenv("DEEPSEEK_API_KEY")
            raise
        if saved:
            return saved
        if connection_id == "gigachat":
            return os.getenv("GIGACHAT_AUTH_KEY") or None
        if connection_id == "deepseek":
            return os.getenv("DEEPSEEK_API_KEY") or None
        return None

    def _all(self) -> list[dict]:
        data = self._read()
        presets = [dict(value, **data.get(key, {})) for key, value in PRESETS.items()]
        return presets + data.get("custom", [])

    def list_connections(self) -> list[dict]:
        result = []
        for item in self._all():
            try:
                configured = bool(self.get_key(item["id"]))
            except ConnectionError:
                configured = False
            preset = item["id"] in PRESETS
            fields = ["scope", "api_key"] if item["id"] == "gigachat" else ["api_key"] if preset else ["name", "endpoint", "model", "api_key"]
            result.append(dict(item, configured=configured, editable_fields=fields, can_reset=preset, can_delete=not preset,
                               status_label="Готово к проверке" if configured else "Нужен API-ключ",
                               delete_label="Сбросить ключ" if preset else "Удалить",
                               delete_prompt=(f"Удалить сохранённый ключ «{item['name']}»? Ключ из переменной среды может сохранить подключение активным." if preset
                                              else f"Удалить подключение «{item['name']}» и его ключ?"),
                               delete_success="Сохранённый ключ сброшен" if preset else "Подключение удалено"))
        return result

    def save_connection(self, payload: dict, connection_id: str | None = None) -> dict:
        if not isinstance(payload, dict):
            raise ConnectionError("Некорректные настройки подключения")
        data = self._read()
        previous = next((item for item in self._all() if item["id"] == connection_id), None) if connection_id else None
        if connection_id and previous is None:
            raise ConnectionError("Подключение не найдено")
        if connection_id in PRESETS:
            allowed = {"api_key", "scope"} if connection_id == "gigachat" else {"api_key"}
            if any(key not in allowed for key in payload):
                raise ConnectionError("У встроенного подключения можно изменить только ключ и область доступа")
            updated = dict(previous)
            if "scope" in payload:
                if payload["scope"] not in {option["value"] for option in SCOPE_OPTIONS}:
                    raise ConnectionError("Некорректная область доступа GigaChat")
                updated["scope"] = payload["scope"]
            if "scope" in payload:
                data[connection_id] = {"scope": updated["scope"]}
        else:
            merged = dict(previous or {}) | payload
            name, model = merged.get("name"), merged.get("model")
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
                raise ConnectionError("Укажите название до 100 символов")
            if not isinstance(model, str) or not 1 <= len(model.strip()) <= 100:
                raise ConnectionError("Укажите модель до 100 символов")
            if merged.get("kind", "openai") != "openai":
                raise ConnectionError("Поддерживается только OpenAI-совместимый API")
            endpoint = validate_endpoint(merged.get("endpoint"))
            updated = {"id": connection_id or str(uuid4()), "name": name.strip(), "kind": "openai", "endpoint": endpoint, "model": model.strip()}
            customs = data.get("custom", [])
            data["custom"] = [item for item in customs if item["id"] != connection_id] + [updated]
        key = payload.get("api_key")
        if key is not None and (not isinstance(key, str) or len(key) > 10000):
            raise ConnectionError("Некорректный API-ключ")
        old_key = self._saved_key(updated["id"])
        changed_key = isinstance(key, str) and bool(key.strip())
        if changed_key:
            try:
                self.secrets.set_password(SERVICE, updated["id"], key.strip())
            except Exception as exc:
                raise ConnectionError("Не удалось сохранить ключ в системном хранилище") from exc
        try:
            self._write(data)
        except OSError as exc:
            if changed_key:
                try:
                    if old_key:
                        self.secrets.set_password(SERVICE, updated["id"], old_key)
                    else:
                        self.secrets.delete_password(SERVICE, updated["id"])
                except Exception:
                    pass
            raise ConnectionError("Не удалось сохранить настройки подключения") from exc
        return dict(updated, configured=bool(self.get_key(updated["id"])))

    def delete_connection(self, connection_id: str) -> None:
        data = self._read()
        if connection_id not in [item["id"] for item in self._all()]:
            raise ConnectionError("Подключение не найдено")
        old_key = self._saved_key(connection_id)
        if old_key:
            try:
                self.secrets.delete_password(SERVICE, connection_id)
            except Exception as exc:
                raise ConnectionError("Не удалось удалить ключ из системного хранилища") from exc
        if connection_id in PRESETS:
            data.pop(connection_id, None)
        else:
            data["custom"] = [item for item in data.get("custom", []) if item["id"] != connection_id]
        try:
            self._write(data)
        except OSError as exc:
            if old_key:
                try:
                    self.secrets.set_password(SERVICE, connection_id, old_key)
                except Exception:
                    pass
            raise ConnectionError("Не удалось удалить подключение") from exc
