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


@pytest.mark.anyio
@pytest.mark.parametrize("failed_branch", ["model", "search"])
async def test_storage_failure_stops_paid_work_and_reports_unavailable(
    tmp_path, repository, settings, failed_branch,
):
    class SlowGateway(FakeGateway):
        async def submit(self, prompt, region):
            await asyncio.sleep(0.002)
            return await super().submit(prompt, region)

    gateway = SlowGateway(polls_before_answer=0)
    runs, factory, search = make_runs(tmp_path, repository, settings, gateway)

    def fail(*_args):
        raise StorageError("storage unavailable")

    if failed_branch == "model":
        runs.repository.save_model = fail
    else:
        runs.repository.save_search = fail
    payload = {"brand": "Ромашка", "domain": "example.ru",
               "prompts_text": "\n".join(f"вопрос {index}" for index in range(20)),
               "provider_ids": ["gigachat"], "regions": [1, 213, 2, 54, 65]}
    created = await runs.start(payload)
    for _ in range(200):
        if runs.stopping.is_set():
            break
        await asyncio.sleep(0.001)
    assert runs.stopping.is_set()
    submitted = len(gateway.submitted)
    await asyncio.sleep(0.05)
    assert len(gateway.submitted) == submitted
    with pytest.raises(StorageError):
        runs.snapshot(created["id"])
    provider_calls = len(factory.prompts)
    with pytest.raises(StorageError):
        await runs.start(payload)
    assert len(factory.prompts) == provider_calls
    await runs.close()
    await search.close()


@pytest.mark.anyio
async def test_branch_error_write_failure_degrades_the_run_service(tmp_path, repository, settings):
    runs, _factory, search = make_runs(tmp_path, repository, settings)

    def fail(*_args):
        raise StorageError("storage unavailable")

    runs.repository.fail_pending_branch = fail
    payload = {"brand": "Ромашка", "domain": "example.ru", "prompts_text": "цветы",
               "provider_ids": ["gigachat"], "regions": [1]}
    with pytest.raises(StorageError):
        await runs.start(payload)
    assert runs.stopping.is_set()
    with pytest.raises(StorageError):
        await runs.start(payload)
    await runs.close()
    await search.close()


@pytest.mark.anyio
async def test_read_failure_cancels_pending_paid_search(tmp_path, repository, settings):
    class SlowGateway(FakeGateway):
        async def submit(self, prompt, region):
            await asyncio.sleep(0.002)
            return await super().submit(prompt, region)

    gateway = SlowGateway(polls_before_answer=0)
    runs, _factory, search = make_runs(tmp_path, repository, settings, gateway)
    payload = {"domain": "example.ru", "prompts_text": "\n".join(f"вопрос {i}" for i in range(20)),
               "provider_ids": [], "regions": [1, 213, 2, 54, 65]}
    created = await runs.start(payload)

    def fail(*_args):
        raise StorageError("storage unavailable")

    runs.repository.get = fail
    with pytest.raises(StorageError):
        runs.snapshot(created["id"])
    assert runs.stopping.is_set()
    submitted = len(gateway.submitted)
    await asyncio.sleep(0.05)
    assert len(gateway.submitted) == submitted
    await runs.close()
    await search.close()


@pytest.mark.anyio
async def test_search_storage_failure_cancels_waiting_submissions_before_yield(tmp_path, repository, settings):
    release_waiters = asyncio.Event()

    class GatedGateway(FakeGateway):
        async def submit(self, prompt, region):
            if region == 1:
                await asyncio.sleep(0)
            else:
                await release_waiters.wait()
            return await super().submit(prompt, region)

    gateway = GatedGateway(polls_before_answer=0)
    runs, _factory, search = make_runs(tmp_path, repository, settings, gateway)

    def fail(*_args):
        release_waiters.set()
        raise StorageError("storage unavailable")

    runs.repository.save_search = fail
    created = await runs.start({
        "brand": "Ромашка", "domain": "example.ru", "prompts_text": "цветы",
        "provider_ids": [], "regions": [1, 213, 2, 54, 65],
    })
    for _ in range(100):
        if runs.stopping.is_set():
            break
        await asyncio.sleep(0)
    assert runs.stopping.is_set()
    for _ in range(5):
        await asyncio.sleep(0)
    assert gateway.submitted == [("цветы", 1)]
    with pytest.raises(StorageError):
        runs.snapshot(created["id"])
    await runs.close()
    await search.close()
