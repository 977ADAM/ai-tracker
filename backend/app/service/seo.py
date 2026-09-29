"""SEO runs on the agent runtime: configuration refusals and run lifecycle.

The fixed six-stage automaton is gone. One run is the LangGraph supervisor of
`SeoAgentRuntime` over five specialists, and this service owns only what the
runtime must not: the request validation, the configuration refusals that must
happen before an analysis row exists or a paid call starts, the durable creation
of the analysis, the background task that runs the graph, and the restart policy
of the runs a previous process left behind.

Nothing here knows the stages, the prompts, or the tools. `snapshot`,
`list_page`, `rows_page`, and `trace_page` are repository reads, `cancel` is the
runtime's cancellation plus a stored snapshot, and a background task never
surfaces its exception to the event loop. A cancelled or failed run touches only
its own analysis: the old global stop flag of `RunService` is never involved.

Start refusals, in order, all before `create_analysis` and before any paid run
call: a malformed request, a disabled Yandex search, a missing Yandex gateway, a
missing service LLM, an unknown or unconfigured model connection, and a service
model that answers the trivial tool probe without a tool call. Only the last
refusal touches the network, which is why it runs after every local check.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from typing import Any

from app.core.errors import AppError, ConfigurationError, RunConflict, StorageError
from app.db.seo import ANALYSIS_TERMINAL, SeoRepository
from app.domain.seo import GENERATED_QUERY_LIMIT, normalize_seo_request
from app.domain.seo_llm import (
    LLM_NOT_CONFIGURED,
    AgentMessage,
    AgentModel,
    close_agent_model,
)
from app.domain.seo_tools import MAX_SEARCH_REQUESTS
from app.service.checks import MISSING_KEY_MESSAGE
from app.service.connections import ConnectionService
from app.service.search import DISABLED_ENGINE, MISSING_CREDENTIALS
from app.service.search_settings import SearchSettingsService
from app.service.seo_agents import SeoAgentRuntime
from app.service.seo_settings import (
    TOOL_TEST_SCHEMA,
    TOOL_TEST_SYSTEM,
    TOOL_TEST_USER,
    TOOLS_UNSUPPORTED,
    SeoSettingsService,
)

LOGGER = logging.getLogger(__name__)

# A restart may resume only a run whose graph state was checkpointed; the probe
# reads the checkpoint file synchronously, because `recover` runs during the
# container build, before any event loop exists.
CheckpointProbe = Callable[[str], bool]


class SeoService:
    """Validate, create, and own the background tasks of the SEO agent runs."""

    def __init__(
        self,
        repository: SeoRepository,
        runtime: SeoAgentRuntime,
        yandex_settings: SearchSettingsService,
        llm_settings: SeoSettingsService,
        connections: ConnectionService,
        *,
        checkpoint_probe: CheckpointProbe | None = None,
    ) -> None:
        self.repository = repository
        self.runtime = runtime
        self.yandex_settings = yandex_settings
        self.llm_settings = llm_settings
        self.connections = connections
        self.checkpoint_probe = checkpoint_probe
        # One background task per live analysis; the done callback removes it, so
        # a finished run leaves no state behind.
        self.tasks: dict[str, asyncio.Task] = {}
        self._deferred_resume: list[str] = []

    # -- public API ------------------------------------------------------

    async def start(self, payload: object) -> dict[str, object]:
        """Refuse an unusable configuration and start the run in the background.

        The answer is immediate: `create_analysis` has already written the
        durable row, and the graph runs as its own task, so no HTTP request ever
        waits for a crawl, a search, or a model call.
        """
        request = normalize_seo_request(payload)
        if not self.yandex_settings.enabled():
            raise ConfigurationError(DISABLED_ENGINE)
        if self.yandex_settings.gateway_snapshot() is None:
            raise ConfigurationError(MISSING_CREDENTIALS)
        model = self.llm_settings.build_agent_model()
        if model is None:
            raise ConfigurationError(LLM_NOT_CONFIGURED)
        self._require_connections(request.connection_ids)
        await self._require_tool_support(model)

        connections = len(request.connection_ids)
        estimate = {
            "search_upper": MAX_SEARCH_REQUESTS,
            "model_upper": GENERATED_QUERY_LIMIT * connections,
            "generated_limit": GENERATED_QUERY_LIMIT,
            "connections": connections,
        }
        analysis_id = self.repository.create_analysis(request, estimate)
        self._spawn(analysis_id, self.runtime.run(analysis_id, request))
        return {"id": analysis_id, "status": "running", "estimate": estimate}

    def snapshot(self, analysis_id: str) -> dict:
        """Return one saved analysis, including its agents, budget, and trace count."""
        return self.repository.snapshot(analysis_id)

    def list_page(self, cursor: str | None = None) -> dict:
        """Return one light history page, newest first."""
        return self.repository.list_page(cursor)

    def rows_page(self, analysis_id: str, kind: str, cursor: str | None = None) -> dict:
        """Return one page of saved model answers or Yandex rows."""
        return self.repository.rows_page(analysis_id, kind, cursor)

    def trace_page(self, analysis_id: str, cursor: str | None = None) -> dict:
        """Return one page of the agent trace, oldest step first."""
        return self.repository.trace_page(analysis_id, cursor)

    def cancel(self, analysis_id: str) -> dict:
        """Stop a running analysis before its next step and return the stored state.

        The terminal check runs here, before the runtime sets its stop event: the
        runtime treats a repeated cancel as a safe no-op, while the API contract
        keeps answering `409` for an analysis that is already finished.
        """
        snapshot = self.repository.snapshot(analysis_id)
        if snapshot["status"] != "running":
            raise RunConflict(ANALYSIS_TERMINAL)
        self.runtime.cancel(analysis_id)
        return self.repository.snapshot(analysis_id)

    def delete(self, analysis_id: str) -> None:
        """Delete a terminal analysis and drop the run state kept for it."""
        self.repository.delete(analysis_id)
        self.tasks.pop(analysis_id, None)
        if analysis_id in self._deferred_resume:
            self._deferred_resume.remove(analysis_id)

    def recover(self) -> None:
        """Decide the fate of every analysis the previous process left running.

        A run with a stored graph checkpoint keeps running: it is deferred until
        a loop exists, because `resume` needs one and this method is called while
        the container is built. A run without a checkpoint has nothing to
        continue: its unsubmitted rows become interrupted, and the analysis
        itself ends as interrupted while its finished rows stay readable.
        """
        for analysis_id in self.repository.running_analysis_ids():
            if self._has_checkpoint(analysis_id):
                if analysis_id not in self._deferred_resume:
                    self._deferred_resume.append(analysis_id)
                continue
            self.repository.interrupt_unsubmitted_rows(analysis_id)
            self.repository.mark_interrupted(analysis_id)

    def resume_pending(self) -> None:
        """Start every deferred resume as a background task.

        Called by the application startup hook, where a loop is running. Without
        a configured service LLM nothing can be resumed, so the runs stay
        deferred for a later start instead of being failed here.
        """
        if not self._deferred_resume:
            return
        if self.llm_settings.build_agent_model() is None:
            LOGGER.info("SEO agent resumes wait for a configured service LLM")
            return
        deferred, self._deferred_resume = self._deferred_resume, []
        for analysis_id in deferred:
            self._spawn(analysis_id, self.runtime.resume(analysis_id))

    async def close(self) -> None:
        """Cancel and await every live run task; safe to call more than once."""
        pending = list(self.tasks.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self.tasks.clear()
        self._deferred_resume.clear()

    # -- configuration refusals ------------------------------------------

    def _require_connections(self, connection_ids: Sequence[str]) -> None:
        """Refuse an unknown connection or one without an API key.

        Locally checked before the tool probe, so a request that can never run
        costs nothing.
        """
        for connection_id in connection_ids:
            try:
                self.connections.require(connection_id)
            except StorageError as exc:
                raise ConfigurationError(str(exc)) from exc
            if not self.connections.is_configured(connection_id):
                raise ConfigurationError(MISSING_KEY_MESSAGE)

    async def _require_tool_support(self, model: AgentModel) -> None:
        """Refuse a service model that cannot call tools, before any paid run.

        One probe with a trivial schema: a model that answers without a tool call
        has no native tool calling, and the graph would never hand off. The probe
        adapter is closed here: the runtime builds its own adapter for each run.
        """
        try:
            turn = await model.step(
                (
                    AgentMessage(role="system", content=TOOL_TEST_SYSTEM),
                    AgentMessage(role="user", content=TOOL_TEST_USER),
                ),
                (TOOL_TEST_SCHEMA,),
            )
        except AppError as exc:
            # Adapter messages are fixed and safe by contract.
            raise ConfigurationError(str(exc)) from exc
        finally:
            await close_agent_model(model)
        if not turn.tool_calls:
            raise ConfigurationError(TOOLS_UNSUPPORTED)

    # -- run state -------------------------------------------------------

    def _has_checkpoint(self, analysis_id: str) -> bool:
        if self.checkpoint_probe is None:
            return False
        try:
            return bool(self.checkpoint_probe(analysis_id))
        except Exception:  # noqa: BLE001 - an unreadable checkpoint is no checkpoint
            LOGGER.error("SEO checkpoint of %s could not be read", analysis_id)
            return False

    def _spawn(self, analysis_id: str, coroutine: Any) -> None:
        """Run one coroutine as a task whose exception never escapes the callback."""
        task = asyncio.create_task(coroutine)
        self.tasks[analysis_id] = task
        task.add_done_callback(lambda done, ident=analysis_id: self._task_done(ident, done))

    def _task_done(self, analysis_id: str, task: asyncio.Task) -> None:
        if self.tasks.get(analysis_id) is task:
            self.tasks.pop(analysis_id, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            LOGGER.error("SEO analysis %s stopped: %s", analysis_id, type(error).__name__)


__all__ = ["LLM_NOT_CONFIGURED", "SeoService"]
