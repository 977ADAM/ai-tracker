"""Resolved Yandex Search settings, including the origin of each credential."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CredentialSource = Literal["ui", "env", "none"]


def _credential(ui_value: str | None, env_value: str | None) -> tuple[str | None, CredentialSource]:
    if ui_value and ui_value.strip():
        return ui_value.strip(), "ui"
    if env_value and env_value.strip():
        return env_value.strip(), "env"
    return None, "none"


@dataclass(frozen=True)
class SearchSettings:
    """Effective settings; ``api_key`` is internal and must never be serialized."""

    enabled: bool
    api_key: str | None
    folder_id: str | None
    api_key_source: CredentialSource
    folder_id_source: CredentialSource

    @classmethod
    def resolve(
        cls,
        *,
        enabled: bool | None = None,
        ui_api_key: str | None = None,
        ui_folder_id: str | None = None,
        env_api_key: str | None = None,
        env_folder_id: str | None = None,
    ) -> SearchSettings:
        api_key, api_key_source = _credential(ui_api_key, env_api_key)
        folder_id, folder_id_source = _credential(ui_folder_id, env_folder_id)
        return cls(
            enabled=True if enabled is None else enabled,
            api_key=api_key,
            folder_id=folder_id,
            api_key_source=api_key_source,
            folder_id_source=folder_id_source,
        )

    @property
    def has_api_key(self) -> bool:
        """Whether the effective key exists, without exposing it."""
        return self.api_key is not None
