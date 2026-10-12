"""Pure domain models. They are plain dataclasses with no I/O and no framework types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

KIND_OPENAI = "openai"
SUPPORTED_KINDS = (KIND_OPENAI,)


@dataclass(frozen=True)
class Connection:
    """A saved provider connection. Never holds an API key."""

    id: str
    name: str
    kind: str
    model: str
    endpoint: str | None = None
    thinking_disabled: bool = False
    preset: bool = False
    answer_mode: Literal["text", "deepseek_web"] = "text"

    def metadata(self) -> dict[str, Any]:
        """The non-secret part that is persisted to disk."""
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "endpoint": self.endpoint,
            "model": self.model,
            "answer_mode": self.answer_mode,
        }
