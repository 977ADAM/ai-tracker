"""In-memory deferred search jobs: pair lifecycle, independent errors, and snapshots."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.errors import (
    ConfigurationError,
    ProviderError,
    StorageError,
    ValidationError,
)
from app.domain.search import SearchDocument
from app.service.search import AsyncRequestRateLimiter, SearchJobNotFound, SearchService

FOUND_REGION = 1
ABSENT_REGION = 213
ERROR_REGION = 65


class FakeClock:
    """A clock the test moves by hand, so retention is checked without waiting."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeGateway:
    """Answers per region: a match, no match, a failure, or never finishing."""

    def __init__(self, outcome: dict[int, str] | None = None, *, polls_before_answer: int = 1) -> None:
        self.outcome = outcome or {FOUND_REGION: "found", ABSENT_REGION: "absent", ERROR_REGION: "error"}
        self.polls_before_answer = polls_before_answer
        self.submitted: list[tuple[str, int]] = []
        self.polls: dict[str, int] = {}
        self.regions: dict[str, int] = {}

    async def submit(self, prompt: str, region: int) -> str:
        operation_id = f"op-{len(self.submitted) + 1}"
        self.submitted.append((prompt, region))
        self.regions[operation_id] = region
        return operation_id

    async def result(self, operation_id: str) -> tuple[SearchDocument, ...] | None:
        self.polls[operation_id] = self.polls.get(operation_id, 0) + 1
        if self.polls[operation_id] <= self.polls_before_answer:
            return None
        outcome = self.outcome.get(self.regions[operation_id], "absent")
        if outcome == "error":
            raise ProviderError("Поиск Яндекса завершился ошибкой")
        if outcome == "never":
            return None
        if outcome == "found":
            return (SearchDocument("https://other.ru/"), SearchDocument("https://shop.example.ru/page"))
        return (SearchDocument("https://other.ru/"),)


def payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {"domain": "example.ru", "prompts_text": "цветы", "regions": [FOUND_REGION]}
    base.update(overrides)
    return base


def service(gateway, **overrides) -> SearchService:
    options: dict[str, object] = {"poll_interval": 0, "max_requests_per_second": 0}
    options.update(overrides)
    return SearchService(gateway, **options)


async def settle(service: SearchService, job_id: str, *, rounds: int = 200) -> dict:
    """Let the scheduled work run until every pair reached a terminal state."""
    for _ in range(rounds):
        snapshot = service.snapshot(job_id)
        if snapshot["completed"] == snapshot["total"]:
            return snapshot
        await asyncio.sleep(0)
    raise AssertionError("the job never settled")


@pytest.mark.anyio
async def test_start_returns_before_any_pair_finishes():
    gateway = FakeGateway()
    search = service(gateway)

    job = await search.start(payload(regions=[FOUND_REGION, ERROR_REGION]))

    assert set(job) == {"id", "total", "status"}
    assert job["total"] == 2
    assert job["status"] == "pending"
    pending = search.snapshot(job["id"])
    assert pending["completed"] == 0
    assert {row["status"] for row in pending["results"]} <= {"submitting", "waiting"}
    await search.close()


@pytest.mark.anyio
async def test_pairs_follow_question_then_region_order():
    gateway = FakeGateway()
    search = service(gateway)

    job = await search.start(payload(prompts_text="первый\nвторой", regions=[FOUND_REGION, ABSENT_REGION]))
    snapshot = await settle(search, job["id"])

    assert gateway.submitted == [
        ("первый", FOUND_REGION),
        ("первый", ABSENT_REGION),
        ("второй", FOUND_REGION),
        ("второй", ABSENT_REGION),
    ]
    assert [(row["prompt"], row["region_id"]) for row in snapshot["results"]] == gateway.submitted
    assert [row["region_name"] for row in snapshot["results"]] == [
        "Москва и Московская область",
        "Москва",
        "Москва и Московская область",
        "Москва",
    ]
    await search.close()


@pytest.mark.anyio
async def test_a_found_pair_reports_its_rank_and_link():
    gateway = FakeGateway()
    search = service(gateway)

    job = await search.start(payload())
    snapshot = await settle(search, job["id"])

    assert snapshot["results"][0] == {
        "prompt": "цветы",
        "region_id": FOUND_REGION,
        "region_name": "Москва и Московская область",
        "engine": "yandex",
        "status": "found",
        "position": 2,
        "url": "https://shop.example.ru/page",
        "error": None,
    }
    await search.close()


@pytest.mark.anyio
async def test_an_absent_site_is_not_a_failure():
    gateway = FakeGateway()
    search = service(gateway)

    job = await search.start(payload(regions=[ABSENT_REGION]))
    snapshot = await settle(search, job["id"])

    assert snapshot["results"][0]["status"] == "absent"
    assert snapshot["results"][0]["position"] is None
    assert snapshot["results"][0]["url"] is None
    assert snapshot["summary"] == {"successful": 1, "found": 0, "failed": 0}
    await search.close()


