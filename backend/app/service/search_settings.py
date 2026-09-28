"""Public Yandex settings and live configuration for future search jobs."""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from app.db.search_settings import SearchSettingsRepository
from app.domain.search_settings import SearchSettings
from app.integrations.yandex_search import YandexSearchGateway
from app.service.search import SearchService


class SearchSettingsService:
    def __init__(
        self,
        repository: SearchSettingsRepository,
        search: SearchService,
        client: httpx.AsyncClient,
    ) -> None:
        self.repository = repository
        self.search = search
        self.client = client
        self._configure(repository.load())

    def public(self) -> dict[str, object]:
        return self._public(self.repository.load())

    def update(self, payload: Mapping[str, object]) -> dict[str, object]:
        settings = self.repository.update(payload)
        self._configure(settings)
        return self._public(settings)

    def reset_credentials(self) -> dict[str, object]:
        settings = self.repository.reset_credentials()
        self._configure(settings)
        return self._public(settings)

    def _configure(self, settings: SearchSettings) -> None:
        gateway = None
        if settings.api_key and settings.folder_id:
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
