"""SEO orchestrator: six fixed stages over durable rows and two independent branches.

The service owns one background task per analysis and never runs a heavy stage
inside an HTTP request. Stage order is fixed: site facts (1), key-query
competitors (2), query generation (3), Yandex and model checks (4), summary (5),
and the report (6). A fatal stage 1 or stage 3 error stops the run before any
paid generated-query or model call; stage 2 degrades to "no competitors" and
stage 4 failures are per row.

Every stage writes its own status and counters through the repository, and every
finished row is saved as it arrives. Yandex and model branches are independent:
`asyncio.gather` waits for both, a row error stays on its row, and a model
provider failure never erases a Yandex result. Cancellation is per analysis
through a private `asyncio.Event`, so a storage failure or a cancel touches only
this run and never the global `RunService` stop flag.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from typing import Any

from app.core.errors import (
    AppError,
    ConfigurationError,
    ProviderError,
    StorageError,
    ValidationError,
)
from app.db.seo import TERMINAL_ANALYSIS_STATUSES, ResumePlan, SeoRepository
from app.db.seo_settings import SeoSettingsRepository
from app.domain.matching import mentions_phrase
from app.domain.providers import AnswerProvider, ProviderFactory
from app.domain.search import (
    TOP_RESULTS,
    SearchDocument,
    SearchGateway,
    first_matching_result,
)
from app.domain.seo import (
    GENERATED_QUERY_LIMIT,
    Candidate,
    CandidateHit,
    GeneratedQuery,
    QueryFlags,
    SeedResult,
    SeoInput,
    flag_queries,
    mentions_host,
    merge_services,
    normalize_seo_request,
    rank_candidates,
)
from app.domain.seo_prompts import (
    SiteFacts,
    queries_from_payload,
    queries_prompt,
    site_facts_from_payload,
    site_facts_prompt,
    summary_prompt,
)
from app.domain.site_fetch import FetchedPage, SiteFetcher
from app.integrations.seo_llm import SeoLlmClient
from app.service.checks import (
    CALL_FAILURE_MESSAGE,
    MISSING_KEY_MESSAGE,
    SETUP_FAILURE_MESSAGE,
)
from app.service.connections import ConnectionService
from app.service.search import (
    DEFAULT_POLL_INTERVAL,
    DISABLED_ENGINE,
    MAX_POLL_INTERVAL,
    MAX_REQUESTS_PER_SECOND,
    MISSING_CREDENTIALS,
    UNEXPECTED_FAILURE,
    AsyncRequestRateLimiter,
)
from app.service.search_settings import SearchSettingsService

LOGGER = logging.getLogger(__name__)

# Yandex region 225 is the whole of Russia, the only region of the first version.
SEARCH_REGION = 225
DEFAULT_MAX_MODEL_CONCURRENCY = 5
MAX_SEARCH_CONCURRENCY = 5

STAGE_FETCH = 1
STAGE_CANDIDATES = 2
STAGE_QUERIES = 3
STAGE_CHECKS = 4
STAGE_SUMMARY = 5
STAGE_REPORT = 6

STATUS_SUBMITTING = "submitting"
STATUS_WAITING = "waiting"
STATUS_FOUND = "found"
STATUS_ABSENT = "absent"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"

FETCH_FAILED = "Не удалось обойти сайт"
SITE_FACTS_FAILED = "Не удалось извлечь сведения о сайте"
SEEDS_FAILED = "Не удалось получить ключевые выдачи Яндекса"
QUERIES_FAILED = "Не удалось сгенерировать запросы"
CHECKS_FAILED = "Не удалось выполнить проверки"
SUMMARY_FAILED = "Не удалось подготовить резюме"
SEARCH_ROW_FAILED = UNEXPECTED_FAILURE
LLM_NOT_CONFIGURED = "Не настроена служебная LLM для SEO-анализа"


class SeoService:
    """Run one durable SEO analysis per background task and expose its saved rows."""

    def __init__(
        self,
        repository: SeoRepository,
        llm_settings: SeoSettingsRepository,
        llm_factory: Callable[[], SeoLlmClient | None],
        fetcher: SiteFetcher,
        yandex_settings: SearchSettingsService,
        connections: ConnectionService,
        provider_factory: ProviderFactory,
        *,
        max_model_concurrency: int = DEFAULT_MAX_MODEL_CONCURRENCY,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        max_poll_interval: float = MAX_POLL_INTERVAL,
        max_requests_per_second: int = MAX_REQUESTS_PER_SECOND,
    ) -> None:
        self.repository = repository
        # Kept for callers that already hold the resolved settings repository;
        # availability itself is decided by `llm_factory`, which builds its
        # client from the same resolved settings and returns None when the three
        # values are not all present.
        self.llm_settings = llm_settings
        self.llm_factory = llm_factory
        self.fetcher = fetcher
        self.yandex_settings = yandex_settings
        self.connections = connections
        self.provider_factory = provider_factory
        self.poll_interval = poll_interval
        self.max_poll_interval = max_poll_interval
        self.model_semaphore = asyncio.Semaphore(max_model_concurrency)
        self.search_semaphore = asyncio.Semaphore(MAX_SEARCH_CONCURRENCY)
        self.submit_limiter = AsyncRequestRateLimiter(max_requests_per_second)
        self.result_limiter = AsyncRequestRateLimiter(max_requests_per_second)
        self.tasks: dict[str, asyncio.Task] = {}
        self.stop_events: dict[str, asyncio.Event] = {}
        self.cancelled: set[str] = set()
        self._deferred_resume: list[str] = []

    # -- public API ------------------------------------------------------

    async def start(self, payload: object) -> dict[str, object]:
        """Validate the request and return before any crawl, search, or model call."""
        request = normalize_seo_request(payload)
        if not self.yandex_settings.enabled():
            raise ConfigurationError(DISABLED_ENGINE)
        gateway = self.yandex_settings.gateway_snapshot()
        if gateway is None:
            raise ConfigurationError(MISSING_CREDENTIALS)
        selected = self._selected_connections(request.connection_ids)
        client = self.llm_factory()
        if client is None:
            raise ConfigurationError(LLM_NOT_CONFIGURED)

        estimate = {
            "search_upper": 3 + GENERATED_QUERY_LIMIT,
            "model_upper": GENERATED_QUERY_LIMIT * len(request.connection_ids),
            "generated_limit": GENERATED_QUERY_LIMIT,
            "connections": len(request.connection_ids),
        }
        analysis_id = self.repository.create_analysis(request, estimate)
        self._stop_event(analysis_id)
        self._spawn(analysis_id, self._run(analysis_id, request, selected, gateway, client))
        self._flush_deferred()
        return {"id": analysis_id, "status": "running", "estimate": estimate}

    def snapshot(self, analysis_id: str) -> dict:
        """Return one saved analysis; the report is always built from stored rows."""
        return self.repository.snapshot(analysis_id)

    def list_page(self, cursor: str | None = None) -> dict:
        """Return one light history page, newest first."""
        return self.repository.list_page(cursor)

    def rows_page(self, analysis_id: str, kind: str, cursor: str | None = None) -> dict:
        """Return one page of saved model answers or Yandex rows."""
        return self.repository.rows_page(analysis_id, kind, cursor)

    def cancel(self, analysis_id: str) -> dict:
        """Stop new external calls of one analysis and end it as cancelled."""
        event = self.stop_events.get(analysis_id)
        if event is not None:
            event.set()
        self.cancelled.add(analysis_id)
        self.repository.cancel(analysis_id)
        return self.repository.snapshot(analysis_id)

    def delete(self, analysis_id: str) -> None:
        """Delete a terminal analysis and drop its in-memory run state."""
        self.repository.delete(analysis_id)
        self.stop_events.pop(analysis_id, None)
        self.cancelled.discard(analysis_id)
        self.tasks.pop(analysis_id, None)

    def recover(self) -> None:
        """Decide the fate of every analysis a restart left behind.

        A ready report is completed; an analysis with already-submitted Yandex
        operations keeps them and resumes polling them without paying again,
        while every unsubmitted row and every queued model call becomes
        interrupted; an analysis with nothing left to resume is interrupted.

        Polling is asynchronous, so the resume task is created when a loop is
        already running. A container built at import time (no loop yet) keeps the
        resumable IDs and starts them on the first `start()`; `resume_pending()`
        lets a startup hook start them right away.
        """
        for analysis_id in self.repository.running_analysis_ids():
            plan = self.repository.resume_plan(analysis_id)
            if plan.report_ready:
                self.repository.finish_analysis(analysis_id)
                continue
            if plan.submitted or plan.submitted_seeds:
                self.repository.interrupt_unsubmitted_rows(analysis_id)
                self._schedule_resume(analysis_id)
                continue
            self.repository.mark_interrupted(analysis_id)

    def resume_pending(self) -> None:
        """Start every analysis whose resume was deferred until a loop existed."""
        self._flush_deferred()

    async def close(self) -> None:
        """Stop every live analysis; safe to call more than once."""
        pending = list(self.tasks.values())
        for event in self.stop_events.values():
            event.set()
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self.tasks.clear()
        self.stop_events.clear()
        self.cancelled.clear()
        self._deferred_resume.clear()

    # -- run state -------------------------------------------------------

    def _stop_event(self, analysis_id: str) -> asyncio.Event:
        event = self.stop_events.get(analysis_id)
        if event is None:
            event = self.stop_events[analysis_id] = asyncio.Event()
        return event

    def _stop(self, analysis_id: str) -> None:
        self._stop_event(analysis_id).set()

    def _stopped(self, analysis_id: str) -> bool:
        event = self.stop_events.get(analysis_id)
        return event is not None and event.is_set()

    def _spawn(self, analysis_id: str, coroutine: Any) -> None:
        """Run one coroutine as a task whose exception never escapes the callback."""
        self._stop_event(analysis_id)
        task = asyncio.create_task(coroutine)
        self.tasks[analysis_id] = task
        task.add_done_callback(lambda done, ident=analysis_id: self._task_done(ident, done))

    def _task_done(self, analysis_id: str, task: asyncio.Task) -> None:
        self.tasks.pop(analysis_id, None)
        self.stop_events.pop(analysis_id, None)
        self.cancelled.discard(analysis_id)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            LOGGER.error("SEO analysis %s stopped: %s", analysis_id, type(error).__name__)

    def _schedule_resume(self, analysis_id: str) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            if analysis_id not in self._deferred_resume:
                self._deferred_resume.append(analysis_id)
            return
        self._spawn(analysis_id, self._resume(analysis_id))

    def _flush_deferred(self) -> None:
        if not self._deferred_resume:
            return
        deferred, self._deferred_resume = self._deferred_resume, []
        for analysis_id in deferred:
            self._spawn(analysis_id, self._resume(analysis_id))

    # -- the six stages --------------------------------------------------

    async def _run(
        self,
        analysis_id: str,
        request: SeoInput,
        selected: tuple[tuple[str, str], ...],
        gateway: SearchGateway,
        client: SeoLlmClient,
    ) -> None:
        try:
            facts = await self._stage_fetch(analysis_id, request, client)
            if facts is None:
                return
            company_name, services = facts
            candidates = await self._stage_candidates(analysis_id, request, gateway)
            if candidates is None:
                return
            queries = await self._stage_queries(analysis_id, request, company_name, services, candidates, client)
            if queries is None:
                return
            await self._stage_checks(analysis_id, request, company_name, selected, candidates, queries, gateway)
            if self._stopped(analysis_id):
                return
            await self._stage_summary(analysis_id, client)
            if self._stopped(analysis_id):
                return
            await self._stage_report(analysis_id)
        except asyncio.CancelledError:
            raise
        except StorageError:
            self._stop(analysis_id)
            self._fail(analysis_id)
        except Exception as exc:  # noqa: BLE001 - a task must never surface an exception
            LOGGER.error("SEO analysis %s failed: %s", analysis_id, type(exc).__name__)
            self._fail(analysis_id)

    async def _stage_fetch(
        self, analysis_id: str, request: SeoInput, client: SeoLlmClient,
    ) -> tuple[str, tuple[str, ...]] | None:
        """Crawl the site, ask the service LLM once, and merge the services.

        A crawl error or an LLM error after one repeat is fatal and happens
        before any paid search or model call.
        """
        self.repository.update_stage(analysis_id, STAGE_FETCH, "running")
        if self._stopped(analysis_id):
            return None
        try:
            pages = tuple(await self.fetcher.fetch(request.host))
        except AppError:
            return self._fatal_stage(analysis_id, STAGE_FETCH, FETCH_FAILED)
        except Exception:  # noqa: BLE001 - any crawl failure is a safe stage error
            return self._fatal_stage(analysis_id, STAGE_FETCH, FETCH_FAILED)
        if self._stopped(analysis_id):
            return None

        facts = await self._ask_site_facts(analysis_id, request, pages, client)
        if facts is None:
            return None
        services = merge_services(request.services, facts.services)
        self.repository.save_site_facts(
            analysis_id,
            facts.company_name,
            services,
            tuple((page.url, page.title) for page in pages),
        )
        self.repository.update_stage(
            analysis_id, STAGE_FETCH, "done",
            counters={"pages": len(pages), "services": len(services)},
        )
        return facts.company_name, services

    async def _ask_site_facts(
        self, analysis_id: str, request: SeoInput, pages: Sequence[FetchedPage], client: SeoLlmClient,
    ) -> SiteFacts | None:
        """One facts call plus one repeat when the answer is not the expected JSON."""
        system, user = site_facts_prompt(request.host, pages)
        for attempt in range(2):
            try:
                text = await client.complete(system, user)
            except ValidationError:
                text = None
            except Exception:  # noqa: BLE001 - fixed adapter messages are safe
                return self._fatal_stage(analysis_id, STAGE_FETCH, SITE_FACTS_FAILED)
            if text is not None:
                try:
                    return site_facts_from_payload(text)
                except ValidationError:
                    pass
            if attempt == 1:
                return self._fatal_stage(analysis_id, STAGE_FETCH, SITE_FACTS_FAILED)
        return None

    async def _stage_candidates(
        self, analysis_id: str, request: SeoInput, gateway: SearchGateway,
    ) -> tuple[Candidate, ...] | None:
        """Run the three key searches and rank the domains they returned.

        One failed key search is only its own row; three failures mark the stage
        as an error and the run continues without candidates.
        """
        self.repository.update_stage(analysis_id, STAGE_CANDIDATES, "running")
        if self._stopped(analysis_id):
            return None
        results = await asyncio.gather(*(
            self._run_seed(analysis_id, gateway, index, seed)
            for index, seed in enumerate(request.seeds)
        ))
        if self._stopped(analysis_id):
            return None
        successful = tuple(result for result in results if result is not None)
        candidates = rank_candidates(successful, request.host)
        self.repository.replace_candidates(analysis_id, candidates)
        counters = {
            "seeds": len(request.seeds),
            "successful": len(successful),
            "candidates": len(candidates),
        }
        if successful:
            self.repository.update_stage(analysis_id, STAGE_CANDIDATES, "done", counters=counters)
        else:
            self.repository.update_stage(
                analysis_id, STAGE_CANDIDATES, "error", error=SEEDS_FAILED, counters=counters,
            )
        return candidates

    async def _run_seed(
        self, analysis_id: str, gateway: SearchGateway, seed_index: int, seed: str,
    ) -> SeedResult | None:
        """Submit and poll one key query; a failure stays on its own row."""
        operation_id: str | None = None
        try:
            async with self.search_semaphore:
                if self._stopped(analysis_id):
                    return None
                await self.submit_limiter.acquire()
                if self._stopped(analysis_id):
                    return None
                operation_id = await gateway.submit(seed, SEARCH_REGION)
            self.repository.save_seed_row(
                analysis_id, seed_index, status=STATUS_SUBMITTING, operation_id=operation_id,
            )
            documents = await self._poll_operation(analysis_id, gateway, operation_id)
            if documents is None:
                return None
            self.repository.save_seed_row(
                analysis_id, seed_index,
                status=STATUS_FOUND if documents else STATUS_ABSENT,
                operation_id=operation_id,
            )
            return SeedResult(query_index=seed_index, documents=self._document_values(documents))
        except StorageError:
            self._stop(analysis_id)
            raise
        except ProviderError as exc:
            self._save_seed_error(analysis_id, seed_index, str(exc), operation_id)
            return None
        except Exception:  # noqa: BLE001 - one broken key search must not stop the others
            self._save_seed_error(analysis_id, seed_index, UNEXPECTED_FAILURE, operation_id)
            return None

    async def _stage_queries(
        self,
        analysis_id: str,
        request: SeoInput,
        company_name: str,
        services: tuple[str, ...],
        candidates: tuple[Candidate, ...],
        client: SeoLlmClient,
    ) -> tuple[GeneratedQuery, ...] | None:
        """Generate the query set, repeat once on a domain error, then flag it.

        A second failure is fatal and still happens before any paid
        generated-query or model call.
        """
        self.repository.update_stage(analysis_id, STAGE_QUERIES, "running")
        if self._stopped(analysis_id):
            return None
        system, user = queries_prompt(request, company_name, services, candidates)
        queries = await self._ask_queries(analysis_id, system, user, services, client)
        if queries is None:
            return None
        flagged = flag_queries(
            queries, company_name, request.host, tuple(candidate.host for candidate in candidates),
        )
        self.repository.replace_queries(analysis_id, flagged)
        if self._stopped(analysis_id):
            return None
        self.repository.update_stage(
            analysis_id, STAGE_QUERIES, "done", counters={"queries": len(flagged)},
        )
        return flagged

    async def _ask_queries(
        self, analysis_id: str, system: str, user: str, services: tuple[str, ...], client: SeoLlmClient,
    ) -> tuple[GeneratedQuery, ...] | None:
        for attempt in range(2):
            try:
                text = await client.complete(system, user)
            except ValidationError:
                text = None
            except Exception:  # noqa: BLE001 - fixed adapter messages are safe
                return self._fatal_stage(analysis_id, STAGE_QUERIES, QUERIES_FAILED)
            if text is not None:
                try:
                    return queries_from_payload(text, services)
                except ValidationError:
                    pass
            if attempt == 1:
                return self._fatal_stage(analysis_id, STAGE_QUERIES, QUERIES_FAILED)
        return None

    async def _stage_checks(
        self,
        analysis_id: str,
        request: SeoInput,
        company_name: str,
        selected: tuple[tuple[str, str], ...],
        candidates: tuple[Candidate, ...],
        queries: tuple[GeneratedQuery, ...],
        gateway: SearchGateway,
    ) -> None:
        """Run both paid branches independently and keep every row they saved."""
        self.repository.update_stage(analysis_id, STAGE_CHECKS, "running")
        if self._stopped(analysis_id):
            return
        results = await asyncio.gather(
            self._search_branch(analysis_id, request, candidates, queries, gateway),
            self._model_branch(analysis_id, request, company_name, selected, queries),
            return_exceptions=True,
        )
        problem = next((item for item in results if isinstance(item, BaseException)), None)
        if isinstance(problem, (StorageError, asyncio.CancelledError)):
            raise problem
        if self._stopped(analysis_id):
            return
        if problem is not None:
            LOGGER.error("SEO analysis %s checks stopped: %s", analysis_id, type(problem).__name__)
            self.repository.update_stage(analysis_id, STAGE_CHECKS, "error", error=CHECKS_FAILED)
            return
        self.repository.update_stage(
            analysis_id, STAGE_CHECKS, "done",
            counters={"search_rows": len(queries), "model_rows": len(queries) * len(selected)},
        )

    async def _search_branch(
        self,
        analysis_id: str,
        request: SeoInput,
        candidates: tuple[Candidate, ...],
        queries: tuple[GeneratedQuery, ...],
        gateway: SearchGateway,
    ) -> None:
        await asyncio.gather(*(
            self._run_search_row(analysis_id, request, candidates, index, query, gateway)
            for index, query in enumerate(queries)
        ))

    async def _run_search_row(
        self,
        analysis_id: str,
        request: SeoInput,
        candidates: tuple[Candidate, ...],
        query_index: int,
        query: GeneratedQuery,
        gateway: SearchGateway,
    ) -> None:
        """Submit one generated query, poll it, and save its site position and hits."""
        operation_id: str | None = None
        try:
            async with self.search_semaphore:
                if self._stopped(analysis_id):
                    self._save_cancelled_search_row(analysis_id, query_index)
                    return
                await self.submit_limiter.acquire()
                if self._stopped(analysis_id):
                    self._save_cancelled_search_row(analysis_id, query_index)
                    return
                operation_id = await gateway.submit(query.text, SEARCH_REGION)
            if self._stopped(analysis_id):
                self._save_cancelled_search_row(analysis_id, query_index, operation_id)
                return
            self.repository.save_search_row(
                analysis_id, query_index, status=STATUS_WAITING, operation_id=operation_id,
            )
            documents = await self._poll_operation(analysis_id, gateway, operation_id)
            if documents is None:
                self._save_cancelled_search_row(analysis_id, query_index, operation_id)
                return
            self._save_search_outcome(
                analysis_id, request, candidates, query_index, documents, operation_id,
            )
        except StorageError:
            self._stop(analysis_id)
            raise
        except ProviderError as exc:
            self._save_search_error(analysis_id, query_index, str(exc), operation_id)
        except Exception:  # noqa: BLE001 - one broken row must not stop the others
            self._save_search_error(analysis_id, query_index, SEARCH_ROW_FAILED, operation_id)

    async def _model_branch(
        self,
        analysis_id: str,
        request: SeoInput,
        company_name: str,
        selected: tuple[tuple[str, str], ...],
        queries: tuple[GeneratedQuery, ...],
    ) -> None:
        await asyncio.gather(*(
            self._run_connection(analysis_id, request, company_name, connection_id, provider_name, queries)
            for connection_id, provider_name in selected
        ))

    async def _run_connection(
        self,
        analysis_id: str,
        request: SeoInput,
        company_name: str,
        connection_id: str,
        provider_name: str,
        queries: tuple[GeneratedQuery, ...],
    ) -> None:
        """Answer every generated query for one connection and save each row."""
        provider, setup_error = self._prepare_provider(connection_id)
        try:
            for query_index, query in enumerate(queries):
                if self._stopped(analysis_id):
                    return
                async with self.model_semaphore:
                    if self._stopped(analysis_id):
                        return
                    answer, error = await self._ask(provider, setup_error, query.text)
                if error is not None:
                    self.repository.save_model_row(
                        analysis_id, connection_id, provider_name, query_index,
                        status=STATUS_ERROR, error=error,
                    )
                    continue
                name_mentioned = mentions_phrase(answer, company_name)
                host_mentioned = mentions_host(answer, request.host)
                self.repository.save_model_row(
                    analysis_id, connection_id, provider_name, query_index,
                    status=STATUS_FOUND if name_mentioned or host_mentioned else STATUS_ABSENT,
                    answer=answer,
                    name_mentioned=name_mentioned,
                    host_mentioned=host_mentioned,
                )
        except StorageError:
            self._stop(analysis_id)
            raise
        finally:
            self._close(provider)

    async def _stage_summary(self, analysis_id: str, client: SeoLlmClient) -> None:
        """Summarize aggregate metrics only; a summary failure never blocks the report."""
        self.repository.update_stage(analysis_id, STAGE_SUMMARY, "running")
        if self._stopped(analysis_id):
            return
        metrics = self.repository.snapshot(analysis_id)["aggregates"]
        system, user = summary_prompt(metrics)
        try:
            text = await client.complete(system, user)
        except Exception:  # noqa: BLE001 - the report stays valid without a summary
            text = None
        if not isinstance(text, str) or not text.strip():
            self.repository.save_summary(analysis_id, None)
            self.repository.update_stage(analysis_id, STAGE_SUMMARY, "error", error=SUMMARY_FAILED)
            return
        self.repository.save_summary(analysis_id, text.strip())
        self.repository.update_stage(
            analysis_id, STAGE_SUMMARY, "done", counters={"summary": 1},
        )

    async def _stage_report(self, analysis_id: str) -> None:
        """The report is already built from stored rows; this closes the analysis."""
        self.repository.update_stage(analysis_id, STAGE_REPORT, "running")
        if self._stopped(analysis_id):
            return
        self.repository.update_stage(analysis_id, STAGE_REPORT, "done", counters={"report": 1})
        self.repository.finish_analysis(analysis_id)

    # -- resume ----------------------------------------------------------

    async def _resume(self, analysis_id: str) -> None:
        """Continue an interrupted analysis from its first unfinished stage.

        Only already-submitted Yandex operations are polled again. Unsubmitted
        rows and queued model calls were marked interrupted by `recover` and are
        never replayed, so a restart never pays for the same work twice.
        """
        try:
            if self._stopped(analysis_id):
                return
            snapshot = self.repository.snapshot(analysis_id)
            if snapshot["status"] in TERMINAL_ANALYSIS_STATUSES:
                return
            plan = self.repository.resume_plan(analysis_id)
            client = self.llm_factory()
            gateway = self.yandex_settings.gateway_snapshot()
            if client is None or gateway is None:
                self.repository.mark_interrupted(analysis_id)
                return

            request = _request_from_snapshot(snapshot)
            stages = {stage["stage"]: stage["status"] for stage in snapshot["stages"]}
            services = tuple(snapshot["services"])
            company_name = snapshot["company_name"]
            candidates = _candidates_from_snapshot(snapshot)
            queries = _queries_from_snapshot(snapshot)

            if stages.get(STAGE_FETCH) != "done":
                # Stage 1 has no submitted external operation to resume.
                self.repository.mark_interrupted(analysis_id)
                return
            if stages.get(STAGE_CANDIDATES) != "done":
                candidates = await self._resume_seeds(analysis_id, request, gateway, plan)
                if candidates is None:
                    return
            if stages.get(STAGE_QUERIES) != "done":
                queries = await self._stage_queries(
                    analysis_id, request, company_name, services, candidates, client,
                )
                if queries is None:
                    return
            if stages.get(STAGE_CHECKS) != "done":
                await self._resume_checks(
                    analysis_id, request, company_name, candidates, queries, plan, gateway,
                    model_rows=snapshot["readiness"]["model_rows"],
                )
                if self._stopped(analysis_id):
                    return
            if stages.get(STAGE_SUMMARY) != "done":
                await self._stage_summary(analysis_id, client)
            if self._stopped(analysis_id):
                return
            await self._stage_report(analysis_id)
        except asyncio.CancelledError:
            raise
        except StorageError:
            self._stop(analysis_id)
            self._fail(analysis_id)
        except Exception as exc:  # noqa: BLE001 - a resumed task must not surface an exception
            LOGGER.error("SEO analysis %s resume failed: %s", analysis_id, type(exc).__name__)
            self._fail(analysis_id)

    async def _resume_seeds(
        self, analysis_id: str, request: SeoInput, gateway: SearchGateway, plan: ResumePlan,
    ) -> tuple[Candidate, ...] | None:
        """Finish stage 2 by polling only the key searches that were submitted."""
        self.repository.update_stage(analysis_id, STAGE_CANDIDATES, "running")
        results = await asyncio.gather(*(
            self._poll_seed(analysis_id, gateway, seed_index, operation_id)
            for seed_index, operation_id in plan.submitted_seeds
        ))
        if self._stopped(analysis_id):
            return None
        successful = tuple(result for result in results if result is not None)
        candidates = rank_candidates(successful, request.host)
        self.repository.replace_candidates(analysis_id, candidates)
        self.repository.update_stage(
            analysis_id, STAGE_CANDIDATES, "done",
            counters={
                "seeds": len(plan.submitted_seeds),
                "successful": len(successful),
                "candidates": len(candidates),
            },
        )
        return candidates

    async def _poll_seed(
        self, analysis_id: str, gateway: SearchGateway, seed_index: int, operation_id: str,
    ) -> SeedResult | None:
        try:
            documents = await self._poll_operation(analysis_id, gateway, operation_id)
            if documents is None:
                return None
            self.repository.save_seed_row(
                analysis_id, seed_index,
                status=STATUS_FOUND if documents else STATUS_ABSENT,
                operation_id=operation_id,
            )
            return SeedResult(query_index=seed_index, documents=self._document_values(documents))
        except StorageError:
            self._stop(analysis_id)
            raise
        except ProviderError as exc:
            self.repository.save_seed_row(
                analysis_id, seed_index, status=STATUS_ERROR, operation_id=operation_id, error=str(exc),
            )
            return None
        except Exception:  # noqa: BLE001 - one failed seed stays its own row
            self.repository.save_seed_row(
                analysis_id, seed_index, status=STATUS_ERROR,
                operation_id=operation_id, error=UNEXPECTED_FAILURE,
            )
            return None

    async def _resume_checks(
        self,
        analysis_id: str,
        request: SeoInput,
        company_name: str,
        candidates: tuple[Candidate, ...],
        queries: tuple[GeneratedQuery, ...],
        plan: ResumePlan,
        gateway: SearchGateway,
        *,
        model_rows: int,
    ) -> None:
        """Poll submitted generated queries; never replay a model call after a restart."""
        if not plan.submitted and model_rows == 0:
            # Stage 4 never started: both branches run as on a fresh analysis.
            selected = self._selected_connections(request.connection_ids)
            await self._stage_checks(
                analysis_id, request, company_name, selected, candidates, queries, gateway,
            )
            return
        self.repository.update_stage(analysis_id, STAGE_CHECKS, "running")
        await asyncio.gather(*(
            self._resume_search_row(
                analysis_id, request, candidates, query_index, queries[query_index], operation_id, gateway,
            )
            for query_index, operation_id in plan.submitted
            if 0 <= query_index < len(queries)
        ))
        if self._stopped(analysis_id):
            return
        self.repository.update_stage(
            analysis_id, STAGE_CHECKS, "done",
            counters={"search_rows": len(queries), "model_rows": model_rows},
        )

    async def _resume_search_row(
        self,
        analysis_id: str,
        request: SeoInput,
        candidates: tuple[Candidate, ...],
        query_index: int,
        query: GeneratedQuery,
        operation_id: str,
        gateway: SearchGateway,
    ) -> None:
        try:
            documents = await self._poll_operation(analysis_id, gateway, operation_id)
            if documents is None:
                return
            self._save_search_outcome(
                analysis_id, request, candidates, query_index, documents, operation_id,
            )
        except StorageError:
            self._stop(analysis_id)
            raise
        except ProviderError as exc:
            self.repository.save_search_row(
                analysis_id, query_index, status=STATUS_ERROR, operation_id=operation_id, error=str(exc),
            )
        except Exception:  # noqa: BLE001 - one failed row stays its own row
            self.repository.save_search_row(
                analysis_id, query_index, status=STATUS_ERROR,
                operation_id=operation_id, error=SEARCH_ROW_FAILED,
            )

    # -- shared helpers --------------------------------------------------

    async def _poll_operation(
        self, analysis_id: str, gateway: SearchGateway, operation_id: str,
    ) -> tuple[SearchDocument, ...] | None:
        """Poll one deferred operation with the shared backoff until it is done."""
        delay = self.poll_interval
        while True:
            if self._stopped(analysis_id):
                return None
            async with self.search_semaphore:
                if self._stopped(analysis_id):
                    return None
                await self.result_limiter.acquire()
                if self._stopped(analysis_id):
                    return None
                documents = await gateway.result(operation_id)
            if documents is not None:
                return tuple(documents)
            await asyncio.sleep(delay)
            delay = min(max(delay * 1.5, self.poll_interval), self.max_poll_interval)

    def _save_search_outcome(
        self,
        analysis_id: str,
        request: SeoInput,
        candidates: tuple[Candidate, ...],
        query_index: int,
        documents: tuple[SearchDocument, ...],
        operation_id: str | None,
    ) -> None:
        match = first_matching_result(request.host, documents)
        if match is None:
            self.repository.save_search_row(
                analysis_id, query_index, status=STATUS_ABSENT, operation_id=operation_id,
            )
        else:
            position, url = match
            self.repository.save_search_row(
                analysis_id, query_index, status=STATUS_FOUND, operation_id=operation_id,
                site_position=position, site_url=url,
            )
        self.repository.save_candidate_hits(
            analysis_id, query_index, self._candidate_hits(candidates, documents),
        )

    @staticmethod
    def _document_values(
        documents: Sequence[SearchDocument],
    ) -> tuple[tuple[int, str, str], ...]:
        return tuple(
            (position, document.url, document.title if isinstance(document.title, str) else "")
            for position, document in enumerate(documents[:TOP_RESULTS], start=1)
        )

    @staticmethod
    def _candidate_hits(
        candidates: Sequence[Candidate], documents: Sequence[SearchDocument],
    ) -> tuple[CandidateHit, ...]:
        """First top-ten hit of every recurring candidate, by the site-match rules."""
        hits: list[CandidateHit] = []
        for candidate in candidates:
            if not candidate.recurring:
                continue
            match = first_matching_result(candidate.host, documents)
            if match is None:
                continue
            position, url = match
            hits.append(CandidateHit(host=candidate.host, position=position, url=url))
        return tuple(hits)

    def _save_seed_error(
        self, analysis_id: str, seed_index: int, message: str, operation_id: str | None,
    ) -> None:
        self.repository.save_seed_row(
            analysis_id, seed_index, status=STATUS_ERROR, operation_id=operation_id, error=message,
        )

    def _save_search_error(
        self, analysis_id: str, query_index: int, message: str, operation_id: str | None,
    ) -> None:
        self.repository.save_search_row(
            analysis_id, query_index, status=STATUS_ERROR, operation_id=operation_id, error=message,
        )

    def _save_cancelled_search_row(
        self, analysis_id: str, query_index: int, operation_id: str | None = None,
    ) -> None:
        """Record a row that was cancelled before or right after its paid submit."""
        if analysis_id not in self.cancelled:
            return
        self.repository.save_search_row(
            analysis_id, query_index, status=STATUS_CANCELLED, operation_id=operation_id,
        )

    def _fatal_stage(self, analysis_id: str, stage: int, message: str) -> None:
        """Mark a fatal stage error and end the run before any further paid call."""
        if self._stopped(analysis_id):
            return
        self.repository.update_stage(analysis_id, stage, "error", error=message)
        self.repository.fail_analysis(analysis_id)
        return

    def _fail(self, analysis_id: str) -> None:
        try:
            self.repository.fail_analysis(analysis_id)
        except AppError:
            LOGGER.error("SEO analysis %s could not be marked failed", analysis_id)

    def _selected_connections(self, connection_ids: Sequence[str]) -> tuple[tuple[str, str], ...]:
        """Validate that every selected connection exists and has a key."""
        selected: list[tuple[str, str]] = []
        for connection_id in connection_ids:
            try:
                connection = self.connections.require(connection_id)
            except StorageError as exc:
                raise ConfigurationError(str(exc)) from exc
            if not self.connections.is_configured(connection_id):
                raise ConfigurationError(MISSING_KEY_MESSAGE)
            selected.append((connection.id, connection.name))
        return tuple(selected)

    def _prepare_provider(self, connection_id: str) -> tuple[AnswerProvider | None, str | None]:
        """Build one adapter, or the safe message each of its rows will report."""
        try:
            key = self.connections.api_key(connection_id)
            if not key:
                return None, MISSING_KEY_MESSAGE
            return self.provider_factory(self.connections.require(connection_id), key), None
        except AppError as exc:
            return None, str(exc)
        except Exception:  # noqa: BLE001 - a broken adapter affects one connection only
            return None, SETUP_FAILURE_MESSAGE

    @staticmethod
    async def _ask(
        provider: AnswerProvider | None, setup_error: str | None, prompt: str,
    ) -> tuple[str | None, str | None]:
        """Answer one prompt off the loop; a failure is that row's safe error."""
        if provider is None or setup_error is not None:
            return None, setup_error or SETUP_FAILURE_MESSAGE
        try:
            answer = await asyncio.to_thread(provider.answer, prompt)
        except ProviderError as exc:
            return None, str(exc)
        except Exception:  # noqa: BLE001 - a broken adapter is a failed row, not a crash
            return None, CALL_FAILURE_MESSAGE
        if not isinstance(answer, str) or not answer.strip():
            return None, CALL_FAILURE_MESSAGE
        return answer, None

    @staticmethod
    def _close(provider: AnswerProvider | None) -> None:
        if provider is None:
            return
        try:
            provider.close()
        except Exception:  # noqa: BLE001, S110 - releasing HTTP resources is best effort
            pass


def _request_from_snapshot(snapshot: dict) -> SeoInput:
    data = snapshot["input"]
    return SeoInput(
        url=data["url"],
        host=data["host"],
        sphere=data["sphere"],
        seeds=tuple(data["seeds"]),
        services=tuple(data["services"]),
        connection_ids=tuple(data["connection_ids"]),
    )


def _candidates_from_snapshot(snapshot: dict) -> tuple[Candidate, ...]:
    return tuple(
        Candidate(
            host=item["host"],
            title=item["title"],
            occurrences=item["occurrences"],
            average_position=item["average_position"],
            seed_indexes=tuple(item["seed_indexes"]),
            recurring=bool(item["recurring"]),
        )
        for item in snapshot["candidates"]
    )


def _queries_from_snapshot(snapshot: dict) -> tuple[GeneratedQuery, ...]:
    return tuple(
        GeneratedQuery(
            text=item["text"],
            category=item["category"],
            service=item["service"],
            flags=QueryFlags(**item["flags"]),
        )
        for item in snapshot["queries"]
    )


__all__ = ["SeoService"]
