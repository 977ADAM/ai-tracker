"""The Yandex search gateway the settings screen and a measurement share.

The application no longer queues search jobs: a measurement submits and polls the
gateway itself. This service only holds what the next run should use, so a
settings change is visible to the next measurement immediately.
"""

from __future__ import annotations

from app.domain.search import SearchGateway


class SearchService:
    """The configured gateway and the availability of the Yandex branch."""

    def __init__(self, gateway: SearchGateway | None) -> None:
        self.gateway = gateway
        self.enabled = True

    def configure(self, gateway: SearchGateway | None, enabled: bool) -> None:
        """Set the gateway and availability the next measurement will use."""
        self.gateway = gateway
        self.enabled = enabled

    async def close(self) -> None:
        """Kept for the shutdown contract; this service owns no background work."""


__all__ = ["SearchService"]
