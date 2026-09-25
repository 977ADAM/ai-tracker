"""One durable run coordinates model and search branches."""

from __future__ import annotations

import asyncio

import pytest

from app.core.errors import StorageError, ValidationError
from app.db.runs import RunRepository
from app.service.checks import CheckService
from app.service.connections import ConnectionService
from app.service.runs import RunService
from app.service.search import SearchService
from tests.fakes import ProviderFactorySpy
from tests.test_service_search import FakeGateway


def make_runs(tmp_path, connection_repository, settings, gateway=None):
    connections = ConnectionService(connection_repository, settings)
    connections.save({"api_key": "test-key"}, "gigachat")
    factory = ProviderFactorySpy()
    repository = RunRepository(tmp_path)
    repository.initialize()
    search = SearchService(gateway, poll_interval=0, max_requests_per_second=0)
    return RunService(repository, CheckService(connections, factory), search), factory, search


async def finished(runs, run_id):
    for _ in range(300):
        snapshot = runs.snapshot(run_id)
        if snapshot["status"] != "pending":
            return snapshot
        await asyncio.sleep(0.001)
    raise AssertionError("run did not finish")


@pytest.mark.anyio
@pytest.mark.parametrize("providers,regions", [(["gigachat"], []), ([], [1]), (["gigachat"], [1])])
async def test_run_modes_are_durable(tmp_path, repository, settings, providers, regions):
    runs, factory, search = make_runs(tmp_path, repository, settings, FakeGateway(polls_before_answer=0))
    created = await runs.start({"brand": "Ромашка", "domain": "example.ru", "prompts_text": "цветы",
                                "provider_ids": providers, "regions": regions})
    assert created["id"]
    assert len(runs.list_page()["items"]) == 1
    saved = await finished(runs, created["id"])
    assert saved["status"] == "done"
    assert len(saved["models"]) == len(providers)
    assert len(saved["search"]) == len(regions)
    assert len(saved["summary_rows"]) == len(providers) + len(regions)
    assert len(factory.keys) == len(providers)
    await runs.close()
    await search.close()


@pytest.mark.anyio
async def test_unknown_provider_and_region_rejected_before_paid_calls(tmp_path, repository, settings):
    gateway = FakeGateway()
    runs, factory, search = make_runs(tmp_path, repository, settings, gateway)
    for provider_ids, regions in [(["missing"], [1]), (["gigachat"], [999999])]:
        with pytest.raises(ValidationError):
            await runs.start({"brand": "Ромашка", "domain": "example.ru", "prompts_text": "цветы",
                              "provider_ids": provider_ids, "regions": regions})
    assert factory.keys == []
    assert gateway.submitted == []
    assert runs.list_page()["items"] == []
    await runs.close()
    await search.close()


@pytest.mark.anyio
async def test_missing_search_credentials_marks_branch_error_and_models_continue(tmp_path, repository, settings):
    runs, _factory, search = make_runs(tmp_path, repository, settings)
    created = await runs.start({"brand": "Ромашка", "domain": "example.ru", "prompts_text": "цветы",
                                "provider_ids": ["gigachat"], "regions": [1]})
    saved = await finished(runs, created["id"])
    assert saved["models"][0]["status"] == "mentioned"
    assert saved["search"][0]["status"] == "error"
    assert saved["status"] == "done"
    await runs.close()
    await search.close()


@pytest.mark.anyio
async def test_storage_failure_prevents_external_calls(tmp_path, repository, settings):
    runs, factory, search = make_runs(tmp_path, repository, settings, FakeGateway())

    def fail(*_args):
        raise StorageError("storage unavailable")

    runs.repository.create = fail
    with pytest.raises(StorageError):
        await runs.start({"brand": "Ромашка", "domain": "example.ru", "prompts_text": "цветы",
                          "provider_ids": ["gigachat"], "regions": [1]})
    assert factory.keys == []
    assert search.gateway.submitted == []
    await runs.close()
    await search.close()