@pytest.mark.anyio
async def test_one_failure_does_not_erase_a_found_pair():
    gateway = FakeGateway()
    search = service(gateway)

    job = await search.start(payload(regions=[FOUND_REGION, ERROR_REGION]))
    snapshot = await settle(search, job["id"])

    assert [row["status"] for row in snapshot["results"]] == ["found", "error"]
    assert snapshot["summary"] == {"successful": 1, "found": 1, "failed": 1}
    assert snapshot["completed"] == 2
    assert snapshot["status"] == "done"
    await search.close()


@pytest.mark.anyio
async def test_an_unexpected_gateway_failure_is_reported_safely():
    class BrokenGateway(FakeGateway):
        async def submit(self, prompt: str, region: int) -> str:
            raise RuntimeError("secret-value leaked")

    search = service(BrokenGateway())

    job = await search.start(payload())
    snapshot = await settle(search, job["id"])

    assert snapshot["results"][0]["status"] == "error"
    assert "secret-value" not in json.dumps(snapshot, ensure_ascii=False)
    assert snapshot["summary"]["failed"] == 1
    await search.close()


@pytest.mark.anyio
async def test_twenty_questions_and_five_regions_submit_one_hundred_requests():
    gateway = FakeGateway()
    search = service(gateway)

    job = await search.start(
        payload(prompts_text="\n".join(f"вопрос {index}" for index in range(20)), regions=[1, 213, 2, 54, 65])
    )

    assert job["total"] == 100
    snapshot = await settle(search, job["id"])
    assert len(gateway.submitted) == 100
    assert snapshot["completed"] == 100
    await search.close()


@pytest.mark.anyio
async def test_a_snapshot_never_carries_operation_ids():
    gateway = FakeGateway()
    search = service(gateway)

    job = await search.start(payload())
    snapshot = await settle(search, job["id"])

    assert all("operation_id" not in row for row in snapshot["results"])
    assert "op-1" not in json.dumps(snapshot, ensure_ascii=False)
    await search.close()


@pytest.mark.anyio
async def test_an_unknown_or_expired_job_is_not_found():
    clock = FakeClock()
    search = service(FakeGateway(), clock=clock, job_ttl=86_400, finished_job_ttl=3_600)

    with pytest.raises(SearchJobNotFound):
        search.snapshot("no-such-job")

    job = await search.start(payload())
    await settle(search, job["id"])
    assert search.snapshot(job["id"])["completed"] == 1

    clock.advance(3_600)
    with pytest.raises(SearchJobNotFound):
        search.snapshot(job["id"])
    await search.close()


@pytest.mark.anyio
async def test_a_long_running_job_outlives_the_finished_job_ttl():
    clock = FakeClock()
    gateway = FakeGateway({FOUND_REGION: "never"})
    search = service(gateway, clock=clock, job_ttl=86_400, finished_job_ttl=3_600)

    job = await search.start(payload())
    for _ in range(5):
        await asyncio.sleep(0)
    clock.advance(3_600)

    snapshot = search.snapshot(job["id"])
    assert snapshot["completed"] == 0
    assert snapshot["results"][0]["status"] == "waiting"

    clock.advance(86_400)
    with pytest.raises(SearchJobNotFound):
        search.snapshot(job["id"])
    await search.close()


@pytest.mark.anyio
async def test_close_cancels_the_work_in_flight():
    gateway = FakeGateway({FOUND_REGION: "never"})
    search = service(gateway)

    job = await search.start(payload())
    for _ in range(5):
        await asyncio.sleep(0)
    polls_before_close = dict(gateway.polls)

    await search.close()
    for _ in range(5):
        await asyncio.sleep(0)

    assert gateway.polls == polls_before_close
    assert search.snapshot(job["id"])["results"][0]["status"] == "waiting"
    await search.close()


@pytest.mark.anyio
async def test_missing_credentials_reject_creation():
    search = service(None)

    with pytest.raises(ConfigurationError) as raised:
        await search.start(payload())

    assert str(raised.value) == "Не заданы ключ и каталог для поиска Яндекса"
    await search.close()


@pytest.mark.anyio
async def test_invalid_input_is_rejected_before_any_paid_request():
    gateway = FakeGateway()
    search = service(gateway)

    with pytest.raises(ValidationError):
        await search.start(payload(prompts_text="x" * 401))

    assert gateway.submitted == []
    await search.close()


