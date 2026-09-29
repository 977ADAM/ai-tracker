"""Runtime configuration: paths, host guard, presets, and environment fallbacks."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "ai-tracker"
DEFAULT_SERVICE_NAME = "ai-tracker"
DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1")
DEFAULT_SCOPE = "GIGACHAT_API_PERS"

# The host guard of the API. The default keeps the app reachable only from the
# machine it runs on; a deployment lists every name it is reached by, comma
# separated: `AI_TRACKER_ALLOWED_HOSTS=localhost,127.0.0.1,backend`.
ALLOWED_HOSTS_VARIABLE = "AI_TRACKER_ALLOWED_HOSTS"

# `.env` lives in the repository root, one level above `backend/`.
ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

# Yandex search credentials. The prefixed names are the documented ones; the
# short legacy names keep working for an existing local `.env`.
YANDEX_SEARCH_API_KEY_VARIABLES = ("YANDEX_SEARCH_API_KEY", "API_KEY")
YANDEX_SEARCH_FOLDER_ID_VARIABLES = ("YANDEX_SEARCH_FOLDER_ID", "FOLDER_ID")

# SEO service LLM. These are only fallbacks: a value saved in the settings
# screen always wins over the environment.
SEO_LLM_ENDPOINT_VARIABLES = ("SEO_LLM_ENDPOINT",)
SEO_LLM_MODEL_VARIABLES = ("SEO_LLM_MODEL",)
SEO_LLM_API_KEY_VARIABLES = ("SEO_LLM_API_KEY",)

# Environment variable that may hold a key per saved connection ID. It is only a
# fallback: a key saved in the settings screen always wins.
DEFAULT_ENV_API_KEYS = {
    "gigachat": "GIGACHAT_AUTH_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def load_env_file(path: Path = ROOT_ENV_FILE) -> None:
    """Read the root `.env` without overriding variables already in the environment."""
    load_dotenv(path, override=False)


def first_value(source: Mapping[str, str], names: Iterable[str]) -> str | None:
    """Return the first non-empty value among `names`, ignoring blank entries."""
    for name in names:
        value = source.get(name)
        if value and value.strip():
            return value.strip()
    return None


def parse_allowed_hosts(value: str | None) -> tuple[str, ...]:
    """Split the comma-separated host guard; a blank value keeps the default.

    `TrustedHostMiddleware` compares the host without its port, so `backend`
    covers a call to `http://backend:8000` made from another container.
    """
    if value is None:
        return DEFAULT_ALLOWED_HOSTS
    hosts = tuple(part.strip() for part in value.split(",") if part.strip())
    return hosts or DEFAULT_ALLOWED_HOSTS

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
    yandex_search_api_key: str | None = None
    yandex_search_folder_id: str | None = None
    seo_llm_endpoint: str | None = None
    seo_llm_model: str | None = None
    seo_llm_api_key: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        return cls(
            config_dir=Path(source.get("AI_TRACKER_CONFIG_DIR") or DEFAULT_CONFIG_DIR),
            allowed_hosts=parse_allowed_hosts(source.get(ALLOWED_HOSTS_VARIABLE)),
            default_scope=source.get("GIGACHAT_SCOPE") or DEFAULT_SCOPE,
            yandex_search_api_key=first_value(source, YANDEX_SEARCH_API_KEY_VARIABLES),
            yandex_search_folder_id=first_value(source, YANDEX_SEARCH_FOLDER_ID_VARIABLES),
            seo_llm_endpoint=first_value(source, SEO_LLM_ENDPOINT_VARIABLES),
            seo_llm_model=first_value(source, SEO_LLM_MODEL_VARIABLES),
            seo_llm_api_key=first_value(source, SEO_LLM_API_KEY_VARIABLES),
        )

    @property
    def has_yandex_search_credentials(self) -> bool:
        """Both halves of the Yandex Search API credentials are present."""
        return bool(self.yandex_search_api_key and self.yandex_search_folder_id)

    @property
    def has_seo_llm_credentials(self) -> bool:
        """The SEO service LLM can be configured from the environment alone."""
        return bool(self.seo_llm_endpoint and self.seo_llm_model and self.seo_llm_api_key)

    def with_presets(self, presets: Iterable[ConnectionPreset]) -> Settings:
        return replace(self, presets=tuple(presets))

    def preset(self, connection_id: str) -> ConnectionPreset | None:
        return next((preset for preset in self.presets if preset.id == connection_id), None)

    def env_api_key(self, connection_id: str) -> str | None:
        variable = self.env_api_keys.get(connection_id)
        if not variable:
            return None
        return os.getenv(variable) or None
