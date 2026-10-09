"""Coordinate a saved run across model checks and deferred Yandex search."""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import UTC, datetime
from threading import Event
from typing import Literal

from app.core.errors import AppError, StorageError, ValidationError
from app.db.runs import RunRepository
from app.domain.models import PromptResult
from app.domain.runs import RunInput, normalize_run_request
from app.service.checks import UNKNOWN_CONNECTION_MESSAGE, CheckService
from app.service.search import SearchRow, SearchService

LOGGER = logging.getLogger(__name__)
MODEL_FAILURE = "Не удалось завершить проверку моделей"
SEARCH_FAILURE = "Не удалось запустить поиск Яндекса"
STOPPED = "Сохранение результатов остановлено"


class RunService:
    def __init__(self, repository: RunRepository, checks: CheckService, search: SearchService) -> None:
        self.repository = repository
        self.checks = checks
        self.search = search
        self.tasks: dict[str, asyncio.Task] = {}
        self.search_jobs: dict[str, str] = {}
        self.failed_runs: set[str] = set()
        self.stopping = Event()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def start(self, payload: object) -> dict:
        if self.stopping.is_set():
            raise StorageError(STOPPED)
        self.loop = asyncio.get_running_loop()
        request = normalize_run_request(payload)
        known = {item.id: item.name for item in self.checks.connections.all()}
        if any(provider_id not in known for provider_id in request.provider_ids):
            raise ValidationError(UNKNOWN_CONNECTION_MESSAGE)
        names = {provider_id: known[provider_id] for provider_id in request.provider_ids}
        run_id = secrets.token_urlsafe(16)
        try:
            self.repository.create(run_id, request, names, datetime.now(UTC).isoformat())
        except StorageError:
            self._storage_failure(run_id)
            raise
        if request.provider_ids:
            task = asyncio.create_task(asyncio.to_thread(self._run_models, run_id, request))
            self.tasks[run_id] = task
            task.add_done_callback(lambda done, ident=run_id: self._task_done(ident, done))
        if request.regions:
            if self.stopping.is_set():
                raise StorageError(STOPPED)
            try:
                created = await self.search.start(
                    {"domain": request.domain, "prompts": list(request.prompts),
                     "regions": list(request.regions),
                     "region_targets": [
                         {"region": region, "engine": engine}
                         for region, engine in zip(request.regions, request.region_engines, strict=True)
                     ]},
                    on_row=lambda index, row: self._save_search(run_id, index, row),
                    on_expire=lambda: self.repository.interrupt_search(run_id),
                    should_stop=self.stopping.is_set,
                )
                self.search_jobs[run_id] = str(created["id"])
                if self.stopping.is_set():
                    self.search.abort(self.search_jobs[run_id])
                    raise StorageError(STOPPED)
            except StorageError:
                self._storage_failure(run_id)
                raise
            except AppError as exc:
                self._fail_branch(run_id, "search", str(exc))
            except Exception:  # noqa: BLE001 - safe branch failure after run creation
                self._fail_branch(run_id, "search", SEARCH_FAILURE)
        return {"id": run_id, "status": self.snapshot(run_id)["status"]}

    def _run_models(self, run_id: str, request: RunInput) -> None:
        def publish(provider_id: str, index: int, result: PromptResult) -> None:
            if self.stopping.is_set():
                raise StorageError(STOPPED)
            self.repository.save_model(run_id, provider_id, index, result)

        try:
            self.checks.run(
                {"brand": request.brand, "domain": request.domain,
                 "prompts": list(request.prompts), "provider_ids": list(request.provider_ids)},
                on_result=publish,
                should_stop=self.stopping.is_set,
            )
        except StorageError:
            self._storage_failure(run_id)
            raise
        except Exception:  # noqa: BLE001 - leave completed answers intact
            self._fail_branch(run_id, "model", MODEL_FAILURE)

    def _fail_branch(self, run_id: str, branch: Literal["model", "search"], message: str) -> None:
        try:
            self.repository.fail_pending_branch(run_id, branch, message)
        except StorageError:
            self._storage_failure(run_id)
            raise

    def _save_search(self, run_id: str, index: int, row: SearchRow) -> None:
        try:
            if self.stopping.is_set():
                raise StorageError(STOPPED)
            self.repository.save_search(run_id, index, row)
        except StorageError:
            self._storage_failure(run_id)
            raise

    def _storage_failure(self, run_id: str) -> None:
        self.failed_runs.update((*self.tasks.keys(), *self.search_jobs.keys(), run_id))
        self.stopping.set()
        if self.loop is not None and not self.loop.is_closed():
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
            if current_loop is self.loop:
                self._abort_search_jobs()
            else:
                self.loop.call_soon_threadsafe(self._abort_search_jobs)

    def _abort_search_jobs(self) -> None:
        for job_id in self.search_jobs.values():
            self.search.abort(job_id)

    def _task_done(self, run_id: str, task: asyncio.Task) -> None:
        self.tasks.pop(run_id, None)
        if not task.cancelled() and task.exception() is not None:
            LOGGER.error("Model work for run %s stopped: %s", run_id, type(task.exception()).__name__)

    def snapshot(self, run_id: str) -> dict:
        if run_id in self.failed_runs:
            raise StorageError(STOPPED)
        try:
            return self.repository.get(run_id)
        except StorageError:
            self._storage_failure(run_id)
            raise

    def list_page(self, cursor: str | None = None, limit: int = 20, project_id: str | None = None) -> dict:
        if self.stopping.is_set():
            raise StorageError(STOPPED)
        try:
            return self.repository.list_page(cursor, limit, project_id)
        except StorageError:
            self._storage_failure("history")
            raise

    def delete(self, run_id: str) -> None:
        try:
            self.repository.delete(run_id)
        except StorageError:
            self._storage_failure(run_id)
            raise

    async def close(self) -> None:
        self.stopping.set()
        pending = list(self.tasks.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self.tasks.clear()
