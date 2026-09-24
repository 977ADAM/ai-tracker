"""Provider groups and their selectable models, without secrets or I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderModel:
    id: str
    model: str
    name: str

    def metadata(self) -> dict[str, str]:
        return {"id": self.id, "model": self.model, "name": self.name}


@dataclass(frozen=True)
class ProviderGroup:
    id: str
    name: str
    endpoint: str
    models: tuple[ProviderModel, ...]
    kind: str = "openai"

    def metadata(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "kind": self.kind,
            "endpoint": self.endpoint, "models": [model.metadata() for model in self.models],
        }
