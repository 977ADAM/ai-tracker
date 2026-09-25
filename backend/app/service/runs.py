"""Coordinate a saved run across model checks and deferred Yandex search."""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import UTC, datetime
from threading import Event

from app.core.errors import AppError, StorageError, ValidationError
from app.db.runs import RunRepository
from app.domain.models import PromptResult
from app.domain.runs import RunInput, normalize_run_request
from app.service.checks import UNKNOWN_CONNECTION_MESSAGE, CheckService
from app.service.search import MISSING_CREDENTIALS, SearchRow, SearchService

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
        self.stopping = Event()

    async def start(self, payload: object) -> dict:
        request = normalize_run_request(payload)
        known = {item.id: item.name for item in self.checks.connections.all()}
        if any(provider_id not in known for provider_id in request.provider_ids):
            raise ValidationError(UNKNOWN_CONNECTION_MESSAGE)
        names = {provider_id: known[provider_id] for provider_id in request.provider_ids}
        run_id = secrets.token_urlsafe(16)
        self.repository.create(run_id, request, names, datetime.now(UTC).isoformat())
        if request.provider_ids:
            task = asyncio.create_task(asyncio.to_thread(self._run_models, run_id, request))
            self.tasks[run_id] = task
            task.add_done_callback(lambda done, ident=run_id: self._task_done(ident, done))
        if request.regions:
            if self.search.gateway is None:
                self.repository.fail_pending_branch(run_id, "search", MISSING_CREDENTIALS)
            else:
                try:
                    await self.search.start(
                        {"domain": request.domain, "prompts": list(request.prompts),
                         "regions": list(request.regions)},
                        on_row=lambda index, row: self._save_search(run_id, index, row),
                        on_expire=lambda: self.repository.interrupt_search(run_id),
                    )
                except StorageError:
                    self.stopping.set()
                    raise
                except AppError as exc:
                    self.repository.fail_pending_branch(run_id, "search", str(exc))
                except Exception:  # noqa: BLE001 - safe branch failure after run creation
                    self.repository.fail_pending_branch(run_id, "search", SEARCH_FAILURE)
        return {"id": run_id, "status": self.repository.get(run_id)["status"]}

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
            )
        except StorageError:
            self.stopping.set()
            raise
        except Exception:  # noqa: BLE001 - leave completed answers intact
            self.repository.fail_pending_branch(run_id, "model", MODEL_FAILURE)

    def _save_search(self, run_id: str, index: int, row: SearchRow) -> None:
        try:
            self.repository.save_search(run_id, index, row)
        except StorageError:
            self.stopping.set()
            raise

    def _task_done(self, run_id: str, task: asyncio.Task) -> None:
        self.tasks.pop(run_id, None)
        if not task.cancelled() and task.exception() is not None:
            LOGGER.error("Model work for run %s stopped: %s", run_id, type(task.exception()).__name__)

    def snapshot(self, run_id: str) -> dict:
        return self.repository.get(run_id)

    def list_page(self, cursor: str | None = None, limit: int = 20) -> dict:
        return self.repository.list_page(cursor, limit)

    def delete(self, run_id: str) -> None:
        self.repository.delete(run_id)

    async def close(self) -> None:
        self.stopping.set()
        pending = list(self.tasks.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self.tasks.clear()
