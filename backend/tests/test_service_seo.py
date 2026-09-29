"""The SEO service over the agent runtime: refusals, lifecycle, and restart.

The runtime itself is a fake here, so the suite proves the service contract —
which configuration refuses a run before an analysis row or a paid call exists,
what `start` answers, what it delegates, and how a restart is decided — without a
graph and without any paid API. The real graph, its budgets, and its checkpoint
resume are covered by `test_service_seo_agents.py`.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.core.errors import (
    ConfigurationError,
    RunConflict,
    RunNotFound,
    StorageError,
    ValidationError,
)
from app.db.search_settings import SearchSettingsRepository
from app.db.seo import SeoRepository
from app.domain.seo import SeoInput, normalize_seo_request
from app.domain.seo_llm import AgentTurn
from app.service.checks import MISSING_KEY_MESSAGE
from app.service.connections import ConnectionService
from app.service.search import DISABLED_ENGINE, MISSING_CREDENTIALS, SearchService
from app.service.search_settings import SearchSettingsService
from app.service.seo import LLM_NOT_CONFIGURED, SeoService
from app.service.seo_settings import TOOLS_UNSUPPORTED
from tests.fakes import (
    FakeAgentModel,
    FakeSeoAgentRuntime,
    FakeSeoSettingsService,
    MemorySecrets,
    ScriptedSeoGateway,
    StorageFailingSeoRepository,
    tool_calling_settings,
)

SEEDS = ("букет цветов", "доставка цветов", "розы")
ESTIMATE = {"search_upper": 43, "model_upper": 40, "generated_limit": 40, "connections": 1}
TERMINAL = frozenset({"completed", "failed", "interrupted", "cancelled"})
# A sentinel for "this container has no Yandex gateway at all".
NO_GATEWAY = object()


def payload(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "url": "https://example.ru/",
        "sphere": "Цветочный магазин",
        "seeds": list(SEEDS),
        "services": ["Букеты", "Доставка"],
        "connection_ids": ["gigachat"],
    }
    data.update(overrides)
    return data


def stored_input(**overrides: object) -> SeoInput:
    return normalize_seo_request(payload(**overrides))


def make_search_settings(tmp_path: Path, gateway: Any, *, enabled: bool = True) -> SearchSettingsService:
    repository = SearchSettingsRepository(
        tmp_path, MemorySecrets(), env_api_key=None, env_folder_id=None, service_name="test",
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    override = None if gateway is NO_GATEWAY else gateway
    service = SearchSettingsService(repository, SearchService(None), client, gateway_override=override)
    service.update({"enabled": enabled})
    return service


def make_harness(
    tmp_path: Path,
    connection_repository: Any,
    settings: Any,
    *,
    gateway: ScriptedSeoGateway | None = None,
    yandex_enabled: bool = True,
    yandex_configured: bool = True,
    configured_connections: tuple[tuple[str, str], ...] = (("gigachat", "test-key"),),
    seo_repository: Any = None,
    llm_settings: Any = None,
    runtime: Any = None,
    runtime_mode: str = "complete",
    checkpoint_probe: Any = None,
) -> SimpleNamespace:
    connections = ConnectionService(connection_repository, settings)
    for connection_id, key in configured_connections:
        connections.save({"api_key": key}, connection_id)
    repository = seo_repository if seo_repository is not None else SeoRepository(tmp_path)
    repository.initialize()
    runtime = runtime if runtime is not None else FakeSeoAgentRuntime(repository, mode=runtime_mode)
    llm = llm_settings if llm_settings is not None else tool_calling_settings()
    gateway = gateway if gateway is not None else ScriptedSeoGateway()
    search_settings = make_search_settings(
        tmp_path, gateway if yandex_configured else NO_GATEWAY, enabled=yandex_enabled,
    )
    service = SeoService(
        repository, runtime, search_settings, llm, connections, checkpoint_probe=checkpoint_probe,
    )
    return SimpleNamespace(
        service=service,
        repository=repository,
        runtime=runtime,
        llm=llm,
        gateway=gateway,
        connections=connections,
        search_settings=search_settings,
    )


async def wait_terminal(service: SeoService, analysis_id: str, *, timeout: float = 5.0) -> dict:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        snapshot = service.snapshot(analysis_id)
        if snapshot["status"] in TERMINAL:
            return snapshot
        await asyncio.sleep(0.001)
    raise AssertionError(f"analysis stayed {service.snapshot(analysis_id)['status']}")


def seed_states(db_path: Path, analysis_id: str) -> dict[int, tuple[str, str | None]]:
    connection = sqlite3.connect(db_path)
    try:
        return {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                "SELECT seed_index, status, operation_id FROM seo_seed_rows "
                "WHERE analysis_id=? ORDER BY seed_index",
                (analysis_id,),
            )
        }
    finally:
        connection.close()


# -- start -------------------------------------------------------------------


@pytest.mark.anyio
async def test_start_writes_the_analysis_and_runs_the_graph_in_the_background(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings)

    created = await harness.service.start(payload())

    assert set(created) == {"id", "status", "estimate"}
    assert created["status"] == "running"
    assert created["estimate"] == ESTIMATE
    assert harness.service.snapshot(created["id"])["status"] == "running"
    assert harness.gateway.submitted == []

    snapshot = await wait_terminal(harness.service, created["id"])

    assert snapshot["status"] == "completed"
    assert harness.runtime.runs == [(created["id"], stored_input())]
    # The finished run leaves no task and no cancellation state behind.
    assert harness.service.tasks == {}
    await harness.service.close()


@pytest.mark.anyio
async def test_the_estimate_counts_every_selected_connection(tmp_path, repository, settings):
    harness = make_harness(
        tmp_path,
        repository,
        settings,
        configured_connections=(("gigachat", "key-1"), ("deepseek", "key-2")),
    )

    created = await harness.service.start(payload(connection_ids=["gigachat", "deepseek"]))

    assert created["estimate"] == {
        "search_upper": 43, "model_upper": 80, "generated_limit": 40, "connections": 2,
    }
    await asyncio.sleep(0)
    assert harness.runtime.runs[0][1].connection_ids == ("gigachat", "deepseek")
    await harness.service.close()


@pytest.mark.anyio
async def test_the_tool_probe_sends_one_trivial_schema_and_closes_the_adapter(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings)
    model = harness.llm.model

    created = await harness.service.start(payload())

    assert len(model.steps) == 1
    messages, tools = model.steps[0]
    assert [message.role for message in messages] == ["system", "user"]
    assert [tool.name for tool in tools] == ["check_connection"]
    # The probe adapter is one paid call of its own and never the run adapter.
    assert model.closed is True
    assert created["status"] == "running"
    await harness.service.close()


@pytest.mark.anyio
async def test_start_rejects_malformed_input_before_any_side_effect(tmp_path, repository, settings):
    harness = make_harness(tmp_path, repository, settings)

    with pytest.raises(ValidationError):
        await harness.service.start(payload(seeds=["один запрос"]))

    assert harness.service.list_page()["items"] == []
    assert harness.runtime.runs == []
    assert harness.llm.builds == 0
    assert harness.llm.model.steps == []
    await harness.service.close()


@pytest.mark.anyio
async def test_start_refuses_a_disabled_or_unconfigured_yandex(tmp_path, repository, settings):
    disabled = make_harness(tmp_path, repository, settings, yandex_enabled=False)
    with pytest.raises(ConfigurationError) as raised:
        await disabled.service.start(payload())
    assert str(raised.value) == DISABLED_ENGINE
    assert disabled.service.list_page()["items"] == []
    assert disabled.runtime.runs == []
    assert disabled.llm.builds == 0
    await disabled.service.close()

    without_gateway = make_harness(tmp_path, repository, settings, yandex_configured=False)
    with pytest.raises(ConfigurationError) as raised:
        await without_gateway.service.start(payload())
    assert str(raised.value) == MISSING_CREDENTIALS
    assert without_gateway.service.list_page()["items"] == []
    assert without_gateway.runtime.runs == []
    await without_gateway.service.close()


@pytest.mark.anyio
async def test_start_requires_a_configured_service_llm(tmp_path, repository, settings):
    harness = make_harness(
        tmp_path, repository, settings, llm_settings=FakeSeoSettingsService(None),
    )

    with pytest.raises(ConfigurationError) as raised:
        await harness.service.start(payload())

    assert str(raised.value) == LLM_NOT_CONFIGURED
    assert harness.service.list_page()["items"] == []
    assert harness.runtime.runs == []
    await harness.service.close()


@pytest.mark.anyio
async def test_start_refuses_a_model_that_cannot_call_tools(tmp_path, repository, settings):
    plain = FakeAgentModel(AgentTurn(text="OK", tool_calls=()))
    harness = make_harness(
        tmp_path, repository, settings, llm_settings=FakeSeoSettingsService(plain),
    )

    with pytest.raises(ConfigurationError) as raised:
        await harness.service.start(payload())

    assert str(raised.value) == TOOLS_UNSUPPORTED
    assert len(plain.steps) == 1
    assert harness.service.list_page()["items"] == []
    assert harness.runtime.runs == []
    await harness.service.close()


@pytest.mark.anyio
async def test_start_refuses_unknown_and_unconfigured_connections(tmp_path, repository, settings):
    harness = make_harness(tmp_path, repository, settings)

    with pytest.raises(ValidationError):
        await harness.service.start(payload(connection_ids=["missing"]))
    with pytest.raises(ConfigurationError) as raised:
        await harness.service.start(payload(connection_ids=["deepseek"]))
    assert str(raised.value) == MISSING_KEY_MESSAGE

    assert harness.service.list_page()["items"] == []
    assert harness.runtime.runs == []
    # Every local check runs before the only check that costs a model call.
    assert harness.llm.model.steps == []
    await harness.service.close()


# -- snapshot, history, rows, and trace --------------------------------------


@pytest.mark.anyio
async def test_snapshot_history_rows_and_trace_delegate_to_the_repository(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings)
    analysis_id = harness.repository.create_analysis(stored_input(), ESTIMATE)
    harness.repository.append_step(
        analysis_id, "supervisor", "handoff", "handoff_to",
        arguments={"agent": "site"}, status="done",
    )

    assert harness.service.snapshot(analysis_id) == harness.repository.snapshot(analysis_id)
    assert harness.service.list_page() == harness.repository.list_page()
    assert harness.service.list_page(None)["items"][0]["id"] == analysis_id
    assert harness.service.rows_page(analysis_id, "search") == harness.repository.rows_page(
        analysis_id, "search",
    )
    assert harness.service.rows_page(analysis_id, "model") == harness.repository.rows_page(
        analysis_id, "model",
    )
    assert harness.service.trace_page(analysis_id) == harness.repository.trace_page(analysis_id)
    assert harness.service.trace_page(analysis_id)["items"][0]["name"] == "handoff_to"

    with pytest.raises(RunNotFound):
        harness.service.snapshot("нет такого")
    with pytest.raises(ValidationError):
        harness.service.rows_page(analysis_id, "unknown")
    with pytest.raises(RunNotFound):
        harness.service.trace_page("нет такого")
    await harness.service.close()


# -- lifecycle ---------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_delegates_to_the_runtime_and_keeps_the_conflict_contract(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings, runtime_mode="hold")

    created = await harness.service.start(payload())
    await asyncio.sleep(0)
    assert created["id"] in harness.service.tasks

    cancelled = harness.service.cancel(created["id"])

    assert harness.runtime.cancels == [created["id"]]
    assert cancelled["status"] == "cancelled"
    assert cancelled["finished_at"] is not None
    # Cancellation is final: the stored state can never be cancelled twice.
    with pytest.raises(RunConflict):
        harness.service.cancel(created["id"])
    with pytest.raises(RunNotFound):
        harness.service.cancel("нет такого")
    await harness.service.close()


@pytest.mark.anyio
async def test_delete_works_only_in_a_terminal_state_and_drops_the_task(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings, runtime_mode="hold")
    created = await harness.service.start(payload())
    await asyncio.sleep(0)

    with pytest.raises(RunConflict):
        harness.service.delete(created["id"])

    harness.service.cancel(created["id"])
    await harness.service.close()
    assert harness.service.tasks == {}
    harness.service.delete(created["id"])

    with pytest.raises(RunNotFound):
        harness.service.snapshot(created["id"])
    with pytest.raises(RunNotFound):
        harness.service.delete(created["id"])


@pytest.mark.anyio
async def test_close_cancels_every_live_run_task_and_is_idempotent(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings, runtime_mode="hold")
    first = await harness.service.start(payload())
    second = await harness.service.start(payload())
    await asyncio.sleep(0)
    assert set(harness.service.tasks) == {first["id"], second["id"]}

    await harness.service.close()
    assert harness.service.tasks == {}
    await harness.service.close()


# -- storage isolation -------------------------------------------------------


@pytest.mark.anyio
async def test_a_storage_failure_isolates_only_its_own_analysis(tmp_path, repository, settings):
    real = SeoRepository(tmp_path)
    real.initialize()
    wrapper = StorageFailingSeoRepository(real, methods=["create_analysis"])
    harness = make_harness(tmp_path, repository, settings, seo_repository=wrapper)

    with pytest.raises(StorageError):
        await harness.service.start(payload())

    assert harness.service.list_page()["items"] == []
    assert harness.service.tasks == {}

    wrapper.failing_methods.clear()
    created = await harness.service.start(payload())
    snapshot = await wait_terminal(harness.service, created["id"])

    assert snapshot["status"] == "completed"
    assert harness.service.list_page()["items"][0]["id"] == created["id"]
    await harness.service.close()


@pytest.mark.anyio
async def test_a_failing_run_task_never_escapes_and_keeps_the_service_usable(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings, runtime_mode="crash")

    broken = await harness.service.start(payload())
    await asyncio.sleep(0.01)

    assert harness.service.tasks == {}
    assert harness.service.snapshot(broken["id"])["status"] == "running"
    assert harness.service.list_page()["items"][0]["id"] == broken["id"]

    harness.runtime.mode = "complete"
    healthy = await harness.service.start(payload())
    assert (await wait_terminal(harness.service, healthy["id"]))["status"] == "completed"
    await harness.service.close()


# -- recover and resume ------------------------------------------------------


@pytest.mark.anyio
async def test_recover_interrupts_a_run_without_a_checkpoint(tmp_path, repository, settings):
    harness = make_harness(tmp_path, repository, settings)
    analysis_id = harness.repository.create_analysis(stored_input(), ESTIMATE)
    harness.repository.save_seed_row(analysis_id, 0, status="submitting")

    harness.service.recover()

    snapshot = harness.service.snapshot(analysis_id)
    assert snapshot["status"] == "interrupted"
    assert snapshot["finished_at"] is not None
    # A row that was never submitted is never replayed after a restart.
    assert seed_states(tmp_path / "runs.sqlite3", analysis_id)[0] == ("interrupted", None)
    assert harness.service.tasks == {}
    assert harness.runtime.resumes == []
    assert harness.gateway.submitted == []
    await harness.service.close()


@pytest.mark.anyio
async def test_recover_defers_a_checkpointed_run_until_resume_pending(
    tmp_path, repository, settings,
):
    harness = make_harness(
        tmp_path, repository, settings, checkpoint_probe=lambda _analysis_id: True,
    )
    analysis_id = harness.repository.create_analysis(stored_input(), ESTIMATE)

    harness.service.recover()

    # `recover` runs while the container is built, so nothing may start yet.
    assert harness.service.tasks == {}
    assert harness.runtime.resumes == []
    assert harness.service.snapshot(analysis_id)["status"] == "running"

    harness.service.resume_pending()
    snapshot = await wait_terminal(harness.service, analysis_id)

    assert snapshot["status"] == "completed"
    assert harness.runtime.resumes == [analysis_id]
    assert harness.service.tasks == {}
    await harness.service.close()


@pytest.mark.anyio
async def test_recover_reads_the_checkpoint_of_every_running_analysis(
    tmp_path, repository, settings,
):
    probed: list[str] = []

    def probe(analysis_id: str) -> bool:
        probed.append(analysis_id)
        return False

    harness = make_harness(tmp_path, repository, settings, checkpoint_probe=probe)
    analysis_id = harness.repository.create_analysis(stored_input(), ESTIMATE)
    running = harness.repository.running_analysis_ids()

    harness.service.recover()

    assert running == (analysis_id,)
    assert probed == list(running)
    assert harness.service.snapshot(analysis_id)["status"] == "interrupted"
    await harness.service.close()


def test_recover_without_a_loop_defers_the_resume_until_a_loop_exists(
    tmp_path, repository, settings,
):
    harness = make_harness(
        tmp_path, repository, settings, checkpoint_probe=lambda _analysis_id: True,
    )
    analysis_id = harness.repository.create_analysis(stored_input(), ESTIMATE)

    # Called from a container build (no running loop), the resume is deferred.
    harness.service.recover()
    assert harness.service.tasks == {}
    assert harness.service.snapshot(analysis_id)["status"] == "running"

    async def kick() -> dict:
        harness.service.resume_pending()
        return await wait_terminal(harness.service, analysis_id)

    snapshot = asyncio.run(kick())

    assert snapshot["status"] == "completed"
    assert harness.runtime.resumes == [analysis_id]
    asyncio.run(harness.service.close())


@pytest.mark.anyio
async def test_resume_pending_waits_for_a_configured_service_llm(
    tmp_path, repository, settings,
):
    harness = make_harness(
        tmp_path,
        repository,
        settings,
        checkpoint_probe=lambda _analysis_id: True,
        llm_settings=FakeSeoSettingsService(None),
    )
    analysis_id = harness.repository.create_analysis(stored_input(), ESTIMATE)
    harness.service.recover()

    harness.service.resume_pending()

    assert harness.runtime.resumes == []
    assert harness.service.tasks == {}
    assert harness.service.snapshot(analysis_id)["status"] == "running"
    await harness.service.close()


# -- runtime wiring -----------------------------------------------------------


def test_the_container_builds_the_service_over_the_agent_runtime(tmp_path):
    from app.api.deps import build_container
    from app.core.config import Settings
    from app.domain.seo_tools import SeoBudget
    from app.integrations.site_fetcher import HttpxSiteFetcher
    from app.service.seo_agents import SeoAgentRuntime, checkpoint_path

    container = build_container(Settings(config_dir=tmp_path), secrets=MemorySecrets())

    try:
        service = container.seo_service
        assert isinstance(service, SeoService)
        assert service.repository is container.seo
        assert service.yandex_settings is container.search_settings
        assert service.connections is container.connections
        assert service.llm_settings is container.seo_settings
        assert isinstance(service.runtime, SeoAgentRuntime)
        assert callable(service.runtime.checkpointer)
        assert service.checkpoint_probe is not None
        assert service.checkpoint_probe("нет такого") is False

        # Nothing is configured in this temporary directory, so the container
        # still builds and no run could start.
        assert container.seo_settings.build_agent_model() is None
        assert not checkpoint_path(tmp_path).exists()

        toolbox = service.runtime.toolbox_factory(
            "analysis", stored_input(), SeoBudget.for_connections(1),
        )
        assert isinstance(toolbox.fetcher, HttpxSiteFetcher)
        assert toolbox.fetcher.client is container.search_client
        assert toolbox.gateway is None
        assert toolbox.model_name == "seo-llm"
    finally:
        asyncio.run(container.search_client.aclose())


def test_the_injected_runtime_and_model_replace_the_built_ones(tmp_path):
    from app.api.deps import build_container
    from app.core.config import Settings

    fake_runtime = FakeSeoAgentRuntime()
    injected_settings = tool_calling_settings("injected-model")
    container = build_container(
        Settings(config_dir=tmp_path),
        secrets=MemorySecrets(),
        seo_agent_runtime=fake_runtime,
        seo_settings_service=injected_settings,
    )

    try:
        assert container.seo_service.runtime is fake_runtime
        assert container.seo_service.llm_settings is injected_settings
        assert container.seo_settings is injected_settings
    finally:
        asyncio.run(container.search_client.aclose())


def test_a_service_llm_saved_after_the_container_build_reaches_the_next_run(tmp_path):
    """The deployment flow the application documents: keys come after boot.

    The container is built while nothing is configured, so the runtime holds the
    stand-in; the settings service is its provider, and the adapter it answers
    after the save — an LLM entered in the interface minutes later — is the one
    the next run calls instead of the state of the boot.
    """
    from app.api.deps import build_container
    from app.core.config import Settings
    from app.integrations.seo_llm import LangChainSeoLlmClient

    container = build_container(Settings(config_dir=tmp_path), secrets=MemorySecrets())

    try:
        runtime = container.seo_service.runtime
        assert container.seo_settings.build_agent_model() is None

        # «Настройки API» → «SEO-анализ»: the user saves the service LLM now.
        container.seo_settings.update(
            {
                "endpoint": "https://api.deepseek.com/chat/completions",
                "model": "deepseek-flash",
                "api_key": "sk-test",
            },
        )

        model = runtime.model_provider()
        assert isinstance(model, LangChainSeoLlmClient)
        assert model.model == "deepseek-flash"
        asyncio.run(model.aclose())
    finally:
        asyncio.run(container.search_client.aclose())
