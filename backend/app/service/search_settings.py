"""Public Yandex settings and live configuration for future search jobs."""

from __future__ import annotations

from collections.abc import Mapping
from threading import RLock

import httpx

from app.core.errors import ConfigurationError, StorageError
from app.db.search_settings import SearchSettingsRepository
from app.domain.search import SearchGateway
from app.domain.search_settings import SearchSettings
from app.integrations.yandex_search import YandexSearchGateway
from app.service.search import SearchService


class SearchSettingsService:
    def __init__(
        self,
        repository: SearchSettingsRepository,
        search: SearchService,
        client: httpx.AsyncClient,
        *,
        gateway_override: SearchGateway | None = None,
    ) -> None:
        self.repository = repository
        self.search = search
        self.client = client
        self.gateway_override = gateway_override
        self._lock = RLock()
        try:
            self._configure(repository.load())
        except (ConfigurationError, StorageError):
            # Search settings cannot take model configuration or model runs down.
            self.search.configure(None, True)

    def public(self) -> dict[str, object]:
        with self._lock:
            try:
                settings = self.repository.load()
            except (ConfigurationError, StorageError):
                self.search.configure(None, True)
                raise
            self._configure(settings)
            return self._public(settings)

    def update(self, payload: Mapping[str, object]) -> dict[str, object]:
        with self._lock:
            settings = self.repository.update(payload)
            self._configure(settings)
            return self._public(settings)

    def reset_credentials(self) -> dict[str, object]:
        with self._lock:
            settings = self.repository.reset_credentials()
            self._configure(settings)
            return self._public(settings)

    def gateway_snapshot(self) -> SearchGateway | None:
        """Return the gateway currently configured for new jobs, or None.

        The orchestrator captures this value once per run, so a settings change
        made while a run is in flight never swaps the gateway underneath it. No
        credential ever leaves this method: only the configured adapter.
        """
        with self._lock:
            return self.search.gateway

    def enabled(self) -> bool:
        """Whether new Yandex jobs may be started at all."""
        with self._lock:
            return self.search.enabled

    def _configure(self, settings: SearchSettings) -> None:
        gateway = self.gateway_override
        if gateway is None and settings.api_key and settings.folder_id:
            gateway = YandexSearchGateway(settings.api_key, settings.folder_id, self.client)
        self.search.configure(gateway, settings.enabled)

    @staticmethod
    def _public(settings: SearchSettings) -> dict[str, object]:
        return {"yandex": {
            "enabled": settings.enabled,
            "folder_id": settings.folder_id,
            "has_api_key": settings.has_api_key,
            "api_key_source": settings.api_key_source,
            "folder_id_source": settings.folder_id_source,
        }}
