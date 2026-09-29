"""Wiring of services for one app instance, plus FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import Depends, Request
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.db.connections import ConnectionRepository
from app.db.runs import RunRepository
from app.db.search_settings import SearchSettingsRepository
from app.db.secrets import KeyringSecrets, SecretStore
from app.db.seo import SeoRepository
from app.db.seo_settings import SeoSettingsRepository
from app.domain.providers import ProviderFactory
from app.domain.search import SearchGateway
from app.domain.seo import SeoInput
from app.domain.seo_llm import AgentModel
from app.domain.seo_tools import SeoBudget
from app.domain.site_fetch import SiteFetcher
from app.integrations.factory import build_provider
from app.integrations.site_fetcher import HttpxSiteFetcher
from app.service.checks import CheckService
from app.service.config import ConfigService
from app.service.connections import ConnectionService
from app.service.form import FormService
from app.service.provider_settings import ProviderSettingsService
from app.service.runs import RunService
from app.service.search import SearchService
from app.service.search_settings import SearchSettingsService
from app.service.seo import LLM_NOT_CONFIGURED, SeoService
from app.service.seo_agents import (
    CheckpointFactory,
    SeoAgentRuntime,
    checkpoint_exists,
    checkpoint_path,
    secure_checkpoint,
)
from app.service.seo_settings import SeoSettingsService
from app.service.seo_tools import SeoToolbox

CONNECT_TIMEOUT = 20
READ_TIMEOUT = 60


class UnconfiguredAgentModel(BaseChatModel):
    """The stand-in chat model of a container without a configured service LLM.

    The application must start while the SEO LLM settings are empty, but
    `SeoAgentRuntime` resolves its chat model when it is built. This model is
    never called: `SeoService.start` refuses such a run with a safe configuration
    error before any analysis row or paid call exists.
    """

    @property
    def _llm_type(self) -> str:
        return "seo-unconfigured"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise ConfigurationError(LLM_NOT_CONFIGURED)


def agent_checkpointer(config_dir: Path) -> CheckpointFactory:
    """Return the factory of the owner-only graph checkpoint file.

    Graph state lives beside `runs.sqlite3`, never inside it, and one file holds
    the thread of every analysis: the runtime passes the analysis id as the
    `thread_id`, so a restart finds exactly the run it needs.
    """
    path = checkpoint_path(config_dir)

    @asynccontextmanager
    async def open_checkpointer(_analysis_id: str):
        secure_checkpoint(path)
        async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
            yield saver

    return open_checkpointer


def checkpoint_probe(config_dir: Path) -> Callable[[str], bool]:
    """Return the synchronous restart probe over one config directory."""
    path = checkpoint_path(config_dir)
    return lambda analysis_id: checkpoint_exists(path, analysis_id)


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
    seo_agent_runtime: SeoAgentRuntime | None = None,
    seo_agent_model: BaseChatModel | AgentModel | None = None,
    seo_toolbox_factory: Callable[[str, SeoInput, SeoBudget], SeoToolbox] | None = None,
    seo_checkpointer: BaseCheckpointSaver | CheckpointFactory | None = None,
    fetcher: SiteFetcher | None = None,
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
    # The SEO repository owns the version-4 migration of the same file, so it
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

    resolved_fetcher = fetcher if fetcher is not None else HttpxSiteFetcher(search_client)

    def agent_toolbox(analysis_id: str, run_input: SeoInput, budget: SeoBudget) -> SeoToolbox:
        """Build one run's toolbox over the settings resolved when it starts.

        The gateway and the model name are read here, not at container build, so
        a settings change reaches the next run; the connections, the fetcher, and
        the provider factory are the app's own shared collaborators.
        """
        return SeoToolbox(
            seo_repository,
            resolved_fetcher,
            search_settings.gateway_snapshot(),
            connections,
            factory,
            analysis_id=analysis_id,
            input=run_input,
            connection_ids=run_input.connection_ids,
            budget=budget,
            model_name=str(seo_settings_service.public()["model"] or ""),
        )

    if seo_agent_runtime is None:
        # The runtime resolves its chat model once, at build time. Without a
        # configured service LLM it gets a stand-in that is never called, because
        # `SeoService.start` refuses such a run first.
        agent_model = (
            seo_agent_model if seo_agent_model is not None
            else seo_settings_service.build_agent_model()
        )
        seo_agent_runtime = SeoAgentRuntime(
            seo_repository,
            seo_toolbox_factory if seo_toolbox_factory is not None else agent_toolbox,
            agent_model if agent_model is not None else UnconfiguredAgentModel(),
            checkpointer=(
                seo_checkpointer if seo_checkpointer is not None
                else agent_checkpointer(Path(settings.config_dir))
            ),
        )
    if seo_service is None:
        # The service owns the configuration refusals and the background tasks;
        # the restart policy below defers a checkpointed run until a loop exists.
        seo_service = SeoService(
            seo_repository,
            seo_agent_runtime,
            search_settings,
            seo_settings_service,
            connections,
            checkpoint_probe=checkpoint_probe(Path(settings.config_dir)),
        )
        seo_service.recover()
    return Container(
        settings=settings,
        repository=repository,
        connections=connections,
        checks=checks,
        form=FormService(connections),
        provider_settings=ProviderSettingsService(repository),
        config=ConfigService(Path(settings.config_dir)),
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


def get_config_service(container: ContainerDep) -> ConfigService:
    return container.config


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
ConfigServiceDep = Annotated[ConfigService, Depends(get_config_service)]
SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]
SearchSettingsServiceDep = Annotated[SearchSettingsService, Depends(get_search_settings_service)]
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
SeoServiceDep = Annotated[SeoService, Depends(get_seo_service)]
SeoSettingsServiceDep = Annotated[SeoSettingsService, Depends(get_seo_settings_service)]
