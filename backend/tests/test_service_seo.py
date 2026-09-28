"""The SEO orchestrator: six stages, degradation, lifecycle, and resume.

Every collaborator is a fake, so the suite proves the stage order and the
"no paid call before stage 3 is done" guarantee without ever reaching a paid
external API.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.core.errors import (
    ConfigurationError,
    ProviderError,
    RunConflict,
    RunNotFound,
    StorageError,
    ValidationError,
)
from app.db.search_settings import SearchSettingsRepository
from app.db.seo import SeoRepository
from app.db.seo_settings import SeoSettingsRepository
from app.domain.seo import (
    Candidate,
    GeneratedQuery,
    QueryFlags,
    SeoInput,
    normalize_seo_request,
)
from app.service.connections import ConnectionService
from app.service.search import SearchService
from app.service.search_settings import SearchSettingsService
from app.service.seo import SeoService
from tests.fakes import (
    DEFAULT_SEO_DOCUMENTS,
    DEFAULT_SEO_PAGE,
    SEO_MENTION_ANSWER,
    FakeSiteFetcher,
    MemorySecrets,
    ScriptedSeoGateway,
    ScriptedSeoLlmClient,
    SeoProviderFactorySpy,
    StorageFailingSeoRepository,
)

REGION = 225
ENDPOINT = "https://api.example.com/v1/chat/completions"
SEEDS = ("букет цветов", "доставка цветов", "розы")
SITE_FACTS = json.dumps({"company_name": "Ромашка", "services": ["Свадьбы"]}, ensure_ascii=False)
SUMMARY = "Итог: сайт виден в Яндексе и упоминается моделями."
QUERY_TEXTS = (
    "купить букет недорого",
    "Ромашка доставка цветов",
    "rival.ru отзывы",
    "как выбрать букет",
    "сравнение конкурентов букеты",
    "доставка роз цена",
)
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


def generated_payload(texts: tuple[str, ...] = QUERY_TEXTS, *, service: str = "Букеты") -> str:
    return json.dumps(
        {
            "queries": [
                {
                    "query": text,
                    "category": "comparative" if "сравнение" in text else "commercial",
                    "service": service,
                }
                for text in texts
            ]
        },
        ensure_ascii=False,
    )


def stored_query(text: str, index: int) -> GeneratedQuery:
    return GeneratedQuery(
        text=text,
        category="commercial",
        service="Букеты",
        flags=QueryFlags(
            mentions_company_name=index == 0,
            mentions_company_host=False,
            mentions_candidate_host=False,
            branded=index == 0,
        ),
    )


def stored_input(**overrides: object) -> SeoInput:
    return normalize_seo_request(payload(**overrides))


ESTIMATE = {"search_upper": 23, "model_upper": 20, "generated_limit": 20, "connections": 1}


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
    fetcher: FakeSiteFetcher | None = None,
    llm_responses: list[Any] | None = None,
    llm_factory: Any = None,
    gateway: ScriptedSeoGateway | None = None,
    yandex_enabled: bool = True,
    yandex_configured: bool = True,
    provider_factory: SeoProviderFactorySpy | None = None,
    seo_repository: Any = None,
    configured_connections: tuple[tuple[str, str], ...] = (("gigachat", "test-key"),),
    poll_interval: float = 0.0,
    max_requests_per_second: int = 0,
) -> SimpleNamespace:
    connections = ConnectionService(connection_repository, settings)
    for connection_id, key in configured_connections:
        connections.save({"api_key": key}, connection_id)
    repository = seo_repository
    if repository is None:
        repository = SeoRepository(tmp_path)
        repository.initialize()
    llm_settings = SeoSettingsRepository(
        tmp_path,
        MemorySecrets(),
        env_endpoint=ENDPOINT,
        env_model="seo-model",
        env_api_key="seo-key",
        service_name="test",
    )
    fetcher = fetcher if fetcher is not None else FakeSiteFetcher()
    responses = llm_responses if llm_responses is not None else [SITE_FACTS, generated_payload(), SUMMARY]
    shared_calls: list[tuple[str, str]] = []

    def default_factory() -> ScriptedSeoLlmClient:
        # Every run captures its own client, exactly as the container does.
        return ScriptedSeoLlmClient(responses, calls=shared_calls)

    llm = default_factory()
    gateway = gateway if gateway is not None else ScriptedSeoGateway()
    factory = provider_factory if provider_factory is not None else SeoProviderFactorySpy()
    search_settings = make_search_settings(
        tmp_path, gateway if yandex_configured else NO_GATEWAY, enabled=yandex_enabled,
    )
    service = SeoService(
        repository,
        llm_settings,
        llm_factory if llm_factory is not None else default_factory,
        fetcher,
        search_settings,
        connections,
        factory,
        max_model_concurrency=5,
        poll_interval=poll_interval,
        max_poll_interval=poll_interval,
        max_requests_per_second=max_requests_per_second,
    )
    return SimpleNamespace(
        service=service,
        repository=repository,
        llm=llm,
        fetcher=fetcher,
        gateway=gateway,
        factory=factory,
        connections=connections,
        search_settings=search_settings,
    )


async def wait_for(service: SeoService, analysis_id: str, *, timeout: float = 5.0) -> dict:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        snapshot = service.snapshot(analysis_id)
        if snapshot["status"] in TERMINAL:
            return snapshot
        await asyncio.sleep(0.001)
    raise AssertionError(f"analysis stayed {service.snapshot(analysis_id)['status']}")


def stage_statuses(snapshot: dict) -> dict[int, str]:
    return {stage["stage"]: stage["status"] for stage in snapshot["stages"]}


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


def row_statuses(service: SeoService, analysis_id: str, kind: str) -> list[str]:
    return [row["status"] for row in service.rows_page(analysis_id, kind)["items"]]


# -- happy path --------------------------------------------------------------


@pytest.mark.anyio
async def test_happy_path_runs_six_stages_in_order(tmp_path, repository, settings):
    observed_gateway: list[dict[int, str]] = []
    observed_models: list[dict[int, str]] = []
    harness_id: dict[str, str] = {}
    harness: SimpleNamespace | None = None

    def gateway_probe(prompt: str, region: int) -> None:
        assert region == REGION
        if prompt not in SEEDS and harness is not None:
            observed_gateway.append(stage_statuses(harness.service.snapshot(harness_id["id"])))

    def model_probe(connection_id: str, prompt: str) -> None:
        if harness is not None:
            observed_models.append(stage_statuses(harness.service.snapshot(harness_id["id"])))

    harness = make_harness(
        tmp_path,
        repository,
        settings,
        gateway=ScriptedSeoGateway(hook=gateway_probe),
        provider_factory=SeoProviderFactorySpy(hook=model_probe),
    )

    created = await harness.service.start(payload())
    harness_id["id"] = created["id"]

    assert created["status"] == "running"
    assert created["estimate"] == {
        "search_upper": 23,
        "model_upper": 20,
        "generated_limit": 20,
        "connections": 1,
    }

    snapshot = await wait_for(harness.service, created["id"])

    assert snapshot["status"] == "completed"
    assert [stage["stage"] for stage in snapshot["stages"]] == [1, 2, 3, 4, 5, 6]
    assert [stage["status"] for stage in snapshot["stages"]] == ["done"] * 6

    # Services: entered ones first, site services appended after the merge.
    assert snapshot["services"] == ["Букеты", "Доставка", "Свадьбы"]
    assert snapshot["company_name"] == "Ромашка"
    assert [page["url"] for page in snapshot["pages"]] == [DEFAULT_SEO_PAGE.url]

    # Candidates are ranked by host and marked recurring across the three SERPs.
    assert [candidate["host"] for candidate in snapshot["candidates"]] == ["rival.ru"]
    assert snapshot["candidates"][0]["occurrences"] == 3
    assert snapshot["candidates"][0]["recurring"] is True
    assert snapshot["candidates"][0]["title"] == "Соперник — букеты"

    # Generated queries keep their server-computed flags.
    queries = {query["text"]: query["flags"] for query in snapshot["queries"]}
    assert len(queries) == len(QUERY_TEXTS)
    assert queries["Ромашка доставка цветов"]["branded"] is True
    assert queries["rival.ru отзывы"]["mentions_candidate_host"] is True
    assert queries["купить букет недорого"]["branded"] is False

    # Both branches wrote one row per generated query, and the report is ready.
    assert row_statuses(harness.service, created["id"], "search") == ["found"] * len(QUERY_TEXTS)
    assert row_statuses(harness.service, created["id"], "model") == ["found"] * len(QUERY_TEXTS)
    model_rows = harness.service.rows_page(created["id"], "model")["items"]
    assert all(row["answer"] == SEO_MENTION_ANSWER for row in model_rows)
    assert all(row["name_mentioned"] and row["host_mentioned"] for row in model_rows)
    search_rows = harness.service.rows_page(created["id"], "search")["items"]
    assert all(row["site_position"] == 2 for row in search_rows)
    assert all(row["site_url"] == "https://example.ru/page" for row in search_rows)
    assert snapshot["summary"] == SUMMARY
    assert snapshot["readiness"]["report_ready"] is True
    assert snapshot["aggregates"]["site"]["search"]["overall"]["denominator"] == len(QUERY_TEXTS)

    # The service LLM was asked exactly three times: facts, queries, summary.
    assert len(harness.llm.calls) == 3
    # The three key queries are the first paid Yandex calls, and nothing paid
    # happened before stage 3 finished.
    assert [prompt for prompt, _ in harness.gateway.submitted[:3]] == list(SEEDS)
    assert len(harness.gateway.submitted) == 3 + len(QUERY_TEXTS)
    assert observed_gateway, "the generated-query branch never submitted"
    assert observed_models, "the model branch never answered"
    assert all(stages[3] == "done" for stages in observed_gateway)
    assert all(stages[3] == "done" for stages in observed_models)
    assert all(provider.closed for provider in harness.factory.providers.values())
    await harness.service.close()


@pytest.mark.anyio
async def test_estimate_counts_every_selected_connection(tmp_path, repository, settings):
    harness = make_harness(
        tmp_path,
        repository,
        settings,
        configured_connections=(("gigachat", "key-1"), ("deepseek", "key-2")),
        llm_responses=[SITE_FACTS, generated_payload(), SUMMARY],
    )

    created = await harness.service.start(payload(connection_ids=["gigachat", "deepseek"]))

    assert created["estimate"] == {
        "search_upper": 23, "model_upper": 40, "generated_limit": 20, "connections": 2,
    }
    snapshot = await wait_for(harness.service, created["id"])
    assert snapshot["status"] == "completed"
    assert len(harness.factory.providers) == 2
    assert len(harness.service.rows_page(created["id"], "model")["items"]) == 2 * len(QUERY_TEXTS)
    await harness.service.close()


# -- start rejections --------------------------------------------------------


@pytest.mark.anyio
async def test_start_rejects_malformed_input_before_any_side_effect(tmp_path, repository, settings):
    harness = make_harness(tmp_path, repository, settings)

    with pytest.raises(ValidationError):
        await harness.service.start(payload(seeds=["один запрос"]))

    assert harness.service.list_page()["items"] == []
    assert harness.gateway.submitted == []
    assert harness.llm.calls == []
    await harness.service.close()


@pytest.mark.anyio
async def test_start_rejects_a_disabled_or_unconfigured_yandex(tmp_path, repository, settings):
    disabled = make_harness(tmp_path, repository, settings, yandex_enabled=False)
    with pytest.raises(ConfigurationError) as raised:
        await disabled.service.start(payload())
    assert str(raised.value) == "Поиск Яндекса выключен"
    assert disabled.service.list_page()["items"] == []
    await disabled.service.close()

    without_gateway = make_harness(
        tmp_path, repository, settings, yandex_configured=False,
    )
    with pytest.raises(ConfigurationError) as raised:
        await without_gateway.service.start(payload())
    assert str(raised.value) == "Не заданы ключ и каталог для поиска Яндекса"
    assert without_gateway.service.list_page()["items"] == []
    await without_gateway.service.close()


@pytest.mark.anyio
async def test_start_requires_a_configured_service_llm(tmp_path, repository, settings):
    harness = make_harness(tmp_path, repository, settings, llm_factory=lambda: None)

    with pytest.raises(ConfigurationError):
        await harness.service.start(payload())

    assert harness.service.list_page()["items"] == []
    assert harness.gateway.submitted == []
    await harness.service.close()


@pytest.mark.anyio
async def test_start_rejects_unknown_and_unconfigured_connections(tmp_path, repository, settings):
    harness = make_harness(tmp_path, repository, settings)

    with pytest.raises(ValidationError):
        await harness.service.start(payload(connection_ids=["missing"]))
    with pytest.raises(ConfigurationError) as raised:
        await harness.service.start(payload(connection_ids=["deepseek"]))
    assert str(raised.value) == "Добавьте API-ключ в настройках подключения"

    assert harness.service.list_page()["items"] == []
    assert harness.gateway.submitted == []
    assert harness.llm.calls == []
    await harness.service.close()


# -- fatal stages ------------------------------------------------------------


@pytest.mark.anyio
async def test_crawl_error_is_fatal_before_any_paid_call(tmp_path, repository, settings):
    harness = make_harness(
        tmp_path,
        repository,
        settings,
        fetcher=FakeSiteFetcher(error=ProviderError("Не удалось загрузить сайт")),
    )

    created = await harness.service.start(payload())
    snapshot = await wait_for(harness.service, created["id"])

    assert snapshot["status"] == "failed"
    assert stage_statuses(snapshot)[1] == "error"
    assert snapshot["stages"][0]["error"] == "Не удалось обойти сайт"
    assert harness.gateway.submitted == []
    assert harness.factory.keys == []
    assert harness.llm.calls == []
    await harness.service.close()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "responses,expected_calls",
    [
        (["{not json", "{still not json"], 2),
        ([ProviderError("Сервис модели временно недоступен"), "{not json"], 1),
    ],
)
async def test_site_facts_llm_error_is_fatal_after_one_repeat(
    tmp_path, repository, settings, responses, expected_calls,
):
    harness = make_harness(tmp_path, repository, settings, llm_responses=responses)

    created = await harness.service.start(payload())
    snapshot = await wait_for(harness.service, created["id"])

    assert snapshot["status"] == "failed"
    assert stage_statuses(snapshot)[1] == "error"
    assert len(harness.llm.calls) == expected_calls
    assert harness.gateway.submitted == []
    assert harness.factory.keys == []
    await harness.service.close()


@pytest.mark.anyio
async def test_too_few_generated_queries_is_fatal_after_one_repeat(tmp_path, repository, settings):
    too_few = generated_payload(QUERY_TEXTS[:4])
    harness = make_harness(
        tmp_path, repository, settings, llm_responses=[SITE_FACTS, too_few, too_few],
    )

    created = await harness.service.start(payload())
    snapshot = await wait_for(harness.service, created["id"])

    assert snapshot["status"] == "failed"
    assert stage_statuses(snapshot)[3] == "error"
    assert len(harness.llm.calls) == 3
    # Only the three key searches were paid for; nothing reached stage 4.
    assert harness.gateway.submitted == [(seed, REGION) for seed in SEEDS]
    assert harness.factory.keys == []
    assert harness.service.rows_page(created["id"], "search")["items"] == []
    await harness.service.close()


# -- degradation -------------------------------------------------------------


@pytest.mark.anyio
async def test_all_key_searches_failing_still_produces_a_report(tmp_path, repository, settings):
    harness = make_harness(
        tmp_path, repository, settings, gateway=ScriptedSeoGateway(fail_submits=SEEDS),
    )

    created = await harness.service.start(payload())
    snapshot = await wait_for(harness.service, created["id"])

    assert snapshot["status"] == "completed"
    statuses = stage_statuses(snapshot)
    assert statuses[2] == "error"
    assert snapshot["stages"][1]["error"] == "Не удалось получить ключевые выдачи Яндекса"
    assert snapshot["candidates"] == []
    assert statuses[3] == "done" and statuses[6] == "done"
    # No key search was submitted; only the generated queries were paid for.
    assert [prompt for prompt, _ in harness.gateway.submitted] == list(QUERY_TEXTS)
    assert len(harness.service.rows_page(created["id"], "search")["items"]) == len(QUERY_TEXTS)
    assert snapshot["readiness"]["report_ready"] is True
    await harness.service.close()


@pytest.mark.anyio
async def test_one_failing_search_row_does_not_block_the_other_rows(tmp_path, repository, settings):
    failing = QUERY_TEXTS[-1]
    harness = make_harness(
        tmp_path, repository, settings, gateway=ScriptedSeoGateway(fail_results={failing}),
    )

    created = await harness.service.start(payload())
    snapshot = await wait_for(harness.service, created["id"])

    assert snapshot["status"] == "completed"
    rows = {
        row["query"]: row["status"]
        for row in harness.service.rows_page(created["id"], "search")["items"]
    }
    assert rows[failing] == "error"
    assert all(status == "found" for query, status in rows.items() if query != failing)
    assert row_statuses(harness.service, created["id"], "model") == ["found"] * len(QUERY_TEXTS)
    assert snapshot["aggregates"]["counts"]["search_errors"] == 1
    await harness.service.close()


@pytest.mark.anyio
async def test_one_failing_connection_does_not_block_other_connections_or_yandex(
    tmp_path, repository, settings,
):
    harness = make_harness(
        tmp_path,
        repository,
        settings,
        provider_factory=SeoProviderFactorySpy(failing_ids=["gigachat"]),
        configured_connections=(("gigachat", "key-1"), ("deepseek", "key-2")),
    )

    created = await harness.service.start(payload(connection_ids=["gigachat", "deepseek"]))
    snapshot = await wait_for(harness.service, created["id"])

    assert snapshot["status"] == "completed"
    by_connection: dict[str, list[str]] = {}
    for row in harness.service.rows_page(created["id"], "model")["items"]:
        by_connection.setdefault(row["connection_id"], []).append(row["status"])
    assert by_connection["gigachat"] == ["error"] * len(QUERY_TEXTS)
    assert by_connection["deepseek"] == ["found"] * len(QUERY_TEXTS)
    assert row_statuses(harness.service, created["id"], "search") == ["found"] * len(QUERY_TEXTS)
    await harness.service.close()


@pytest.mark.anyio
async def test_a_summary_failure_still_completes_the_report(tmp_path, repository, settings):
    harness = make_harness(
        tmp_path,
        repository,
        settings,
        llm_responses=[SITE_FACTS, generated_payload(), ProviderError("Сервис модели недоступен")],
    )

    created = await harness.service.start(payload())
    snapshot = await wait_for(harness.service, created["id"])

    assert snapshot["status"] == "completed"
    assert stage_statuses(snapshot)[5] == "error"
    assert snapshot["summary"] is None
    assert snapshot["readiness"]["report_ready"] is True
    assert snapshot["aggregates"]["counts"]["search_rows"] == len(QUERY_TEXTS)
    await harness.service.close()


# -- lifecycle ---------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_during_polling_stops_new_submissions(tmp_path, repository, settings):
    harness = make_harness(
        tmp_path,
        repository,
        settings,
        gateway=ScriptedSeoGateway(never_finishing=SEEDS),
        poll_interval=0.001,
    )

    created = await harness.service.start(payload())
    for _ in range(500):
        if len(harness.gateway.submitted) == len(SEEDS):
            break
        await asyncio.sleep(0.001)

    cancelled = harness.service.cancel(created["id"])

    assert cancelled["status"] == "cancelled"
    assert cancelled["finished_at"] is not None
    submitted = len(harness.gateway.submitted)
    await asyncio.sleep(0.02)
    assert len(harness.gateway.submitted) == submitted == len(SEEDS)
    assert harness.factory.keys == []
    assert harness.service.snapshot(created["id"])["status"] == "cancelled"
    await harness.service.close()


@pytest.mark.anyio
async def test_delete_works_only_in_a_terminal_state(tmp_path, repository, settings):
    harness = make_harness(
        tmp_path,
        repository,
        settings,
        gateway=ScriptedSeoGateway(never_finishing=SEEDS),
        poll_interval=0.001,
    )
    created = await harness.service.start(payload())
    with pytest.raises(RunConflict):
        harness.service.delete(created["id"])

    harness.service.cancel(created["id"])
    harness.gateway.never_finishing.clear()

    saved = await harness.service.start(payload())
    snapshot = await wait_for(harness.service, saved["id"])
    assert snapshot["status"] == "completed"

    harness.service.delete(saved["id"])
    with pytest.raises(RunNotFound):
        harness.service.snapshot(saved["id"])
    with pytest.raises(RunNotFound):
        harness.service.delete(saved["id"])
    await harness.service.close()


@pytest.mark.anyio
async def test_a_storage_failure_isolates_only_its_own_analysis(tmp_path, repository, settings):
    real = SeoRepository(tmp_path)
    real.initialize()
    wrapper = StorageFailingSeoRepository(real, methods=["save_search_row"])
    harness = make_harness(tmp_path, repository, settings, seo_repository=wrapper)

    broken = await harness.service.start(payload())
    snapshot = await wait_for(harness.service, broken["id"])

    assert snapshot["status"] == "failed"
    assert harness.service.list_page()["items"][0]["id"] == broken["id"]

    wrapper.failing_methods.clear()
    healthy = await harness.service.start(payload())
    healed = await wait_for(harness.service, healthy["id"])
    assert healed["status"] == "completed"
    assert healed["readiness"]["report_ready"] is True
    assert harness.service.list_page()["items"][0]["id"] == healthy["id"]
    await harness.service.close()


# -- recover -----------------------------------------------------------------


@pytest.mark.anyio
async def test_recover_resumes_submitted_seeds_without_resubmitting_them(tmp_path, repository, settings):
    harness = make_harness(
        tmp_path, repository, settings, llm_responses=[generated_payload(), SUMMARY],
    )
    analysis_id = harness.repository.create_analysis(stored_input(), ESTIMATE)
    harness.repository.update_stage(analysis_id, 1, "done")
    harness.repository.save_site_facts(
        analysis_id,
        "Ромашка",
        ["Букеты", "Доставка"],
        [(DEFAULT_SEO_PAGE.url, DEFAULT_SEO_PAGE.title)],
    )
    harness.repository.update_stage(analysis_id, 2, "running")
    harness.repository.save_seed_row(analysis_id, 0, status="waiting", operation_id="seo-operation-1")
    harness.repository.save_seed_row(analysis_id, 1, status="submitting")

    harness.service.recover()
    snapshot = await wait_for(harness.service, analysis_id)

    assert snapshot["status"] == "completed"
    # The already-paid seed was polled again, never submitted again.
    submitted_prompts = [prompt for prompt, _ in harness.gateway.submitted]
    assert all(prompt not in SEEDS for prompt in submitted_prompts)
    assert len(submitted_prompts) == len(QUERY_TEXTS)
    assert seed_states(tmp_path / "runs.sqlite3", analysis_id) == {
        0: ("found", "seo-operation-1"),
        1: ("interrupted", None),
    }
    assert snapshot["candidates"][0]["host"] == "rival.ru"
    assert snapshot["readiness"]["report_ready"] is True
    await harness.service.close()


@pytest.mark.anyio
async def test_recover_polls_submitted_search_rows_and_finishes_the_report(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings, llm_responses=[SUMMARY])
    analysis_id = harness.repository.create_analysis(stored_input(), ESTIMATE)
    harness.repository.update_stage(analysis_id, 1, "done")
    harness.repository.update_stage(analysis_id, 2, "done")
    harness.repository.save_site_facts(
        analysis_id, "Ромашка", ["Букеты", "Доставка"], [(DEFAULT_SEO_PAGE.url, "")],
    )
    harness.repository.replace_candidates(
        analysis_id, (Candidate("rival.ru", "Соперник", 3, 1.0, (0, 1, 2), True),),
    )
    harness.repository.replace_queries(
        analysis_id, [stored_query(text, index) for index, text in enumerate(QUERY_TEXTS)],
    )
    harness.repository.update_stage(analysis_id, 3, "done")
    harness.repository.update_stage(analysis_id, 4, "running")
    harness.repository.save_search_row(analysis_id, 0, status="waiting", operation_id="op-0")
    harness.repository.save_model_row(analysis_id, "gigachat", "GigaChat", 0, status="pending")

    harness.service.recover()
    snapshot = await wait_for(harness.service, analysis_id)

    assert snapshot["status"] == "completed"
    assert harness.gateway.submitted == []
    assert harness.factory.keys == []
    rows = harness.service.rows_page(analysis_id, "search")["items"]
    assert [row["status"] for row in rows] == ["found"]
    assert rows[0]["site_position"] == 2
    assert rows[0]["site_url"] == "https://example.ru/page"
    # The queued model call is interrupted, never replayed.
    model_rows = harness.service.rows_page(analysis_id, "model")["items"]
    assert [row["status"] for row in model_rows] == ["interrupted"]
    assert len(harness.llm.calls) == 1  # only the summary
    assert snapshot["summary"] == SUMMARY
    assert snapshot["readiness"]["report_ready"] is True
    await harness.service.close()


@pytest.mark.anyio
async def test_recover_interrupts_an_analysis_with_nothing_to_resume(tmp_path, repository, settings):
    harness = make_harness(tmp_path, repository, settings)
    analysis_id = harness.repository.create_analysis(stored_input(), ESTIMATE)

    harness.service.recover()

    snapshot = harness.service.snapshot(analysis_id)
    assert snapshot["status"] == "interrupted"
    assert snapshot["finished_at"] is not None
    assert harness.gateway.submitted == []
    assert harness.llm.calls == []
    assert harness.service.tasks == {}
    await harness.service.close()


@pytest.mark.anyio
async def test_recover_completes_an_analysis_whose_report_is_ready(tmp_path, repository, settings):
    harness = make_harness(tmp_path, repository, settings)
    analysis_id = harness.repository.create_analysis(stored_input(), ESTIMATE)
    harness.repository.update_stage(analysis_id, 6, "done")

    harness.service.recover()

    snapshot = harness.service.snapshot(analysis_id)
    assert snapshot["status"] == "completed"
    assert snapshot["readiness"]["report_ready"] is True
    assert harness.gateway.submitted == []
    await harness.service.close()


def test_recover_without_a_loop_defers_the_resume_until_a_loop_exists(tmp_path, repository, settings):
    harness = make_harness(tmp_path, repository, settings, llm_responses=[generated_payload(), SUMMARY])
    analysis_id = harness.repository.create_analysis(stored_input(), ESTIMATE)
    harness.repository.update_stage(analysis_id, 1, "done")
    harness.repository.save_site_facts(analysis_id, "Ромашка", ["Букеты"], [(DEFAULT_SEO_PAGE.url, "")])
    harness.repository.update_stage(analysis_id, 2, "running")
    harness.repository.save_seed_row(analysis_id, 0, status="waiting", operation_id="seo-operation-9")

    # Called from a container build (no running loop), the resume is deferred.
    harness.service.recover()
    assert harness.service.tasks == {}
    assert harness.service.snapshot(analysis_id)["status"] == "running"

    async def kick() -> dict:
        harness.service.resume_pending()
        return await wait_for(harness.service, analysis_id)

    snapshot = asyncio.run(kick())

    assert snapshot["status"] == "completed"
    assert harness.gateway.submitted and all(prompt not in SEEDS for prompt, _ in harness.gateway.submitted)
    asyncio.run(harness.service.close())


# -- snapshot and rows delegates ---------------------------------------------


@pytest.mark.anyio
async def test_snapshot_and_pages_delegate_to_the_repository(tmp_path, repository, settings):
    harness = make_harness(tmp_path, repository, settings)

    created = await harness.service.start(payload())
    snapshot = await wait_for(harness.service, created["id"])

    assert harness.service.snapshot(created["id"]) == snapshot
    page = harness.service.list_page()
    assert page["items"][0]["id"] == created["id"]
    assert len(harness.service.rows_page(created["id"], "search")["items"]) == len(QUERY_TEXTS)
    assert len(harness.service.rows_page(created["id"], "model")["items"]) == len(QUERY_TEXTS)
    with pytest.raises(RunNotFound):
        harness.service.snapshot("нет такого")
    with pytest.raises(ValidationError):
        harness.service.rows_page(created["id"], "unknown")
    await harness.service.close()


@pytest.mark.anyio
async def test_a_storage_failure_while_reading_does_not_stop_other_analyses(
    tmp_path, repository, settings,
):
    real = SeoRepository(tmp_path)
    real.initialize()
    wrapper = StorageFailingSeoRepository(real, methods=["snapshot"])
    harness = make_harness(tmp_path, repository, settings, seo_repository=wrapper)
    analysis_id = harness.repository.create_analysis(stored_input(), ESTIMATE)

    with pytest.raises(StorageError):
        harness.service.snapshot(analysis_id)

    wrapper.failing_methods.clear()
    assert harness.service.snapshot(analysis_id)["status"] == "running"
    await harness.service.close()


# -- document titles travel into the search rows ------------------------------


@pytest.mark.anyio
async def test_candidate_titles_come_from_the_serp_documents(tmp_path, repository, settings):
    harness = make_harness(tmp_path, repository, settings)

    created = await harness.service.start(payload())
    snapshot = await wait_for(harness.service, created["id"])

    assert snapshot["candidates"][0]["title"] == DEFAULT_SEO_DOCUMENTS[0].title
    await harness.service.close()


# -- runtime wiring -----------------------------------------------------------


def test_the_container_builds_the_seo_service_over_the_shared_client(tmp_path):
    from app.api.deps import build_container
    from app.core.config import Settings
    from app.integrations.site_fetcher import HttpxSiteFetcher

    container = build_container(Settings(config_dir=tmp_path), secrets=MemorySecrets())

    try:
        assert isinstance(container.seo_service, SeoService)
        assert container.seo_service.repository is container.seo
        assert container.seo_service.yandex_settings is container.search_settings
        assert container.seo_service.connections is container.connections
        fetcher = container.seo_service.fetcher
        assert isinstance(fetcher, HttpxSiteFetcher)
        assert fetcher.client is container.search_client
        # Nothing is configured in this temporary directory, so no client is built.
        assert container.seo_service.llm_factory() is None
    finally:
        asyncio.run(container.search_client.aclose())
