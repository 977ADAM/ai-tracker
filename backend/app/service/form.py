"""Form use case: the limits and options the check page needs before a run."""

from __future__ import annotations

from typing import Any

from app.domain.connections import NEW_PROVIDER_FIELDS
from app.domain.limits import LIMITS, SCOPE_OPTIONS
from app.service.connections import ConnectionService


class FormService:
    def __init__(self, connections: ConnectionService) -> None:
        self.connections = connections

    def build(self) -> dict[str, Any]:
        providers = self.connections.list_public()
        ready = next((item for item in providers if item["configured"]), None)
        return {
            "limits": dict(LIMITS),
            "new_provider_fields": list(NEW_PROVIDER_FIELDS),
            "scope_options": [dict(option) for option in SCOPE_OPTIONS],
            "default_provider_ids": [ready["id"]] if ready else [],
        }
