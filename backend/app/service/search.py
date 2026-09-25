"""Deferred Yandex search jobs owned by one local process, in memory only.

A run lives exactly as long as the page that started it: the service keeps the
ordered question-region rows, submits each pair, and polls its operation until it
finishes. One failed pair never erases another pair's result, and a failed pair is
never reported as an absent site.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.core.errors import ConfigurationError, ProviderError, SearchJobNotFound
from app.domain.search import (
    REGIONS,
    SearchDocument,
    SearchGateway,
    SearchInput,
    first_matching_result,
    normalize_search_request,
)

STATUS_SUBMITTING = "submitting"
STATUS_WAITING = "waiting"
STATUS_FOUND = "found"
STATUS_ABSENT = "absent"
STATUS_ERROR = "error"

TERMINAL_STATUSES = frozenset({STATUS_FOUND, STATUS_ABSENT, STATUS_ERROR})

JOB_STATUS_PENDING = "pending"
JOB_STATUS_DONE = "done"

JOB_TTL_SECONDS = 24 * 60 * 60
FINISHED_JOB_TTL_SECONDS = 60 * 60

DEFAULT_POLL_INTERVAL = 30.0
MAX_POLL_INTERVAL = 300.0
DEFAULT_MAX_CONCURRENCY = 5

MISSING_CREDENTIALS = "Не заданы ключ и каталог для поиска Яндекса"
JOB_NOT_FOUND = "Задача поиска не найдена"
UNEXPECTED_FAILURE = "Не удалось получить выдачу Яндекса"

REGION_NAMES = dict(REGIONS)


@dataclass
class SearchRow:
    """One question-region pair and everything the page shows about it."""

    prompt: str
    region: int
    region_name: str
    status: str = STATUS_SUBMITTING
    position: int | None = None
    url: str | None = None
    error: str | None = None
    finished_at: float | None = None

    @property
    def finished(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def finish(self, match: tuple[int, str] | None, at: float) -> None:
        """Record a finished search: a rank and link, or an absent site."""
        self.finished_at = at
        if match is None:
            self.status = STATUS_ABSENT
            return
        self.status = STATUS_FOUND
        self.position, self.url = match

    def fail(self, message: str, at: float) -> None:
        """A failed pair is an error, never an absent site."""
        self.status = STATUS_ERROR
        self.position = None
        self.url = None
        self.error = message
        self.finished_at = at

    def as_dict(self) -> dict[str, object]:
        return {
            "prompt": self.prompt,
            "region_id": self.region,
            "region_name": self.region_name,
            "status": self.status,
            "position": self.position,
            "url": self.url,
            "error": self.error,
        }


@dataclass
class SearchJob:
    """A batch of pairs for one site. Its snapshot is the only thing ever published."""

    id: str
    domain: str
    host: str
    regions: tuple[int, ...]
    rows: list[SearchRow]
    created_at: float

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def completed(self) -> int:
        return sum(1 for row in self.rows if row.finished)

    @property
    def found(self) -> int:
        return sum(1 for row in self.rows if row.status == STATUS_FOUND)

    @property
    def failed(self) -> int:
        return sum(1 for row in self.rows if row.status == STATUS_ERROR)

    @property
    def successful(self) -> int:
        """Pairs that produced a verdict; failures are counted separately."""
        return self.completed - self.failed

    @property
    def status(self) -> str:
        return JOB_STATUS_DONE if self.completed == self.total else JOB_STATUS_PENDING

    @property
    def completed_at(self) -> float | None:
        """When the last pair reached a terminal state, or None while work is left."""
        if self.completed != self.total:
            return None
        stamps = [row.finished_at for row in self.rows if row.finished_at is not None]
        return max(stamps) if stamps else None

    def deadline(self, job_ttl: float, finished_job_ttl: float) -> float:
        """Creation plus its TTL, or completion plus the shorter one, whichever is first."""
        deadline = self.created_at + job_ttl
        completed_at = self.completed_at
        if completed_at is not None:
            deadline = min(deadline, completed_at + finished_job_ttl)
        return deadline

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "domain": self.domain,
            "regions": list(self.regions),
            "total": self.total,
            "completed": self.completed,
            "status": self.status,
            "summary": {"successful": self.successful, "found": self.found, "failed": self.failed},
            "results": [row.as_dict() for row in self.rows],
        }


class InMemorySearchJobStore:
    """The live job table of this process. Nothing here survives a restart."""

    def __init__(self) -> None:
        self._jobs: dict[str, SearchJob] = {}

    def add(self, job: SearchJob) -> None:
        self._jobs[job.id] = job

    def get(self, job_id: str) -> SearchJob | None:
        return self._jobs.get(job_id)

    def remove(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)

    def expired(self, now: float, job_ttl: float, finished_job_ttl: float) -> list[SearchJob]:
        return [job for job in self._jobs.values() if job.deadline(job_ttl, finished_job_ttl) <= now]


class SearchService:
    """Owns search jobs, their background work, and their retained snapshots.

    A `None` gateway means the Yandex credentials are missing: creating a run is
    refused before anything is sent. Every pair is submitted and polled under one
    concurrency limit; `snapshot` never exposes mutable state.
    """

    def __init__(
        self,
        gateway: SearchGateway | None,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        max_poll_interval: float = MAX_POLL_INTERVAL,
        job_ttl: float = JOB_TTL_SECONDS,
        finished_job_ttl: float = FINISHED_JOB_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.gateway = gateway
        self.poll_interval = poll_interval
        self.max_poll_interval = max_poll_interval
        self.job_ttl = job_ttl
        self.finished_job_ttl = finished_job_ttl
        self.clock = clock
        self.store = InMemorySearchJobStore()
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.tasks: dict[str, asyncio.Task] = {}

    async def start(self, payload: object) -> dict[str, object]:
        """Validate a run, create its pairs, and return before any pair finishes."""
        if self.gateway is None:
            raise ConfigurationError(MISSING_CREDENTIALS)
        request = normalize_search_request(payload)
        self._drop_expired()

        job = self._create_job(request)
        self.store.add(job)
        task = asyncio.create_task(self._run(job))
        self.tasks[job.id] = task
        task.add_done_callback(lambda _task, job_id=job.id: self.tasks.pop(job_id, None))
        return {"id": job.id, "total": job.total, "status": job.status}

    def snapshot(self, job_id: str) -> dict[str, object]:
        """Return a copy of one job's public state, or refuse an unknown ID."""
        self._drop_expired()
        job = self.store.get(job_id)
        if job is None:
            raise SearchJobNotFound(JOB_NOT_FOUND)
        return job.as_dict()

    async def close(self) -> None:
        """Cancel the work still in flight; safe to call more than once."""
        pending = list(self.tasks.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self.tasks.clear()

    def _create_job(self, request: SearchInput) -> SearchJob:
        rows = [
            SearchRow(prompt=prompt, region=region, region_name=REGION_NAMES[region])
            for prompt in request.prompts
            for region in request.regions
        ]
        return SearchJob(
            id=secrets.token_urlsafe(16),
            domain=request.domain,
            host=request.host,
            regions=request.regions,
            rows=rows,
            created_at=self.clock(),
        )

    def _drop_expired(self) -> None:
        for job in self.store.expired(self.clock(), self.job_ttl, self.finished_job_ttl):
            self.store.remove(job.id)
            task = self.tasks.pop(job.id, None)
            if task is not None:
                task.cancel()

    async def _run(self, job: SearchJob) -> None:
        await asyncio.gather(*(self._run_pair(job, row) for row in job.rows))

    async def _run_pair(self, job: SearchJob, row: SearchRow) -> None:
        gateway = self.gateway
        assert gateway is not None  # `start` refuses a run without credentials
        try:
            async with self.semaphore:
                operation_id = await gateway.submit(row.prompt, row.region)
            row.status = STATUS_WAITING
            delay = self.poll_interval
            while True:
                async with self.semaphore:
                    documents: tuple[SearchDocument, ...] | None = await gateway.result(operation_id)
                if documents is not None:
                    row.finish(first_matching_result(job.host, documents), self.clock())
                    return
                await asyncio.sleep(delay)
                delay = min(max(delay * 1.5, self.poll_interval), self.max_poll_interval)
        except asyncio.CancelledError:
            raise
        except ProviderError as exc:
            # Adapter messages are fixed and safe by contract.
            row.fail(str(exc), self.clock())
        except Exception:  # noqa: BLE001 - one broken pair must not stop the others
            row.fail(UNEXPECTED_FAILURE, self.clock())


__all__ = [
    "InMemorySearchJobStore",
    "SearchDocument",
    "SearchJob",
    "SearchJobNotFound",
    "SearchRow",
    "SearchService",
]