@pytest.mark.anyio
async def test_rate_limiter_allows_at_most_ten_calls_per_rolling_second():
    clock = FakeClock()

    async def advance(seconds: float) -> None:
        clock.advance(seconds)
        await asyncio.sleep(0)

    limiter = AsyncRequestRateLimiter(10, clock=clock, sleep=advance)
    times = []
    for _ in range(21):
        await limiter.acquire()
        times.append(clock())

    assert times[:10] == [0] * 10
    assert times[10:20] == [1] * 10
    assert times[20] == 2


@pytest.mark.anyio
async def test_service_applies_separate_submit_and_result_quotas():
    clock = FakeClock()

    async def advance(seconds: float) -> None:
        clock.advance(seconds)
        await asyncio.sleep(0)

    class TimedGateway(FakeGateway):
        def __init__(self) -> None:
            super().__init__()
            self.submit_times: list[float] = []
            self.result_times: list[float] = []

        async def submit(self, prompt: str, region: int) -> str:
            self.submit_times.append(clock())
            return await super().submit(prompt, region)

        async def result(self, operation_id: str) -> tuple[SearchDocument, ...] | None:
            self.result_times.append(clock())
            return await super().result(operation_id)

    gateway = TimedGateway()
    search = service(
        gateway,
        max_requests_per_second=10,
        request_clock=clock,
        request_sleep=advance,
    )
    job = await search.start(payload(prompts_text="\n".join(f"вопрос {index}" for index in range(11))))
    await settle(search, job["id"])

    assert len(gateway.submit_times) == 11
    assert len(gateway.result_times) == 22
    for times in (gateway.submit_times, gateway.result_times):
        assert all(sum(start <= value < start + 1 for value in times) <= 10 for start in times)
    await search.close()


@pytest.mark.anyio
async def test_expired_jobs_are_cleaned_without_another_request():
    clock = FakeClock()
    search = service(FakeGateway(), clock=clock, finished_job_ttl=1, cleanup_interval=0.01)
    job = await search.start(payload())
    await settle(search, job["id"])

    clock.advance(1)
    for _ in range(20):
        if search.store.get(job["id"]) is None:
            break
        await asyncio.sleep(0.01)

    assert search.store.get(job["id"]) is None
    await search.close()


@pytest.mark.anyio
async def test_callbacks_keep_duplicate_prompt_ordinals_and_errors():
    search = service(FakeGateway(), max_concurrency=1)
    seen = []
    job = await search.start(
        payload(prompts_text="цветы\nцветы", regions=[FOUND_REGION, ERROR_REGION]),
        on_row=lambda index, row: seen.append((index, row.status)),
    )
    await settle(search, job["id"])
    assert seen == [(0, "found"), (1, "error"), (2, "found"), (3, "error")]
    await search.close()


@pytest.mark.anyio
async def test_storage_failure_cancels_queued_paid_submissions():
    gateway = FakeGateway(polls_before_answer=0)
    search = service(gateway, max_concurrency=1)
    failed = asyncio.Event()

    def on_row(_index, _row):
        failed.set()
        raise StorageError("disk failure")

    await search.start(
        payload(prompts_text="\n".join(f"вопрос {index}" for index in range(20)),
                regions=[1, 213, 2, 54, 65]),
        on_row=on_row,
    )
    await asyncio.wait_for(failed.wait(), 1)
    for _ in range(10):
        await asyncio.sleep(0)
    assert len(gateway.submitted) == 1
    await search.close()


@pytest.mark.anyio
async def test_expiry_notifies_for_unfinished_job():
    clock = FakeClock()
    search = service(FakeGateway({FOUND_REGION: "never"}), clock=clock, job_ttl=2)
    expired = []
    job = await search.start(payload(), on_expire=lambda: expired.append(job["id"]))
    for _ in range(5):
        await asyncio.sleep(0)
    clock.advance(2)
    with pytest.raises(SearchJobNotFound):
        search.snapshot(job["id"])
    assert expired == [job["id"]]
    await search.close()

@pytest.mark.anyio
async def test_disabled_engine_rejects_without_upstream_submission():
    gateway = FakeGateway(polls_before_answer=0)
    search = service(gateway)
    search.configure(gateway, False)

    with pytest.raises(ConfigurationError, match="выключен"):
        await search.start(payload())

    assert gateway.submitted == []
    await search.close()


@pytest.mark.anyio
async def test_reconfiguration_only_affects_jobs_started_after_it():
    original = FakeGateway(polls_before_answer=0)
    replacement = FakeGateway(polls_before_answer=0)
    search = service(original)
    first = await search.start(payload())
    search.configure(replacement, True)
    second = await search.start(payload(prompts_text="новый вопрос"))

    assert (await settle(search, first["id"]))["status"] == "done"
    assert (await settle(search, second["id"]))["status"] == "done"
    assert original.submitted == [("цветы", FOUND_REGION)]
    assert replacement.submitted == [("новый вопрос", FOUND_REGION)]
    await search.close()
