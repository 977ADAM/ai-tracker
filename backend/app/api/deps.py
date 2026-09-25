"""Wiring of services for one app instance, plus FastAPI dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, Request

from app.core.config import Settings
from app.db.connections import ConnectionRepository
from app.db.secrets import KeyringSecrets, SecretStore
from app.domain.providers import ProviderFactory
from app.domain.search import SearchGateway
from app.integrations.factory import build_provider
from app.integrations.yandex_search import YandexSearchGateway
from app.service.checks import CheckService
from app.service.connections import ConnectionService
from app.service.form import FormService
from app.service.provider_settings import ProviderSettingsService
from app.service.search import SearchService

CONNECT_TIMEOUT = 20
READ_TIMEOUT = 60


@dataclass(frozen=True)
class Container:
    """Everything the routers need, built once per app instance."""

    settings: Settings
    repository: ConnectionRepository
    connections: ConnectionService
    checks: CheckService
    form: FormService
    provider_settings: ProviderSettingsService
    search: SearchService
    search_client: httpx.AsyncClient | None = None


def build_search_gateway(settings: Settings) -> tuple[SearchGateway | None, httpx.AsyncClient | None]:
    """Build the Yandex adapter over one shared client, or nothing without credentials."""
    if not settings.has_yandex_search_credentials:
        return None, None
    client = httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=CONNECT_TIMEOUT, pool=CONNECT_TIMEOUT),
    )
    gateway = YandexSearchGateway(settings.yandex_search_api_key or "", settings.yandex_search_folder_id or "", client)
    return gateway, client


def build_container(
    settings: Settings,
    *,
    repository: ConnectionRepository | None = None,
    secrets: SecretStore | None = None,
    provider_factory: ProviderFactory | None = None,
    search_gateway: SearchGateway | None = None,
) -> Container:
    if repository is None:
        repository = ConnectionRepository(
            Path(settings.config_dir),
            secrets or KeyringSecrets(),
            presets=settings.presets,
            env_api_key=settings.env_api_key,
            service_name=settings.service_name,
        )
    if search_gateway is None:
        search_gateway, search_client = build_search_gateway(settings)
    else:
        search_client = None
    connections = ConnectionService(repository, settings)
    factory = provider_factory or (lambda connection, key: build_provider(connection, key, settings))
    return Container(
        settings=settings,
        repository=repository,
        connections=connections,
        checks=CheckService(connections, factory),
        form=FormService(connections),
        provider_settings=ProviderSettingsService(repository),
        search=SearchService(search_gateway),
        search_client=search_client,
    )


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_connection_service(container: ContainerDep) -> ConnectionService:
    return container.connections


def get_check_service(container: ContainerDep) -> CheckService:
    return container.checks


def get_form_service(container: ContainerDep) -> FormService:
    return container.form


def get_provider_settings_service(container: ContainerDep) -> ProviderSettingsService:
    return container.provider_settings


def get_search_service(container: ContainerDep) -> SearchService:
    return container.search


ConnectionServiceDep = Annotated[ConnectionService, Depends(get_connection_service)]
CheckServiceDep = Annotated[CheckService, Depends(get_check_service)]
FormServiceDep = Annotated[FormService, Depends(get_form_service)]
ProviderSettingsServiceDep = Annotated[ProviderSettingsService, Depends(get_provider_settings_service)]
SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]
