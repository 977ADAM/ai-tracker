"""The composition root: one `Container` of services per application instance.

Nothing here knows about HTTP. Every collaborator is built once, injected where
it is shared, and passed explicitly where a run needs its own instance, so the
whole object graph of the application can be assembled — and replaced in tests —
without starting a server.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.api.deps.checkpoints import agent_checkpointer, checkpoint_probe
from app.api.deps.fallbacks import UnconfiguredAgentModel
from app.core.config import Settings
from app.db.chat import ChatRepository
from app.db.connections import ConnectionRepository
from app.db.measurements import MeasurementRepository
from app.db.projects import ProjectRepository
from app.db.runs import RunRepository
from app.db.search_settings import SearchSettingsRepository
from app.db.secrets import KeyringSecrets, SecretStore
from app.db.seo import SeoRepository
from app.db.seo_settings import SeoSettingsRepository
from app.domain.providers import ProviderFactory
from app.domain.search import SearchGateway
from app.domain.seo import SeoInput
from app.domain.seo_answer import SeoAnswerProvider, SeoConnectionSnapshot
from app.domain.seo_llm import AgentModel
from app.domain.seo_tools import SeoBudget
from app.domain.site_fetch import SiteFetcher
from app.integrations.factory import build_provider
from app.integrations.seo_answer import build_seo_answer_provider
from app.integrations.site_fetcher import HttpxSiteFetcher
from app.service.chat import ChatService
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
from app.service.seo import SeoService
from app.service.seo_agents import CheckpointFactory, SeoAgentRuntime
from app.service.seo_settings import SeoSettingsService
from app.service.seo_tools import SeoToolbox

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
    seo: SeoRepository
    seo_service: SeoService
    seo_settings: SeoSettingsService
    chats: ChatRepository
    chat_service: ChatService
    projects: ProjectService
    project_generation: ProjectGenerationService
    measurements: MeasurementService


def make_seo_toolbox_factory(
    repository: SeoRepository,
    fetcher: SiteFetcher,
    search_settings: SearchSettingsService,
    connections: ConnectionService,
    provider_factory: ProviderFactory,
    seo_answer_factory: Callable[[SeoConnectionSnapshot, str], SeoAnswerProvider] | None = None,
) -> Callable[[str, SeoInput, SeoBudget], SeoToolbox]:
    """Return the factory of one run's toolbox, over settings read at run start.

    The gateway is resolved when a run begins, not at container build, so a
    settings change reaches the next run; the repository, the fetcher, the
    connections, and the provider factory are the app's own shared collaborators.
    """

    def build(analysis_id: str, run_input: SeoInput, budget: SeoBudget) -> SeoToolbox:
        return SeoToolbox(
            repository,
            fetcher,
            search_settings.gateway_snapshot(),
            connections,
            provider_factory,
            analysis_id=analysis_id,
            input=run_input,
            connection_ids=run_input.connection_ids,
            budget=budget,
            seo_answer_factory=seo_answer_factory,
        )

    return build


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
    chats: ChatRepository | None = None,
    chat_service: ChatService | None = None,
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
    run_repository = RunRepository(Path(settings.config_dir))
    run_repository.initialize()
    run_repository.recover_unfinished()
    # The SEO repository owns the version-4 migration of the same file, so it
    # always initializes after the run repository opened and recovered.
    if seo_repository is None:
        seo_repository = SeoRepository(Path(settings.config_dir))
    seo_repository.initialize()
    # The chat repository owns the version-5 migration of the same file, so it
    # always initializes after the SEO repository opened the file at version 4.
    if chats is None:
        chats = ChatRepository(Path(settings.config_dir))
    chats.initialize()
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
    toolbox_factory = seo_toolbox_factory or make_seo_toolbox_factory(
        seo_repository, resolved_fetcher, search_settings, connections, factory,
        lambda snapshot, key: build_seo_answer_provider(snapshot, key, settings, text_factory=factory),
    )

    if seo_agent_runtime is None:
        # The runtime asks for the service LLM at the start of every run, not
        # once at build time: the application boots before the user configures
        # it, so a model resolved here would freeze that unconfigured state and
        # every later run would fail. The build-time model is only what a runtime
        # built without a provider falls back to.
        agent_model = (
            seo_agent_model if seo_agent_model is not None
            else seo_settings_service.build_agent_model()
        )
        seo_agent_runtime = SeoAgentRuntime(
            seo_repository,
            toolbox_factory,
            agent_model if agent_model is not None else UnconfiguredAgentModel(),
            model_provider=(
                None if seo_agent_model is not None
                else seo_settings_service.build_agent_model
            ),
            checkpointer=(
                seo_checkpointer if seo_checkpointer is not None
                else agent_checkpointer(Path(settings.config_dir))
            ),
        )
    if seo_service is None:
        # The service owns the configuration refusals and the background tasks;
        # the restart policy inside it defers a checkpointed run until a loop
        # exists.
        seo_service = SeoService(
            seo_repository,
            seo_agent_runtime,
            search_settings,
            seo_settings_service,
            connections,
            checkpoint_probe=checkpoint_probe(Path(settings.config_dir)),
        )
        seo_service.recover()
    form = FormService(connections)
    if chat_service is None:
        # The chat asks for its model on every turn, not once at build time: the
        # application boots before the user configures the service LLM, so a
        # client resolved here would freeze that unconfigured state.
        chat_service = ChatService(
            chats, seo_service, connections, form,
            client_factory=seo_settings_service.build_client,
        )
    project_repository = ProjectRepository(Path(settings.config_dir))
    project_repository.initialize()
    measurement_repository = MeasurementRepository(Path(settings.config_dir))
    measurement_repository.recover_unfinished()
    measurements = MeasurementService(
        measurement_repository, project_repository, connections, seo_settings_service,
        search_settings, lambda snapshot, key: build_seo_answer_provider(snapshot, key, settings, text_factory=factory),
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
        seo=seo_repository,
        seo_service=seo_service,
        seo_settings=seo_settings_service,
        chats=chats,
        chat_service=chat_service,
        projects=projects,
        project_generation=ProjectGenerationService(project_repository, resolved_fetcher, seo_settings_service),
        measurements=measurements,
    )
