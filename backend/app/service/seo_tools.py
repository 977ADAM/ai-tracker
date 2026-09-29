"""The server side of the SEO agent tools: budgets, rules, storage, and trace.

Every tool the agents may call is implemented here. The model chooses a name and
arguments; this class validates them, checks the run budget and the data
dependencies *before* any external call, performs the action through a port,
persists the result through `SeoRepository`, and appends exactly one trace step.
A refusal or a failed source becomes a compact JSON result — a domain or
provider error never escapes to the graph, while a storage failure still does,
because it must stop the run instead of being reported as a model result.

Idempotency is owned here as well: a `yandex_search` for an already checked
query returns the stored SERP and never submits again, a submitted operation is
polled through its stored ID instead of being sent a second time, and
`ask_models` skips every pair that already has a stored model row.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from urllib.parse import urlsplit

from app.core.errors import AppError, ProviderError, StorageError, ValidationError
from app.db.seo import SeoRepository
from app.domain.matching import mentions_phrase, normalize_text
from app.domain.providers import AnswerProvider, ProviderFactory
from app.domain.search import (
    TOP_RESULTS,
    SearchDocument,
    SearchGateway,
    first_matching_result,
    result_url_host,
)
from app.domain.seo import (
    QUERY_CATEGORIES,
    Candidate,
    CandidateHit,
    SeedResult,
    SeoInput,
    accept_generated_queries,
    flag_queries,
    mentions_host,
    merge_services,
    rank_candidates,
)
from app.domain.seo_llm import ToolSchema
from app.domain.seo_tools import (
    AGENT_TOOLS,
    BUDGET_EXHAUSTED,
    CANCELLED,
    INVALID_AGENT,
    MAX_FETCH_PAGES,
    SEARCH_REGION,
    SPECIALIST_AGENTS,
    SUPERVISOR_ONLY,
    TOOL_NOT_ALLOWED,
    UNKNOWN_TOOL,
    BudgetExceeded,
    SeoBudget,
    SeoCancelled,
    ToolRejected,
    tools_for,
    validate_arguments,
)
from app.domain.site_fetch import (
    FetchedPage,
    SiteFetcher,
    canonical_host,
    same_site_host,
)
from app.integrations.site_fetcher import FETCH_FAILED
from app.service.checks import (
    CALL_FAILURE_MESSAGE,
    MISSING_KEY_MESSAGE,
    SETUP_FAILURE_MESSAGE,
)
from app.service.connections import ConnectionService
from app.service.search import (
    DEFAULT_POLL_INTERVAL,
    MAX_POLL_INTERVAL,
    UNEXPECTED_FAILURE,
)

LOGGER = logging.getLogger(__name__)

MAX_SEARCH_CONCURRENCY = 5
MAX_MODEL_CONCURRENCY = 5
PAGE_EXCERPT_CHARS = 4000
TRACE_ARGUMENT_CHARS = 200
TRACE_RESULT_CHARS = 300
TRACE_LIST_ITEMS = 5
ROWS_PAGE_SIZE = 100
MAX_REPORTED_ERRORS = 20
DEFAULT_REPORT_MODEL = "seo-llm"

STATUS_PENDING = "waiting"
STATUS_FOUND = "found"
STATUS_ABSENT = "absent"
STATUS_ERROR = "error"
STATUS_BUDGET = "budget"
STATUS_SKIPPED = "skipped"
OUTCOME_REUSED = "reused"
OUTCOME_FOUND = "found"
OUTCOME_ABSENT = "absent"
OUTCOME_ERROR = "error"
OUTCOME_SKIPPED = "skipped"
OUTCOME_BUDGET = "budget"

CHECKED_STATUSES = (STATUS_FOUND, STATUS_ABSENT)
ERROR_ROW_STATUSES = frozenset({"error", "interrupted", "cancelled"})

STEP_TOOL = "tool"
STEP_HANDOFF = "handoff"
STEP_DONE = "done"
STEP_REJECTED = "rejected"
STEP_ERROR = "error"

UNAVAILABLE = "Инструмент временно недоступен"
SEARCH_UNAVAILABLE = "Поиск Яндекса недоступен"
OTHER_HOST = "Можно читать только страницы введённого сайта"
PAGE_NOT_FOUND = "Страница не найдена среди прочитанных"
PAGES_FIRST = "Сначала прочитайте хотя бы одну страницу сайта"
SITE_FACTS_FIRST = "Сначала сохраните сведения о сайте"
FACTS_ALREADY = "Сведения о сайте уже сохранены"
CANDIDATES_ALREADY = "Кандидаты уже сохранены"
QUERIES_ALREADY = "Сгенерированные запросы уже сохранены"
REPORT_ALREADY = "Отчёт уже сохранён"
SEEDS_FIRST = "Сначала получите выдачи по ключевым запросам"
QUERIES_FIRST = "Сначала сохраните сгенерированные запросы"
NOT_STORED_QUERY = "Запрос не сохранён в этом анализе"
UNKNOWN_CONNECTION = "Выбрано неизвестное подключение"


class SeoToolbox:
    """Executes the SEO tools of one analysis under its own budget and trace.

    One instance serves the whole run: `schemas_for` records which agent is
    acting, so a specialist can never call the tool of another agent or the
    supervisor's control tools. `call` is the only entry point and always answers
    with a compact JSON string.
    """

    def __init__(
        self,
        repository: SeoRepository,
        fetcher: SiteFetcher,
        gateway: SearchGateway | None,
        connections: ConnectionService,
        provider_factory: ProviderFactory,
        *,
        analysis_id: str,
        input: SeoInput,
        connection_ids: Sequence[str],
        budget: SeoBudget,
        submit_search: Callable[[str], Awaitable[str]] | None = None,
        poll_search: Callable[[str], Awaitable[tuple[SearchDocument, ...] | None]] | None = None,
        on_step: Callable[[int, str, str], None] | None = None,
        model_name: str = "",
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        max_poll_interval: float = MAX_POLL_INTERVAL,
        max_search_concurrency: int = MAX_SEARCH_CONCURRENCY,
        max_model_concurrency: int = MAX_MODEL_CONCURRENCY,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self.repository = repository
        self.fetcher = fetcher
        self.gateway = gateway
        self.connections = connections
        self.provider_factory = provider_factory
        self.submit_search = submit_search
        self.poll_search = poll_search
        self.analysis_id = analysis_id
        self.input = input
        self.connection_ids = tuple(connection_ids)
        self.budget = budget
        self.on_step = on_step
        # The run's own cancellation probe: the runtime sets it after building
        # the toolbox, so a cancelled analysis stops before the next paid call.
        self.should_stop = should_stop
        self.model_name = model_name or DEFAULT_REPORT_MODEL
        self.poll_interval = poll_interval
        self.max_poll_interval = max_poll_interval

        # The run's own state: `finish_run` sets these, the Task 4 runtime reads
        # them and finalizes the analysis itself.
        self.finished = False
        self.finish_reason: str | None = None
        self.exhausted = False
        self.current_agent: str | None = None
        self._active_agent = "supervisor"

        self._search_semaphore = asyncio.Semaphore(max_search_concurrency)
        self._model_semaphore = asyncio.Semaphore(max_model_concurrency)
        # One lock per searchable query and per model pair: the agent runtime may
        # run several tool calls of one turn in parallel, and the second call for
        # the same query must read the stored result instead of paying again.
        self._locks: dict[tuple, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        self._pairs_cache: set[tuple[str, int]] | None = None
        # The company name and the candidate list are read by every answered row;
        # one cached read per write keeps a 200-row batch from rebuilding the
        # report 200 times.
        self._company_name_cache: str | None = None
        self._candidates_cache: list | None = None
        self._pages: dict[str, FetchedPage] = {}
        self._pages_loaded = False
        self._site_facts_saved = False
        self._candidates_saved = False
        self._queries_saved = False
        self._report_saved = False

    # -- public API ------------------------------------------------------

    def schemas_for(self, agent: str) -> tuple[ToolSchema, ...]:
        """Return the tools one agent may see and remember it as the active agent."""
        tools = tools_for(agent)
        self.current_agent = agent
        return tools

    def cancelled(self) -> bool:
        """True while this run is cancelled: no further step or paid call starts."""
        return bool(self.should_stop is not None and self.should_stop())

    def _require_not_cancelled(self) -> None:
        """Stop the graph at a tool boundary; cancellation is not a tool result."""
        if self.cancelled():
            raise SeoCancelled(CANCELLED)

    async def call(
        self,
        name: str,
        arguments: Mapping[str, object] | None = None,
        *,
        agent: str | None = None,
    ) -> str:
        """Validate, budget, execute, and trace one tool call; always answer with JSON.

        Domain and provider failures become a safe `rejected`/`error` result for
        the model. `StorageError` and `SeoCancelled` still propagate: a broken
        database must stop the run, and a cancelled run must not start another
        step or another paid call.
        """
        self._require_not_cancelled()
        resolved = agent if agent is not None else self.current_agent
        step_agent = resolved or "supervisor"
        self._active_agent = step_agent
        self._mark_agent_running(step_agent)
        try:
            self.budget = self.budget.spend_tool_call()
            self._require_allowed(name, resolved)
            safe: object = validate_arguments(name, arguments)
        except BudgetExceeded as exc:
            self.exhausted = True
            return self._record_rejection(step_agent, name, arguments, str(exc))
        except ToolRejected as exc:
            return self._record_rejection(step_agent, name, arguments, str(exc))

        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:  # unreachable: `validate_arguments` knows every tool name
            return self._record_rejection(step_agent, name, safe, UNKNOWN_TOOL)
        try:
            result = await handler(safe)
        except asyncio.CancelledError:
            raise
        except (StorageError, SeoCancelled):
            raise
        except BudgetExceeded as exc:
            self.exhausted = True
            return self._record_rejection(step_agent, name, safe, str(exc))
        except ToolRejected as exc:
            return self._record_rejection(step_agent, name, safe, str(exc))
        except AppError as exc:
            # Adapter messages are fixed and safe by contract.
            return self._record_failure(step_agent, name, safe, str(exc))
        except Exception:  # noqa: BLE001 - a broken tool is a safe result, not a crash
            LOGGER.error("SEO tool %s failed unexpectedly", name)
            return self._record_failure(step_agent, name, safe, UNAVAILABLE)

        self._record(step_agent, name, safe, STEP_DONE, result=result)
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))

    # -- trace -----------------------------------------------------------

    def _mark_agent_running(self, agent: str) -> None:
        """Show the acting agent as `running` from its first tool call on.

        The interface reads the agent state while the run is live, so an agent
        that started working must not stay `pending`. A `save_*` tool still ends
        its own agent with `done`; the upsert here only moves `pending` forward
        and never rewrites a terminal status.
        """
        try:
            for entry in self.repository.agents(self.analysis_id):
                if entry["agent"] != agent:
                    continue
                if entry["status"] == "pending":
                    self.repository.upsert_agent(self.analysis_id, agent, "running")
                return
        except AppError:
            LOGGER.error("SEO agent state could not be marked running")

    def _require_allowed(self, name: str, agent: str | None) -> None:
        """Refuse a tool that is outside the acting agent's own subset."""
        if agent is None:
            return
        allowed = AGENT_TOOLS.get(agent)
        if allowed is None:
            raise ToolRejected(INVALID_AGENT)
        if name not in allowed:
            raise ToolRejected(TOOL_NOT_ALLOWED)

    def _record_rejection(self, agent: str, name: str, arguments: object, message: str) -> str:
        self._record(agent, name, arguments, STEP_REJECTED, error=message)
        return json.dumps({"status": "rejected", "error": message}, ensure_ascii=False)

    def _record_failure(self, agent: str, name: str, arguments: object, message: str) -> str:
        self._record(agent, name, arguments, STEP_ERROR, error=message)
        return json.dumps({"status": "error", "error": message}, ensure_ascii=False)

    def _record(
        self,
        agent: str,
        name: str,
        arguments: object,
        status: str,
        *,
        result: Mapping[str, object] | None = None,
        error: str | None = None,
    ) -> int:
        """Append one trace step; a broken observer never changes the result."""
        step_index = self.repository.append_step(
            self.analysis_id,
            agent,
            STEP_HANDOFF if name == "handoff_to" else STEP_TOOL,
            name,
            arguments=_trace_arguments(arguments),
            result_summary=_summarize(result) if result is not None else None,
            status=status,
            error=error,
        )
        if self.on_step is not None:
            try:
                self.on_step(step_index, name, status)
            except Exception:  # noqa: BLE001 - tracing is best effort for onlookers
                LOGGER.error("SEO trace observer failed for %s", name)
        return step_index

    # -- site tools ------------------------------------------------------

    async def _tool_fetch_site(self, args: Mapping[str, object]) -> dict:
        remaining = self.budget.max_pages - self.budget.pages
        if remaining <= 0:
            raise BudgetExceeded(BUDGET_EXHAUSTED)
        allowed = min(int(args.get("max_pages", MAX_FETCH_PAGES)), remaining)
        pages = await self._crawl()
        taken = tuple(pages[:allowed])
        if taken:
            self.budget = self.budget.spend_pages(len(taken))
            self._store_pages(taken)
        return {
            "pages": [{"url": page.url, "title": page.title, "chars": len(page.text)} for page in taken],
            "used_pages": self.budget.pages,
            "truncated": len(pages) > len(taken),
        }

    async def _tool_read_page(self, args: Mapping[str, object]) -> dict:
        url = str(args["url"])
        host = _url_host(url)
        if host is None or not same_site_host(self.input.host, host):
            raise ToolRejected(OTHER_HOST)
        if self.budget.pages >= self.budget.max_pages:
            raise BudgetExceeded(BUDGET_EXHAUSTED)
        pages = await self._crawl()
        page = _match_page(pages, url)
        if page is None:
            raise ToolRejected(PAGE_NOT_FOUND)
        self.budget = self.budget.spend_pages()
        self._store_pages((page,))
        return {"url": page.url, "title": page.title, "excerpt": page.text[:PAGE_EXCERPT_CHARS]}

    async def _tool_save_site_facts(self, args: Mapping[str, object]) -> dict:
        if self._site_facts_saved or self._agent_status("site") == "done":
            raise ToolRejected(FACTS_ALREADY)
        self._load_pages()
        if not self._pages:
            raise ToolRejected(PAGES_FIRST)
        company_name = str(args["company_name"])
        services = merge_services(self.input.services, args["services"])  # type: ignore[arg-type]
        self.repository.save_site_facts(
            self.analysis_id,
            company_name,
            services,
            tuple((page.url, page.title) for page in self._pages.values()),
        )
        self.repository.upsert_agent(self.analysis_id, "site", "done")
        self._site_facts_saved = True
        self._company_name_cache = None
        return {
            "status": "saved",
            "company_name": company_name,
            "services": list(services),
            "pages": len(self._pages),
        }

    async def _crawl(self) -> tuple[FetchedPage, ...]:
        """Crawl the entered host through the fetcher; its errors stay safe."""
        self._require_not_cancelled()
        try:
            return tuple(await self.fetcher.fetch(self.input.host))
        except AppError as exc:
            raise ToolRejected(str(exc)) from exc
        except Exception as exc:
            raise ToolRejected(FETCH_FAILED) from exc

    def _load_pages(self) -> None:
        """Read the stored pages once, so a resumed toolbox never drops them."""
        if self._pages_loaded:
            return
        self._pages_loaded = True
        for row in self.repository.pages(self.analysis_id):
            self._pages.setdefault(
                row["url"], FetchedPage(url=row["url"], title=row["title"], text=""),
            )

    def _store_pages(self, pages: Sequence[FetchedPage]) -> None:
        self._load_pages()
        for page in pages:
            self._pages[page.url] = page
        self.repository.save_pages(
            self.analysis_id, tuple((page.url, page.title) for page in self._pages.values()),
        )

    # -- competitor tools ------------------------------------------------

    async def _tool_yandex_search(self, args: Mapping[str, object]) -> dict:
        target = self._resolve_query(str(args["query"]))
        if target is None:
            raise ToolRejected(NOT_STORED_QUERY)
        outcome = await self._check_query(target)
        result: dict = {
            "status": outcome["status"],
            "documents": [_document_json(document) for document in outcome["documents"]],
            "reused": outcome["reused"],
        }
        if outcome["error"] is not None:
            result["error"] = outcome["error"]
        return result

    async def _tool_list_seed_results(self, args: Mapping[str, object]) -> dict:
        seeds = []
        for index, seed in enumerate(self.input.seeds):
            stored = self.repository.search_documents(self.analysis_id, index, seed=True)
            seeds.append({
                "index": index,
                "query": seed,
                "status": stored["status"] if stored is not None else "pending",
                "documents": [_document_json(document) for document in (stored["documents"] if stored else ())],
            })
        return {"seeds": seeds}

    async def _tool_save_candidates(self, args: Mapping[str, object]) -> dict:
        if self._candidates_saved or self._agent_status("competitors") == "done":
            raise ToolRejected(CANDIDATES_ALREADY)
        proposals = args["candidates"]
        successful = self._successful_seeds()
        if not successful and proposals:
            raise ToolRejected(SEEDS_FIRST)
        ranked = rank_candidates(
            tuple(SeedResult(query_index=index, documents=stored["documents"]) for index, stored in successful),
            self.input.host,
        )
        by_host = {candidate.host: candidate for candidate in ranked}
        chosen: list[Candidate] = []
        skipped: list[str] = []
        for item in proposals:  # type: ignore[union-attr]
            host = _bare_host(str(item["host"]))
            candidate = by_host.get(host)
            if candidate is None:
                skipped.append(host)
                continue
            note = str(item.get("note") or "")
            if note and not candidate.title:
                candidate = replace(candidate, title=note)
            chosen.append(candidate)
        chosen.sort(key=lambda candidate: (-candidate.occurrences, candidate.average_position, candidate.host))
        self.repository.replace_candidates(self.analysis_id, chosen)
        self.repository.upsert_agent(self.analysis_id, "competitors", "done")
        self._candidates_saved = True
        self._candidates_cache = None
        return {
            "status": "saved",
            "candidates": [
                {
                    "host": candidate.host,
                    "occurrences": candidate.occurrences,
                    "average_position": candidate.average_position,
                    "recurring": candidate.recurring,
                }
                for candidate in chosen
            ],
            "recurring": [candidate.host for candidate in chosen if candidate.recurring],
            "skipped": skipped,
        }

    def _successful_seeds(self) -> tuple[tuple[int, dict], ...]:
        """Key queries that produced a verdict; a failed row is never a verdict."""
        successful: list[tuple[int, dict]] = []
        for index in range(len(self.input.seeds)):
            stored = self.repository.search_documents(self.analysis_id, index, seed=True)
            if stored is not None and stored["status"] in CHECKED_STATUSES:
                successful.append((index, stored))
        return tuple(successful)

    # -- query tools -----------------------------------------------------

    async def _tool_read_facts(self, args: Mapping[str, object]) -> dict:
        snapshot = self.repository.snapshot(self.analysis_id)
        return {
            "company_name": snapshot["company_name"],
            "services": list(snapshot["services"]),
            "pages": [page["url"] for page in snapshot["pages"]],
        }

    async def _tool_save_queries(self, args: Mapping[str, object]) -> dict:
        if self._queries_saved or self._agent_status("queries") == "done":
            raise ToolRejected(QUERIES_ALREADY)
        if not self._facts_ready():
            raise ToolRejected(SITE_FACTS_FIRST)
        snapshot = self.repository.snapshot(self.analysis_id)
        try:
            accepted = accept_generated_queries(
                {"queries": list(args["queries"])}, tuple(snapshot["services"]),
            )
        except ValidationError as exc:
            raise ToolRejected(str(exc)) from exc
        flagged = flag_queries(
            accepted,
            snapshot["company_name"],
            self.input.host,
            tuple(candidate["host"] for candidate in snapshot["candidates"]),
        )
        self.repository.replace_queries(self.analysis_id, flagged)
        self.repository.upsert_agent(self.analysis_id, "queries", "done")
        self._queries_saved = True
        return {
            "status": "saved",
            "saved": len(flagged),
            "categories": {
                category: sum(1 for query in flagged if query.category == category)
                for category in QUERY_CATEGORIES
            },
            "branded": sum(1 for query in flagged if query.flags.branded),
        }

    # -- check tools -----------------------------------------------------

    async def _tool_search_many(self, args: Mapping[str, object]) -> dict:
        snapshot = self.repository.snapshot(self.analysis_id)
        stored = {normalize_text(item["text"]): item["index"] for item in snapshot["queries"]}
        if not stored:
            raise ToolRejected(QUERIES_FIRST)
        targets, errors = self._targets(args.get("queries"), snapshot["queries"], stored)

        async def run(target: dict) -> dict:
            async with self._search_semaphore:
                try:
                    return await self._check_query(target)
                except BudgetExceeded:
                    self.exhausted = True
                    return _outcome(OUTCOME_BUDGET, error=BUDGET_EXHAUSTED)

        results = await asyncio.gather(*(run(target) for target in targets))
        counts = _count_outcomes(results)
        errors.extend(
            {"query": target["text"], "error": result["error"]}
            for target, result in zip(targets, results, strict=True)
            if result["error"] is not None
        )
        return {
            "found": counts[OUTCOME_FOUND],
            "absent": counts[OUTCOME_ABSENT],
            "error": counts[OUTCOME_ERROR],
            "reused": counts[OUTCOME_REUSED],
            "budget_exhausted": counts[OUTCOME_BUDGET] > 0,
            "errors": errors[:MAX_REPORTED_ERRORS],
        }

    async def _tool_ask_models(self, args: Mapping[str, object]) -> dict:
        snapshot = self.repository.snapshot(self.analysis_id)
        stored = {normalize_text(item["text"]): item["index"] for item in snapshot["queries"]}
        if not stored:
            raise ToolRejected(QUERIES_FIRST)
        targets, errors = self._targets(args.get("queries"), snapshot["queries"], stored)
        connections = [str(item) for item in (args.get("connection_ids") or self.connection_ids)]
        if any(connection_id not in self.connection_ids for connection_id in connections):
            raise ToolRejected(UNKNOWN_CONNECTION)
        existing = self._stored_model_pairs()
        prepared = {connection_id: self._prepare_provider(connection_id) for connection_id in connections}

        async def run(connection_id: str, target: dict) -> dict:
            async with self._model_semaphore:
                return await self._answer_one(connection_id, target, existing, prepared[connection_id])

        try:
            results = await asyncio.gather(*(
                run(connection_id, target) for connection_id in connections for target in targets
            ))
        finally:
            for provider, _error, _name in prepared.values():
                self._close(provider)

        per_connection = {
            connection_id: {"found": 0, "absent": 0, "error": 0, "skipped": 0, "budget": 0}
            for connection_id in connections
        }
        for result in results:
            bucket = per_connection[result["connection_id"]]
            bucket[result["outcome"]] = bucket.get(result["outcome"], 0) + 1
        errors.extend(
            {"connection_id": result["connection_id"], "query": result["query"], "error": result["error"]}
            for result in results
            if result["error"] is not None and result["outcome"] == OUTCOME_ERROR
        )
        totals = _count_outcomes(results)
        return {
            "answers": totals[OUTCOME_FOUND] + totals[OUTCOME_ABSENT] + totals[OUTCOME_REUSED],
            "found": totals[OUTCOME_FOUND],
            "absent": totals[OUTCOME_ABSENT],
            "error": totals[OUTCOME_ERROR],
            "skipped": totals[OUTCOME_SKIPPED],
            "budget_exhausted": totals[OUTCOME_BUDGET] > 0,
            "connections": per_connection,
            "errors": errors[:MAX_REPORTED_ERRORS],
        }

    async def _tool_read_checks(self, args: Mapping[str, object]) -> dict:
        searches = self._all_rows("search")
        models = self._all_rows("model")
        errors = [
            {"kind": "search", "query": item.get("query"), "connection_id": None, "error": item["error"]}
            for item in searches
            if item["error"]
        ]
        errors.extend(
            {
                "kind": "model",
                "query": item.get("query"),
                "connection_id": item.get("connection_id"),
                "error": item["error"],
            }
            for item in models
            if item["error"]
        )
        return {
            "searches": _summarize_rows(searches),
            "models": _summarize_rows(models),
            "errors": errors[:MAX_REPORTED_ERRORS],
        }

    async def _tool_read_metrics(self, args: Mapping[str, object]) -> dict:
        # The report agent receives only server-computed aggregates: model text
        # can never change a number.
        return self.repository.snapshot(self.analysis_id)["aggregates"]

    async def _tool_save_report(self, args: Mapping[str, object]) -> dict:
        if self._report_saved or self._agent_status("report") == "done":
            raise ToolRejected(REPORT_ALREADY)
        summary = str(args["summary"])
        recommendations = str(args["recommendations"])
        self.repository.save_conclusions(
            self.analysis_id,
            summary=summary,
            recommendations=recommendations,
            model=self.model_name,
        )
        self.repository.upsert_agent(self.analysis_id, "report", "done")
        self._report_saved = True
        return {
            "status": "saved",
            "summary_chars": len(summary),
            "recommendations_chars": len(recommendations),
        }

    # -- supervisor tools ------------------------------------------------

    async def _tool_handoff_to(self, args: Mapping[str, object]) -> dict:
        if self._active_agent != "supervisor":
            raise ToolRejected(SUPERVISOR_ONLY)
        target = str(args["agent"]).strip().lower()
        if target not in SPECIALIST_AGENTS:
            raise ToolRejected(INVALID_AGENT)
        self.budget = self.budget.spend_handoff()
        agents = {agent["agent"]: agent for agent in self.repository.agents(self.analysis_id)}
        entry = agents.get(target, {"status": "pending", "error": None})
        return {
            "agent": target,
            "agent_status": entry["status"],
            "agent_error": entry["error"],
            "reason": str(args.get("reason") or ""),
            "budget": self.budget.as_dict(),
            "finished": self.finished,
        }

    async def _tool_finish_run(self, args: Mapping[str, object]) -> dict:
        if self._active_agent != "supervisor":
            raise ToolRejected(SUPERVISOR_ONLY)
        # The toolbox only flags the end; the Task 4 runtime finalizes the run.
        self.finished = True
        self.finish_reason = str(args.get("reason") or "")
        return {"finished": True, "reason": self.finish_reason, "budget": self.budget.as_dict()}

    async def _tool_read_status(self, args: Mapping[str, object]) -> dict:
        snapshot = self.repository.snapshot(self.analysis_id)
        return {
            "agents": [
                {"agent": agent["agent"], "status": agent["status"], "error": agent["error"]}
                for agent in snapshot["agents"]
            ],
            "budget": self.budget.as_dict(),
            "stored": {
                "pages": len(snapshot["pages"]),
                "candidates": len(snapshot["candidates"]),
                "queries": len(snapshot["queries"]),
                "search_rows": snapshot["counters"]["search_rows"],
                "model_rows": snapshot["counters"]["model_rows"],
                "report_ready": snapshot["readiness"]["report_ready"],
            },
            "finished": self.finished,
            "finish_reason": self.finish_reason,
            "exhausted": self.exhausted,
        }

    # -- shared helpers --------------------------------------------------

    def _resolve_query(self, query: str) -> dict | None:
        """Map a query text onto a key query or a saved generated query."""
        key = normalize_text(query)
        if not key:
            return None
        for index, seed in enumerate(self.input.seeds):
            if normalize_text(seed) == key:
                return {"kind": "seed", "index": index, "text": seed}
        for item in self.repository.snapshot(self.analysis_id)["queries"]:
            if normalize_text(item["text"]) == key:
                return {"kind": "generated", "index": item["index"], "text": item["text"]}
        return None

    async def _check_query(self, target: Mapping[str, object]) -> dict:
        """Check one stored query with at most one paid submit.

        A stored SERP is returned as is; an operation that was already paid for
        is polled through its stored ID; only a query with neither is submitted.
        The per-query lock serializes parallel calls, so the loser of the race
        reads the winner's stored result instead of submitting a second time.
        """
        async with await self._lock_for(("search", str(target["kind"]), int(target["index"]))):
            return await self._check_query_locked(target)

    async def _check_query_locked(self, target: Mapping[str, object]) -> dict:
        stored = self._saved_serp(target)
        if stored is not None:
            return _outcome(
                OUTCOME_REUSED, status=str(stored["status"]),
                documents=stored["documents"], reused=True,
            )
        # A batch of parallel checks re-reads this before every paid submit: a
        # run cancelled mid-batch must not send the queries still queued.
        self._require_not_cancelled()
        operation_id = self._pending_operation(target)
        if operation_id is None:
            self.budget = self.budget.spend_search()
            try:
                operation_id = await self._submit(str(target["text"]))
            except AppError as exc:
                self._save_serp_error(target, str(exc), None)
                return _outcome(OUTCOME_ERROR, error=str(exc))
            except Exception:  # noqa: BLE001 - one failed row stays its own row
                self._save_serp_error(target, UNEXPECTED_FAILURE, None)
                return _outcome(OUTCOME_ERROR, error=UNEXPECTED_FAILURE)
            self._save_pending(target, operation_id)
        documents, error = await self._poll_documents(operation_id)
        if error is not None:
            self._save_serp_error(target, error, operation_id)
            return _outcome(OUTCOME_ERROR, error=error)
        self._save_serp_outcome(target, documents, operation_id)
        outcome = OUTCOME_FOUND if documents else OUTCOME_ABSENT
        return _outcome(outcome, documents=self._document_triples(documents))

    async def _submit(self, query: str) -> str:
        if self.submit_search is not None:
            return await self.submit_search(query)
        if self.gateway is None:
            raise ProviderError(SEARCH_UNAVAILABLE)
        return await self.gateway.submit(query, SEARCH_REGION)

    async def _poll(self, operation_id: str) -> tuple[SearchDocument, ...] | None:
        if self.poll_search is not None:
            return await self.poll_search(operation_id)
        if self.gateway is None:
            raise ProviderError(SEARCH_UNAVAILABLE)
        return await self.gateway.result(operation_id)

    async def _poll_documents(self, operation_id: str) -> tuple[tuple, str | None]:
        """Poll one deferred operation with backoff until its documents arrive."""
        delay = self.poll_interval
        while True:
            try:
                documents = await self._poll(operation_id)
            except AppError as exc:
                return (), str(exc)
            except Exception:  # noqa: BLE001 - a failed row keeps its safe error
                return (), UNEXPECTED_FAILURE
            if documents is not None:
                return tuple(documents), None
            await asyncio.sleep(delay)
            delay = min(max(delay * 1.5, self.poll_interval), self.max_poll_interval)

    def _saved_serp(self, target: Mapping[str, object]) -> dict | None:
        return self.repository.search_documents(
            self.analysis_id, int(target["index"]), seed=target["kind"] == "seed",
        )

    def _pending_operation(self, target: Mapping[str, object]) -> str | None:
        """Return the stored operation ID of an already paid, unfinished query."""
        plan = self.repository.resume_plan(self.analysis_id)
        if target["kind"] == "seed":
            return dict(plan.submitted_seeds).get(int(target["index"]))
        return dict(plan.submitted).get(int(target["index"]))

    def _save_pending(self, target: Mapping[str, object], operation_id: str) -> None:
        index = int(target["index"])
        if target["kind"] == "seed":
            self.repository.save_seed_row(
                self.analysis_id, index, status=STATUS_PENDING, operation_id=operation_id,
            )
        else:
            self.repository.save_search_row(
                self.analysis_id, index, status=STATUS_PENDING, operation_id=operation_id,
            )

    def _save_serp_outcome(
        self, target: Mapping[str, object], documents: tuple[SearchDocument, ...], operation_id: str,
    ) -> None:
        index = int(target["index"])
        match = first_matching_result(self.input.host, documents)
        status = STATUS_FOUND if match is not None else STATUS_ABSENT
        if target["kind"] == "seed":
            self.repository.save_seed_row(
                self.analysis_id, index, status=status, operation_id=operation_id,
            )
        else:
            if match is None:
                self.repository.save_search_row(
                    self.analysis_id, index, status=status, operation_id=operation_id,
                )
            else:
                self.repository.save_search_row(
                    self.analysis_id, index, status=status, operation_id=operation_id,
                    site_position=match[0], site_url=match[1],
                )
            self.repository.save_candidate_hits(
                self.analysis_id, index, self._candidate_hits(documents),
            )
        self.repository.save_search_documents(
            self.analysis_id, index, self._document_triples(documents),
            status=status, seed=target["kind"] == "seed",
        )

    def _save_serp_error(
        self, target: Mapping[str, object], message: str, operation_id: str | None,
    ) -> None:
        index = int(target["index"])
        if target["kind"] == "seed":
            self.repository.save_seed_row(
                self.analysis_id, index, status=STATUS_ERROR, operation_id=operation_id, error=message,
            )
        else:
            self.repository.save_search_row(
                self.analysis_id, index, status=STATUS_ERROR, operation_id=operation_id, error=message,
            )
        # The failed row is stored as an error, never as an absent site, and the
        # stored outcome keeps a repeated call from paying for it twice.
        self.repository.save_search_documents(
            self.analysis_id, index, (), status=STATUS_ERROR, seed=target["kind"] == "seed",
        )

    def _candidate_hits(self, documents: Sequence[SearchDocument]) -> tuple[CandidateHit, ...]:
        if self._candidates_cache is None:
            self._candidates_cache = list(self.repository.snapshot(self.analysis_id)["candidates"])
        hits: list[CandidateHit] = []
        for candidate in self._candidates_cache:
            if not candidate["recurring"]:
                continue
            match = first_matching_result(candidate["host"], documents)
            if match is None:
                continue
            hits.append(CandidateHit(host=candidate["host"], position=match[0], url=match[1]))
        return tuple(hits)

    def _document_triples(
        self, documents: Sequence[SearchDocument],
    ) -> tuple[tuple[int, str, str], ...]:
        return tuple(
            (position, document.url, document.title if isinstance(document.title, str) else "")
            for position, document in enumerate(documents[:TOP_RESULTS], start=1)
        )

    def _targets(
        self, requested: object, queries: Sequence[Mapping], stored: Mapping[str, int],
    ) -> tuple[list[dict], list[dict]]:
        """Map requested texts onto saved queries, reporting unknown ones safely."""
        if requested is None:
            return (
                [
                    {"kind": "generated", "index": item["index"], "text": item["text"]}
                    for item in queries
                ],
                [],
            )
        targets: list[dict] = []
        errors: list[dict] = []
        seen: set[int] = set()
        for text in requested:  # type: ignore[union-attr]
            query = str(text)
            index = stored.get(normalize_text(query))
            if index is None:
                errors.append({"query": query, "error": NOT_STORED_QUERY})
                continue
            if index in seen:
                # The same query twice in one batch is one paid check, not two.
                continue
            seen.add(index)
            targets.append({"kind": "generated", "index": index, "text": query})
        return targets, errors

    async def _answer_one(
        self,
        connection_id: str,
        target: Mapping[str, object],
        existing: set[tuple[str, int]],
        prepared: tuple[AnswerProvider | None, str | None, str],
    ) -> dict:
        query_index = int(target["index"])
        if (connection_id, query_index) in existing:
            return self._skipped(connection_id, target)
        async with await self._lock_for(("model", connection_id, query_index)):
            # Re-read the stored pairs inside the lock: a parallel call of the
            # same turn may have answered this pair while this one waited.
            if (connection_id, query_index) in self._stored_model_pairs():
                return self._skipped(connection_id, target)
            return await self._answer_one_locked(connection_id, target, prepared)

    def _skipped(self, connection_id: str, target: Mapping[str, object]) -> dict:
        # Idempotency: a stored pair is never paid for again.
        return {
            "connection_id": connection_id, "outcome": OUTCOME_SKIPPED,
            "query": target["text"], "error": None,
        }

    async def _answer_one_locked(
        self,
        connection_id: str,
        target: Mapping[str, object],
        prepared: tuple[AnswerProvider | None, str | None, str],
    ) -> dict:
        query_index = int(target["index"])
        # A cancelled batch pays for no further provider call.
        self._require_not_cancelled()
        try:
            self.budget = self.budget.spend_model_answer()
        except BudgetExceeded:
            self.exhausted = True
            return {
                "connection_id": connection_id, "outcome": OUTCOME_BUDGET,
                "query": target["text"], "error": BUDGET_EXHAUSTED,
            }
        provider, setup_error, provider_name = prepared
        answer, error = await self._ask(provider, setup_error, str(target["text"]))
        if error is not None:
            self.repository.save_model_row(
                self.analysis_id, connection_id, provider_name, query_index,
                status=STATUS_ERROR, error=error,
            )
            self._remember_pair(connection_id, query_index)
            return {
                "connection_id": connection_id, "outcome": OUTCOME_ERROR,
                "query": target["text"], "error": error,
            }
        name_mentioned = mentions_phrase(answer or "", self._company_name())
        host_mentioned = mentions_host(answer or "", self.input.host)
        found = name_mentioned or host_mentioned
        self.repository.save_model_row(
            self.analysis_id, connection_id, provider_name, query_index,
            status=STATUS_FOUND if found else STATUS_ABSENT,
            answer=answer,
            name_mentioned=name_mentioned,
            host_mentioned=host_mentioned,
        )
        self._remember_pair(connection_id, query_index)
        return {
            "connection_id": connection_id,
            "outcome": OUTCOME_FOUND if found else OUTCOME_ABSENT,
            "query": target["text"],
            "error": None,
        }

    def _prepare_provider(self, connection_id: str) -> tuple[AnswerProvider | None, str | None, str]:
        """Build one adapter, or the safe message every row of it will report."""
        try:
            connection = self.connections.require(connection_id)
        except AppError as exc:
            return None, str(exc), connection_id
        except Exception:  # noqa: BLE001 - a broken connection affects one group only
            return None, SETUP_FAILURE_MESSAGE, connection_id
        name = connection.name
        try:
            key = self.connections.api_key(connection_id)
            if not key:
                return None, MISSING_KEY_MESSAGE, name
            return self.provider_factory(connection, key), None, name
        except AppError as exc:
            return None, str(exc), name
        except Exception:  # noqa: BLE001 - a broken adapter affects one group only
            return None, SETUP_FAILURE_MESSAGE, name

    @staticmethod
    async def _ask(
        provider: AnswerProvider | None, setup_error: str | None, prompt: str,
    ) -> tuple[str | None, str | None]:
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

    def _company_name(self) -> str:
        if self._company_name_cache is None:
            self._company_name_cache = str(
                self.repository.snapshot(self.analysis_id)["company_name"]
            )
        return self._company_name_cache

    def _agent_status(self, agent: str) -> str:
        for entry in self.repository.agents(self.analysis_id):
            if entry["agent"] == agent:
                return str(entry["status"])
        return "pending"

    def _facts_ready(self) -> bool:
        return self._site_facts_saved or self._agent_status("site") == "done"

    async def _lock_for(self, key: tuple) -> asyncio.Lock:
        """Return the lock of one payable unit of work, creating it once."""
        async with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = self._locks[key] = asyncio.Lock()
            return lock

    def _stored_model_pairs(self) -> set[tuple[str, int]]:
        """The answered pairs, read from the database once per toolbox."""
        if self._pairs_cache is None:
            self._pairs_cache = {
                (str(item["connection_id"]), int(item["query_index"]))
                for item in self._all_rows("model")
            }
        return self._pairs_cache

    def _remember_pair(self, connection_id: str, query_index: int) -> None:
        if self._pairs_cache is not None:
            self._pairs_cache.add((connection_id, query_index))

    def _all_rows(self, kind: str) -> list[dict]:
        """Read every saved row of one kind through the paged repository read."""
        items: list[dict] = []
        cursor: str | None = None
        while True:
            page = self.repository.rows_page(self.analysis_id, kind, cursor, ROWS_PAGE_SIZE)
            items.extend(page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                return items


# -- module helpers ----------------------------------------------------------


def _outcome(
    outcome: str,
    *,
    status: str | None = None,
    documents: Sequence[tuple[int, str, str]] = (),
    reused: bool = False,
    error: str | None = None,
) -> dict:
    """One internal check outcome: what happened and what the query now says."""
    return {
        "outcome": outcome,
        "status": status or outcome,
        "documents": tuple(documents),
        "reused": reused,
        "error": error,
    }


def _count_outcomes(results: Sequence[Mapping[str, object]]) -> dict[str, int]:
    counts = {
        OUTCOME_FOUND: 0, OUTCOME_ABSENT: 0, OUTCOME_ERROR: 0,
        OUTCOME_REUSED: 0, OUTCOME_SKIPPED: 0, OUTCOME_BUDGET: 0,
    }
    for result in results:
        outcome = str(result["outcome"])
        if outcome in counts:
            counts[outcome] += 1
    return counts


def _summarize_rows(items: Sequence[Mapping[str, object]]) -> dict[str, int]:
    counts = {"found": 0, "absent": 0, "error": 0, "pending": 0}
    for item in items:
        status = str(item["status"])
        if status in CHECKED_STATUSES:
            counts[status] += 1
        elif status in ERROR_ROW_STATUSES:
            counts["error"] += 1
        else:
            counts["pending"] += 1
    return counts


def _document_json(document: tuple[int, str, str]) -> dict[str, object]:
    position, url, title = document
    return {"position": position, "host": result_url_host(url) or "", "title": title}


def _trace_arguments(arguments: object) -> dict[str, object]:
    """Keep a short, safe summary of the arguments of one call."""
    if not isinstance(arguments, Mapping):
        return {}
    return {str(key): _safe_value(value) for key, value in list(arguments.items())[:20]}


def _safe_value(value: object, depth: int = 0) -> object:
    if isinstance(value, str):
        return value[:TRACE_ARGUMENT_CHARS]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if depth >= 2:
        return str(value)[:TRACE_ARGUMENT_CHARS]
    if isinstance(value, Mapping):
        return {str(key): _safe_value(item, depth + 1) for key, item in list(value.items())[:10]}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, depth + 1) for item in value[:TRACE_LIST_ITEMS]]
    return str(value)[:TRACE_ARGUMENT_CHARS]


def _summarize(result: Mapping[str, object]) -> str:
    try:
        text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        text = "{}"
    return text[:TRACE_RESULT_CHARS]


def _url_host(url: str) -> str | None:
    try:
        return canonical_host(url)
    except ValidationError:
        return None


def _url_key(url: str) -> tuple[str, str]:
    parsed = urlsplit(url if "://" in url else f"http://{url}")
    return (parsed.hostname or "").lower().removeprefix("www."), parsed.path.rstrip("/")


def _match_page(pages: Sequence[FetchedPage], url: str) -> FetchedPage | None:
    """Find the crawled page a tool asked for; a page never read is not a page."""
    target = _url_key(url)
    for page in pages:
        if _url_key(page.url) == target:
            return page
    return None


def _bare_host(value: str) -> str:
    text = value.strip()
    if "://" in text:
        return (urlsplit(text).hostname or "").lower().removeprefix("www.")
    return text.rstrip(".").lower().removeprefix("www.")


__all__ = ["SeoToolbox"]
