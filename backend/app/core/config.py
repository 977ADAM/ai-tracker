"""Runtime configuration: paths, host guard, presets, and environment fallbacks."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "ai-tracker"
DEFAULT_SERVICE_NAME = "ai-tracker"
DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1")
DEFAULT_SCOPE = "GIGACHAT_API_PERS"

# Environment variable that may hold a key per saved connection ID. It is only a
# fallback: a key saved in the settings screen always wins.
DEFAULT_ENV_API_KEYS = {
    "gigachat": "GIGACHAT_AUTH_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

# Built-in connection templates. Empty means the app ships no preconfigured
# connections and every connection is created by the user in the settings
# screen. Fill this tuple to ship templates again; the preset code paths stay
# covered by the test suite, which injects its own Settings.
BUILTIN_PRESETS: tuple[ConnectionPreset, ...] = ()


@dataclass(frozen=True)
class ConnectionPreset:
    """A connection template that ships with the app instead of being created by the user."""

    id: str
    name: str
    kind: str
    model: str
    endpoint: str | None = None
    scope: str | None = None
    thinking_disabled: bool = False


@dataclass(frozen=True)
class Settings:
    """Everything the app needs from its environment, resolved once at startup."""

    config_dir: Path = DEFAULT_CONFIG_DIR
    service_name: str = DEFAULT_SERVICE_NAME
    allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS
    default_scope: str = DEFAULT_SCOPE
    env_api_keys: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_ENV_API_KEYS))
    presets: tuple[ConnectionPreset, ...] = BUILTIN_PRESETS

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        return cls(
            config_dir=Path(source.get("AI_TRACKER_CONFIG_DIR") or DEFAULT_CONFIG_DIR),
            default_scope=source.get("GIGACHAT_SCOPE") or DEFAULT_SCOPE,
        )

    def with_presets(self, presets: Iterable[ConnectionPreset]) -> Settings:
        return replace(self, presets=tuple(presets))

    def preset(self, connection_id: str) -> ConnectionPreset | None:
        return next((preset for preset in self.presets if preset.id == connection_id), None)

    def env_api_key(self, connection_id: str) -> str | None:
        variable = self.env_api_keys.get(connection_id)
        if not variable:
            return None
        return os.getenv(variable) or None
