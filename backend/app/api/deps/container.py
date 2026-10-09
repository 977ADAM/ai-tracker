"""The composition root: one `Container` of services per application instance.

Nothing here knows about HTTP. Every collaborator is built once, injected where
it is shared, and passed explicitly where a run needs its own instance, so the
whole object graph of the application can be assembled — and replaced in tests —
without starting a server.

The application is an AI tracker: a company is one project, and every durable
row (a measurement snapshot, a brand-check run) belongs to that project in one
PostgreSQL database.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from app.core.config import Settings
from app.db.connections import ConnectionRepository
from app.db.measurements import MeasurementRepository
from app.db.projects import ProjectRepository
from app.db.runs import RunRepository
from app.db.search_settings import SearchSettingsRepository
from app.db.secrets import KeyringSecrets, SecretStore
from app.db.seo_settings import SeoSettingsRepository
from app.domain.providers import ProviderFactory
from app.domain.search import SearchGateway
from app.domain.site_fetch import SiteFetcher
from app.integrations.factory import build_provider
from app.integrations.seo_answer import build_seo_answer_provider
from app.integrations.site_fetcher import HttpxSiteFetcher
from app.service.checks import CheckService
from app.service.config import ConfigService
from app.service.connections import ConnectionService
from app.service.form import FormService
from app.service.measurements import MeasurementService
from app.service.project_generation import ProjectGenerationService
from app.service.projects import ProjectService
from app.service.provider_settings import ProviderSettingsService
from app.service.runs import RunService
from app.service.search import SearchService
from app.service.search_settings import SearchSettingsService
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
    config: ConfigService
    search: SearchService
    runs: RunService
    search_settings: SearchSettingsService
    search_client: httpx.AsyncClient
    seo_settings: SeoSettingsService
    projects: ProjectService
    project_generation: ProjectGenerationService
    measurements: MeasurementService


def build_container(
    settings: Settings,
    *,
    repository: ConnectionRepository | None = None,
    secrets: SecretStore | None = None,
    provider_factory: ProviderFactory | None = None,
    search_gateway: SearchGateway | None = None,
    search_settings_repository: SearchSettingsRepository | None = None,
    seo_settings_repository: SeoSettingsRepository | None = None,
    seo_settings_service: SeoSettingsService | None = None,
    fetcher: SiteFetcher | None = None,
) -> Container:
    """Assemble the services of one application; every collaborator is injectable."""
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
    # One PostgreSQL database holds every durable row. Its schema is created and
    # changed by the Alembic CLI (`uv run alembic upgrade head`), never here.
    run_repository = RunRepository(settings.database_url)
    run_repository.recover_unfinished()
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
        # The service-LLM settings service shares the app's HTTP client and
        # resolves its values lazily, so a settings change is visible to the
        # next measurement or generation request.
        seo_settings_service = SeoSettingsService(seo_settings_repository, search_client)

    resolved_fetcher = fetcher if fetcher is not None else HttpxSiteFetcher(search_client)
    form = FormService(connections)
    project_repository = ProjectRepository(settings.database_url)
    measurement_repository = MeasurementRepository(settings.database_url)
    measurement_repository.recover_unfinished()
    measurements = MeasurementService(
        measurement_repository, project_repository, connections, seo_settings_service,
        search_settings,
        lambda snapshot, key: build_seo_answer_provider(snapshot, key, settings, text_factory=factory),
    )
    projects = ProjectService(project_repository, measurement_repository, connections)
    return Container(
        settings=settings,
        repository=repository,
        connections=connections,
        checks=checks,
        form=form,
        provider_settings=ProviderSettingsService(repository),
        config=ConfigService(Path(settings.config_dir)),
        search=search,
        runs=RunService(run_repository, checks, search),
        search_settings=search_settings,
        search_client=search_client,
        seo_settings=seo_settings_service,
        projects=projects,
        project_generation=ProjectGenerationService(project_repository, resolved_fetcher, seo_settings_service),
        measurements=measurements,
    )
