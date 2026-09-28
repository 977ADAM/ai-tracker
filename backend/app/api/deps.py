"""Wiring of services for one app instance, plus FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, Request

from app.core.config import Settings
from app.db.connections import ConnectionRepository
from app.db.runs import RunRepository
from app.db.search_settings import SearchSettingsRepository
from app.db.secrets import KeyringSecrets, SecretStore
from app.db.seo import SeoRepository
from app.db.seo_settings import SeoSettingsRepository
from app.domain.providers import ProviderFactory
from app.domain.search import SearchGateway
from app.domain.site_fetch import SiteFetcher
from app.integrations.factory import build_provider
from app.integrations.seo_llm import SeoLlmClient
from app.integrations.site_fetcher import HttpxSiteFetcher
from app.service.checks import CheckService
from app.service.connections import ConnectionService
from app.service.form import FormService
from app.service.provider_settings import ProviderSettingsService
from app.service.runs import RunService
from app.service.search import SearchService
from app.service.search_settings import SearchSettingsService
from app.service.seo import SeoService
from app.service.seo_settings import SeoSettingsService

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
    runs: RunService
    search_settings: SearchSettingsService
    search_client: httpx.AsyncClient
    seo: SeoRepository
    seo_service: SeoService
    seo_settings: SeoSettingsService


def build_container(
    settings: Settings,
    *,
    repository: ConnectionRepository | None = None,
    secrets: SecretStore | None = None,
    provider_factory: ProviderFactory | None = None,
    search_gateway: SearchGateway | None = None,
    search_settings_repository: SearchSettingsRepository | None = None,
    seo_repository: SeoRepository | None = None,
    seo_settings_repository: SeoSettingsRepository | None = None,
    seo_settings_service: SeoSettingsService | None = None,
    seo_service: SeoService | None = None,
    fetcher: SiteFetcher | None = None,
    llm_factory: Callable[[], SeoLlmClient | None] | None = None,
) -> Container:
    secret_store = secrets or KeyringSecrets()
    if repository is None:
        repository = ConnectionRepository(
            Path(settings.config_dir),
            secret_store,
            presets=settings.presets,
            env_api_key=settings.env_api_key,
            service_name=settings.service_name,
        )
    if search_settings_repository is None:
        search_settings_repository = SearchSettingsRepository(
            Path(settings.config_dir), secret_store,
            env_api_key=settings.yandex_search_api_key,
            env_folder_id=settings.yandex_search_folder_id,
            service_name=settings.service_name,
        )
    search_client = httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=CONNECT_TIMEOUT, pool=CONNECT_TIMEOUT),
    )
    connections = ConnectionService(repository, settings)
    factory = provider_factory or (lambda connection, key: build_provider(connection, key, settings))
    run_repository = RunRepository(Path(settings.config_dir))
    run_repository.initialize()
    run_repository.recover_unfinished()
    # The SEO repository owns the version-3 migration of the same file, so it
    # always initializes after the run repository opened and recovered.
    if seo_repository is None:
        seo_repository = SeoRepository(Path(settings.config_dir))
    seo_repository.initialize()
    checks = CheckService(connections, factory)
    search = SearchService(None)
    search_settings = SearchSettingsService(
        search_settings_repository, search, search_client, gateway_override=search_gateway,
    )
    if seo_settings_repository is None:
        seo_settings_repository = SeoSettingsRepository(
            Path(settings.config_dir),
            secret_store,
            env_endpoint=settings.seo_llm_endpoint,
            env_model=settings.seo_llm_model,
            env_api_key=settings.seo_llm_api_key,
            service_name=settings.service_name,
        )
    if seo_settings_service is None:
        # The settings service shares the app's HTTP client and resolves its
        # values lazily, so a settings change is visible to the next run.
        seo_settings_service = SeoSettingsService(seo_settings_repository, search_client)

    def resolved_llm_factory() -> SeoLlmClient | None:
        return seo_settings_service.build_client()

    if seo_service is None:
        # The orchestrator owns the six stages. It captures the gateway and the
        # service-LLM client once per run, so a settings change made while a run
        # is in flight never swaps a collaborator underneath it.
        seo_service = SeoService(
            seo_repository,
            seo_settings_repository,
            llm_factory or resolved_llm_factory,
            fetcher if fetcher is not None else HttpxSiteFetcher(search_client),
            search_settings,
            connections,
            factory,
        )
        seo_service.recover()
    return Container(
        settings=settings,
        repository=repository,
        connections=connections,
        checks=checks,
        form=FormService(connections),
        provider_settings=ProviderSettingsService(repository),
        search=search,
        runs=RunService(run_repository, checks, search),
        search_settings=search_settings,
        search_client=search_client,
        seo=seo_repository,
        seo_service=seo_service,
        seo_settings=seo_settings_service,
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


def get_search_settings_service(container: ContainerDep) -> SearchSettingsService:
    return container.search_settings


def get_run_service(container: ContainerDep) -> RunService:
    return container.runs


def get_seo_service(container: ContainerDep) -> SeoService:
    return container.seo_service


def get_seo_settings_service(container: ContainerDep) -> SeoSettingsService:
    return container.seo_settings


ConnectionServiceDep = Annotated[ConnectionService, Depends(get_connection_service)]
CheckServiceDep = Annotated[CheckService, Depends(get_check_service)]
FormServiceDep = Annotated[FormService, Depends(get_form_service)]
ProviderSettingsServiceDep = Annotated[ProviderSettingsService, Depends(get_provider_settings_service)]
SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]
SearchSettingsServiceDep = Annotated[SearchSettingsService, Depends(get_search_settings_service)]
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
SeoServiceDep = Annotated[SeoService, Depends(get_seo_service)]
SeoSettingsServiceDep = Annotated[SeoSettingsService, Depends(get_seo_settings_service)]
