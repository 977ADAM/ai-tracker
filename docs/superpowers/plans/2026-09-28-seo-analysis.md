# SEO Analysis with a Supervisor Agent — Implementation Plan (Revision 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed six-stage SEO pipeline with a supervisor-led multi-agent runtime: five specialists with server-owned tools, native tool calling through LangGraph, hard budgets, a persisted agent trace, and a report whose numbers stay server-computed while the report agent adds conclusions and recommendations.

**Architecture:** A LangGraph `StateGraph` holds a supervisor node and five specialist subgraphs created with `create_agent`; specialists reach the world only through server tools (`fetch_site`, `yandex_search`, `search_many`, `ask_models`, `save_*`, `read_*`) that enforce budgets, idempotency, security rules, and trace persistence. Graph state is checkpointed into `seo-agents.sqlite3`; results live in the existing `runs.sqlite3` at `user_version = 4`.

**Tech Stack:** Python 3.13+, FastAPI, Pydantic, httpx, `langchain-core`, `langchain-openai`, `langgraph`, `langgraph-checkpoint-sqlite`, SQLite (stdlib, WAL), keyring, SvelteKit 2, Svelte 5, TypeScript, Tailwind v4, pytest, Vitest, Playwright (`qa/`).

**Spec:** `docs/superpowers/specs/2026-09-28-seo-analysis-design.md` (revision 4, multi-agent).

**Base:** revision 1 of this plan is already implemented through commit `ec8a789` (settings, fetcher, domain rules at the 20-query limit, persistence at `user_version = 3`, fixed-pipeline orchestrator, API, form, progress, report, history, browser checks). This revision keeps the fetcher, host rules, matching, metrics, storage conventions, and API shell, and replaces the orchestration, the query limit, and the UI surfaces that expose stages.

**Working tree note:** commit the spec revision before Task 1.

## Global Constraints

- Agents decide *what* to do; the server decides *what is allowed*. Every external action goes through a tool implementation that checks budgets, dependencies, host rules, and idempotency regardless of what the model asks for.
- Native tool calling only. No text-protocol fallback. A model without tool support fails the settings test and is refused at run creation with «Модель не поддерживает вызов инструментов» before any paid call.
- Budgets per run: ≤ 20 fetched pages, ≤ 43 Yandex searches in total (3 key queries + 40 generated), ≤ 40 × M model answers, ≤ 15 supervisor handoffs, ≤ 20 model turns per specialist, ≤ 120 tool calls, ≤ 120 s per LLM call. Exhaustion ends the run with a stored «остановлен по лимиту» flag; it must never loop.
- Idempotency: a repeated `yandex_search` for the same normalized query, and a repeated `ask_models` for an already-checked pair, return the stored result and never create a new paid call.
- Metrics stay server-computed from stored rows. The report agent receives aggregates only and writes text; its text can never change a number and is labelled as model output.
- Fatal without further paid calls: unusable site URL, crawl failure, site agent failure, fewer than five valid queries after the agent's own retries. Non-fatal: no candidates, a failed search row, a failed connection, a failed report agent.
- Fetcher rules are unchanged: HTTPS start, same host and subdomains only, public addresses only after every redirect, connection pinned to the verified address, robots.txt respected, no JavaScript, no form submission.
- Secrets, upstream bodies, and Yandex operation IDs never reach API responses, the trace, history, or logs. Trace entries store safe arguments and short results only.
- Old behaviour is frozen: `/api/check`, `/api/search`, `/api/runs`, their limits, matching, and storage stay untouched; existing tests stay green.
- The form stays five fields with a fixed generated-query cap of 40; the estimate shown before the run is `3 + 40` searches and `40 × M` model answers, and the true agent-step count is declared unbounded in money.
- Commands: `cd backend && uv run pytest -q && uv run ruff check app tests`; `cd frontend && npm run check && npx vitest run && npm run build`; browser checks run from `qa/` against locally started services with `AI_TRACKER_CONFIG_DIR` pointed at a scratch directory.

## Review Focus

- Budget enforcement is proven by tests where a hostile or looping model asks for more pages, searches, answers, tool calls, and handoffs than allowed: the tool refuses, the trace records the refusal, and the run still terminates — test in Tasks 2 and 4.
- Dependency order is enforced server-side: `save_queries` before site facts, and `ask_models` before queries, must be rejected as tool results rather than crashing the graph — test in Task 2.
- Idempotency: a second `yandex_search` for the same normalized query and a second `ask_models` for a stored pair produce zero new gateway submissions and zero provider calls — test in Tasks 2 and 4.
- Prompt injection through page text cannot change tools, host, or budgets — test in Task 2.
- Trace completeness and redaction: every tool call and model turn appears once with a safe argument summary and no secrets or operation IDs — test in Tasks 3 and 6.
- Resume: after a simulated restart the graph continues from the checkpoint, stored tool results are reused, already-submitted Yandex operations are polled and not resubmitted — test in Task 4.
- Migration: a `user_version = 3` database with SEO rows keeps them readable and gains the agent tables at version 4 — test in Task 3.
- Metrics remain server-computed even when the report agent returns nonsense or fails — test in Tasks 5 and 6.

---

### Task 1: Tool-calling model client and tool-support check

**Files:**
- Modify: `backend/pyproject.toml` (add `langchain-core`, `langchain-openai`, `langgraph`, `langgraph-checkpoint-sqlite`)
- Modify: `backend/app/domain/seo_llm.py`
- Modify: `backend/app/integrations/seo_llm.py`
- Modify: `backend/app/service/seo_settings.py`
- Modify: `backend/app/api/schemas/seo_settings.py` and `backend/app/api/routers/seo_settings.py` only if the test response shape needs the new field
- Test: `backend/tests/test_domain_seo_llm.py`, `backend/tests/test_integrations_seo_llm.py`, `backend/tests/test_service_seo_settings.py`, `backend/tests/test_api_seo_settings.py`

**Interfaces:**
- Produces `ToolCall(id: str, name: str, arguments: dict[str, object])` and `AgentTurn(text: str, tool_calls: tuple[ToolCall, ...])` in `domain/seo_llm.py`, plus the `AgentModel` protocol `async def step(messages: Sequence[AgentMessage], tools: Sequence[ToolSchema]) -> AgentTurn`.
- Produces `LangChainSeoLlmClient(settings, *, timeout=120)` in `integrations/seo_llm.py` wrapping `ChatOpenAI(base_url, api_key, model, temperature=0)`; `step()` binds the given tool schemas, invokes the chat model, and maps returned tool calls into `ToolCall` values. Transport, auth, rate-limit, and malformed-payload failures become fixed safe Russian `ProviderError` messages.
- Keeps `SeoLlmClient.complete(system, user)` for the settings test path.
- `SeoSettingsService.test()` performs two probes: a plain chat completion and a tool probe with one trivial schema. Success shape becomes `{"ok": true, "model": ..., "tools": true}`; a model that answers without a tool call returns `{"ok": false, "error": "Модель не поддерживает вызов инструментов"}`; each probe failure keeps the existing safe error text.

- [ ] **Step 1: Add the dependencies** and confirm `cd backend && uv run python -c "import langchain_openai, langgraph"` succeeds; record resolved versions.
- [ ] **Step 2: Write failing client tests** with a fake chat model for tool-call mapping (single call, several calls, empty text with a call, plain text without calls, malformed arguments, provider errors) and for the tool schema passed through unchanged.
- [ ] **Step 3: Implement `ToolCall`/`AgentTurn`/`AgentModel` and `LangChainSeoLlmClient`**; keep `SeoLlmClient` and all current tests green.
- [ ] **Step 4: Write failing settings-service tests** for the two-probe result, the tool-unsupported case, and secret-free responses.
- [ ] **Step 5: Implement the two-probe test path** and expose `tools` in the public test response; update the API schema/route if needed.
- [ ] **Step 6: Run `cd backend && uv run pytest tests/test_domain_seo_llm.py tests/test_integrations_seo_llm.py tests/test_service_seo_settings.py tests/test_api_seo_settings.py -q && uv run pytest -q && uv run ruff check app tests`.**
- [ ] **Step 7: Commit** the client, settings probe, and tests.

### Task 2: Server tool layer with budgets, idempotency, and trace

**Files:**
- Create: `backend/app/domain/seo_tools.py`
- Create: `backend/app/service/seo_tools.py`
- Modify: `backend/app/domain/seo.py` (raise the generated-query limit to 40 and expose the budget constants)
- Test: `backend/tests/test_domain_seo_tools.py`
- Test: `backend/tests/test_service_seo_tools.py`
- Modify: `backend/tests/test_domain_seo.py` for the new limit

**Interfaces:**
- Produces budget constants: `GENERATED_QUERY_LIMIT = 40`, `MAX_SEARCH_REQUESTS = 43`, `MAX_FETCH_PAGES = 20`, `MAX_SUPERVISOR_HANDOFFS = 15`, `MAX_SPECIALIST_TURNS = 20`, `MAX_TOOL_CALLS = 120`, `LLM_CALL_TIMEOUT = 120.0`, `MIN_GENERATED_QUERIES = 5`.
- Produces `TOOL_SCHEMAS: Mapping[str, ToolSchema]` and the per-agent tool subsets (`SITE_TOOLS`, `COMPETITOR_TOOLS`, `QUERY_TOOLS`, `CHECK_TOOLS`, `REPORT_TOOLS`, `SUPERVISOR_TOOLS`).
- Produces `SeoBudget` (immutable usage counters with `spend_*` methods that raise a safe `BudgetExceeded`) and `ToolRejected` (a safe refusal that is returned to the model as the tool result, never raised out of the graph).
- Produces `SeoToolbox(repository, fetcher, gateway, connections, provider_factory, submit_search, poll_search, *, analysis_id, input, connection_ids, budget, on_step)` with `async def call(name: str, arguments: Mapping[str, object]) -> str` returning a compact JSON result string and `def schemas_for(agent: str) -> tuple[ToolSchema, ...]`.
- Every tool call: validates arguments, checks the budget and data dependencies, performs the action, persists its result through the Task 3 repository methods, and appends one trace step. Unknown names and bad arguments produce `ToolRejected`, not an exception.
- Idempotency: `yandex_search` looks up the stored row for the normalized query (key queries by index, generated queries by text) and returns the stored outcome when present; `ask_models` skips pairs that already have a model row for the given query.

- [ ] **Step 1: Write failing schema/budget tests** for schema self-consistency, per-agent tool subsets, budget spend and exhaustion, and argument validation (missing, extra, wrong types, unknown tool).
- [ ] **Step 2: Implement `domain/seo_tools.py`** and raise `GENERATED_QUERY_LIMIT` to 40 with the budget constants; update the domain tests that pinned 20.
- [ ] **Step 3: Write failing toolbox tests** for `fetch_site`/`read_page` (host rules, page budget, robots refusal surfaced safely), `save_site_facts` (dependency: requires fetched pages), `yandex_search` (region 225, search budget, stored-row reuse, stored operation ID, error rows), `save_candidates` (requires at least one successful seed SERP or explicit none), `read_facts`, `save_queries` (requires facts; ≥ 5 valid; ≤ 40; validation errors surfaced as tool errors), `search_many`, `ask_models` (concurrency cap, per-pair idempotency, per-connection error isolation), `read_checks`, `read_metrics`, `save_report`, `handoff_to` (supervisor only, handoff budget), `finish_run`.
- [ ] **Step 4: Implement the base tool executor, trace writes, and budget accounting**; confirm the focused tests pass.
- [ ] **Step 5: Implement the search and model tools** with "submit once, store the operation ID, poll on later calls" semantics and the idempotent reuse paths.
- [ ] **Step 6: Write failing hostile-input tests**: page text asking to fetch another host, change the region, exceed the page or search budget, call an unknown tool, or pass extra arguments — every case is refused with a safe message and nothing external happens.
- [ ] **Step 7: Run `cd backend && uv run pytest tests/test_domain_seo_tools.py tests/test_service_seo_tools.py tests/test_domain_seo.py -q && uv run pytest -q && uv run ruff check app tests`.**
- [ ] **Step 8: Commit** the tool layer and tests.

### Task 3: Persistence for agents, trace, and conclusions (schema version 4)

**Files:**
- Modify: `backend/app/db/seo.py`
- Modify: `backend/app/db/runs.py` (accept version 4)
- Test: `backend/tests/test_db_seo.py`, `backend/tests/test_db_runs.py`

**Interfaces:**
- New tables: `seo_agents` (`analysis_id`, `agent`, `status`, `error`, `updated_at`), `seo_agent_steps` (`analysis_id`, `step_index`, `agent`, `kind` in `model|tool|handoff|system`, `name`, `arguments_json`, `result_summary`, `status`, `error`, `created_at`), `seo_conclusions` (`analysis_id`, `summary`, `recommendations`, `model`, `created_at`).
- New methods: `upsert_agent(analysis_id, agent, status, *, error=None)`, `agents(analysis_id)`, `append_step(analysis_id, agent, kind, name, *, arguments=None, result_summary=None, status="done", error=None) -> int`, `trace_page(analysis_id, cursor=None, limit=100)`, `save_conclusions(analysis_id, *, summary, recommendations, model)`, `conclusions(analysis_id)`, `budget_state(analysis_id) -> dict` (counts of pages, searches, model rows, steps, handoffs, tool calls).
- `initialize()` raises `PRAGMA user_version` to 4; a version-3 database gains the new tables and keeps every existing SEO row; version 5 or higher is refused with the existing safe `StorageError`.
- `snapshot(analysis_id)` gains `agents`, `budget`, `conclusions`, and keeps aggregates and readiness; model answers and operation IDs stay out.

- [ ] **Step 1: Write failing migration tests** for a populated version-3 database: rows survive, new tables appear, `user_version` becomes 4, `RunRepository` still opens the file, and a hypothetical version 5 is refused.
- [ ] **Step 2: Implement the schema bump and the version guard change**; confirm migration tests pass.
- [ ] **Step 3: Write failing tests for agent status upserts, ordered step appends with monotonic indexes, trace pagination with `next_cursor`, conclusions round-trip, and budget counters derived from stored rows.**
- [ ] **Step 4: Implement the new tables, methods, and snapshot extensions**; confirm the focused tests pass.
- [ ] **Step 5: Run `cd backend && uv run pytest tests/test_db_seo.py tests/test_db_runs.py -q && uv run pytest -q && uv run ruff check app tests`.**
- [ ] **Step 6: Commit** the schema revision and tests.

### Task 4: Supervisor runtime on LangGraph

**Files:**
- Create: `backend/app/service/seo_agents.py`
- Modify: `backend/app/service/seo.py` (runner delegates orchestration to the graph)
- Modify: `backend/app/api/deps.py` (checkpointer path, client factory, injectable overrides)
- Modify: `backend/app/main.py` if the startup hook needs the new resume entry point
- Test: `backend/tests/test_service_seo_agents.py`
- Modify: `backend/tests/test_service_seo.py`, `backend/tests/fakes.py`

**Interfaces:**
- Produces `SeoAgentRuntime(repository, toolbox_factory, model, *, checkpointer, max_supervisor_turns=15)` with `async def run(analysis_id: str, input: SeoInput) -> None` and `async def resume(analysis_id: str) -> None`.
- The graph: a supervisor node using `SUPERVISOR_TOOLS` (`handoff_to`, `finish_run`, `read_status`) and five specialist nodes built with `create_agent` over `SITE_TOOLS`, `COMPETITOR_TOOLS`, `QUERY_TOOLS`, `CHECK_TOOLS`, `REPORT_TOOLS`. Specialists return to the supervisor after their own loop ends; every handoff is budgeted and traced.
- Checkpointing: `SqliteSaver` over `seo-agents.sqlite3` in the config directory with owner-only permissions; thread id is the analysis id.
- Termination: `finish_run` completes the run through the repository; exhausted budgets complete it with `budget_exhausted = true`; a fatal condition (unusable site, crawl failure, site agent failure, fewer than five valid queries after the agent retried) marks the run `failed` with the stage error and the trace preserved.
- Cancel: a per-analysis `asyncio.Event` is checked before each node and tool call; cancellation stops the graph and marks the run `cancelled`.
- Resume: `resume(analysis_id)` continues from the checkpoint; stored tool results are reused, submitted Yandex operations are polled, model answers are not re-requested; without a checkpoint the run becomes `interrupted`.
- `SeoService` keeps `start`, `snapshot`, `list_page`, `rows_page`, `trace_page`, `cancel`, `delete`, `recover`; `recover()` defers resumable runs and `resume_pending()` starts them at application startup, as today.

- [ ] **Step 1: Write failing runtime tests** with a scripted agent model: supervisor hands control to the site agent, then competitors, then queries, then checks, then report, then `finish_run`; every handoff traced; the repository shows six agent statuses and a completed run.
- [ ] **Step 2: Implement the graph skeleton, supervisor node, specialist nodes, and checkpointing**; confirm the happy path passes.
- [ ] **Step 3: Write failing guardrail tests** with a model that loops, calls a specialist twice with no new data, exceeds handoffs, exceeds tool calls, calls a tool not in its subset, and returns garbage arguments: the runtime stops within every budget, records refusals in the trace, and still finishes the run.
- [ ] **Step 4: Implement budget checks at node boundaries, per-specialist tool subsets, and `finish_run` on exhaustion.**
- [ ] **Step 5: Write failing degradation tests** for crawl failure, site agent failure, no candidates, fewer than five queries, one failing connection, a failing search row, and a failing report agent; assert exactly the fatal/non-fatal matrix from the spec and zero paid calls after a fatal condition.
- [ ] **Step 6: Implement the fatal/non-fatal handling and the `budget_exhausted` flag**; confirm the degradation tests pass.
- [ ] **Step 7: Write failing lifecycle tests** for cancel mid-run, storage failure isolation, restore from checkpoint with stored results reused, polled (not resubmitted) Yandex operations, interrupted runs without a checkpoint, and configuration refusals (disabled Yandex, missing LLM, unsupported tools).
- [ ] **Step 8: Implement cancel, storage isolation, resume, and configuration refusals**; rewire `SeoService` and `deps.py`, and keep `main.py` startup resume working.
- [ ] **Step 9: Run `cd backend && uv run pytest -q && uv run ruff check app tests`** and confirm the whole backend suite is green, including the rewritten fixed-pipeline tests.
- [ ] **Step 10: Commit** the runtime, runner rewiring, and tests.

### Task 5: Domain and report adjustments for the agentic run

**Files:**
- Modify: `backend/app/domain/seo.py` (limits already raised in Task 2; add agent names and statuses)
- Modify: `backend/app/domain/seo_report.py`
- Modify: `backend/app/domain/seo_prompts.py`
- Test: `backend/tests/test_domain_seo.py`, `backend/tests/test_domain_seo_report.py`, `backend/tests/test_domain_seo_prompts.py`

**Interfaces:**
- Produces `AGENTS = ("supervisor", "site", "competitors", "queries", "checks", "report")`, `AGENT_LABELS` (Russian labels for the UI), and `AgentStatus = Literal["pending", "running", "waiting", "done", "error", "skipped"]`.
- Produces report payload helpers so `build_report` output can be paired with the agent conclusions without touching the metric shapes: `report_payload(metrics, *, conclusions: Mapping[str, object] | None) -> dict`.
- Produces agent prompt builders in `seo_prompts.py`: `supervisor_prompt(input, budget_state, status)`, `site_agent_prompt(input)`, `competitor_agent_prompt(input)`, `query_agent_prompt(input)`, `check_agent_prompt(input)`, `report_agent_prompt(metrics)`. Page text and query text stay in user messages inside explicit delimiters and are marked as data; budgets and allowed tool names are stated in the system prompt but never trusted.
- Metrics rules, matching rules, and category/service splits stay exactly as they are.

- [ ] **Step 1: Write failing tests** for agent constants and labels, `AgentStatus` values, prompt contents (spheres, services, seeds, candidates, metrics, budget summary; page text only in the user message), and `report_payload` combining metrics with optional conclusions.
- [ ] **Step 2: Implement the constants, prompt builders, and payload helper**; keep every existing report test green.
- [ ] **Step 3: Write failing tests** proving that a missing, empty, or nonsense conclusions block leaves every metric unchanged.
- [ ] **Step 4: Run `cd backend && uv run pytest tests/test_domain_seo.py tests/test_domain_seo_report.py tests/test_domain_seo_prompts.py -q && uv run pytest -q && uv run ruff check app tests`.**
- [ ] **Step 5: Commit** the domain and report adjustments.

### Task 6: API surface for agents, budget, trace, and conclusions

**Files:**
- Modify: `backend/app/api/schemas/seo.py`
- Modify: `backend/app/api/routers/seo.py`
- Modify: `backend/app/service/seo.py` (expose `trace_page`)
- Test: `backend/tests/test_api_seo.py`, `backend/tests/test_api_schemas.py`

**Interfaces:**
- `GET /api/seo/analyses/{id}` keeps its shape and gains `agents` (name, status, error), `budget` (used versus cap per resource), and `conclusions` (`summary`, `recommendations`, `model` or `null`).
- New `GET /api/seo/analyses/{id}/trace?cursor=` returning `{items, next_cursor}` where an item is `{step_index, agent, kind, name, arguments, result_summary, status, error, created_at}`; invalid cursors → 400, unknown analysis → 404.
- No response contains the API key, upstream bodies, or Yandex operation IDs; `seo_agent_steps.arguments_json` is projected to a safe subset before leaving the API.

- [ ] **Step 1: Write failing API tests** for the extended snapshot fields, the trace endpoint (order, pagination, cursor validation, unknown id), absence of secrets and operation IDs, and the pinned OpenAPI path/schema set.
- [ ] **Step 2: Implement the schemas, the trace route, and the service method**; confirm the focused tests pass.
- [ ] **Step 3: Run `cd backend && uv run pytest -q && uv run ruff check app tests`.**
- [ ] **Step 4: Commit** the API changes and tests.

### Task 7: Frontend for agents, trace, budget, and conclusions

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/server/python-api.ts`, `frontend/src/lib/server/python-api.test.ts`
- Modify: `frontend/src/lib/seo-form.ts`, `frontend/src/lib/seo-form.test.ts` (limits 40 and the `3 + 40` / `40 × M` estimate)
- Create: `frontend/src/lib/components/SeoAgentPanel.svelte` and `SeoAgentPanel.test.ts` (six agents with statuses, used-versus-cap budgets)
- Create: `frontend/src/lib/components/SeoTraceFeed.svelte` and `SeoTraceFeed.test.ts` (paginated steps, safe arguments, errors)
- Modify: `frontend/src/lib/components/SeoRunProgress.svelte`, `SeoForm.svelte`, `SeoReport.svelte` and their tests
- Modify: `frontend/src/routes/+page.svelte`, `frontend/src/lib/components/SearchRunPage.test.ts`
- Modify: `frontend/src/lib/components/SeoSettingsPanel.svelte` and its test (show the tool-support result)
- Create: `frontend/src/routes/api/seo/analyses/[id]/trace/+server.ts`

**Interfaces:**
- Types: `SeoAgent`, `SeoAgentStatus`, `SeoBudgetView`, `SeoTraceStep`, `SeoTracePage`, `SeoConclusions`; snapshot gains `agents`, `budget`, `conclusions`; `SeoRowsKind` gains no new member, `trace` is its own path builder `seoAnalysisTracePath(id, cursor)`.
- `SeoForm` shows the raised estimate (`3 + 40` searches, `40 × M` answers) and states that the number of agent steps depends on the model and is not priced.
- `SeoAgentPanel` replaces the fixed six-stage list in the run screen: six agents with statuses, error text, and budget usage.
- `SeoTraceFeed` renders steps newest-last in order with agent, tool name, short arguments, short result, and status, loading more by cursor.
- `SeoReport` gains a conclusions and recommendations block labelled as model text and shown separately from the numbers; metrics rendering and `—` rules stay unchanged.
- `SeoSettingsPanel` shows whether the configured model supports tool calling from the settings test.

- [ ] **Step 1: Write failing `seo-form` tests** for the 40-query cap and the new estimate, then implement them.
- [ ] **Step 2: Write failing BFF tests** for the trace path (allowlist, projection, cursor validation, no secrets) and the extended snapshot projection; implement types, path builder, and projectors.
- [ ] **Step 3: Add the trace route handler** and confirm `npm run check` passes.
- [ ] **Step 4: Write failing agent panel and trace feed tests** for statuses, budget rendering, pagination, error steps, and safe argument display; implement both components.
- [ ] **Step 5: Update the run screen, report, form, and settings panel**; rewrite the page test for the agent screen and keep every other frontend test green.
- [ ] **Step 6: Run `cd frontend && npm run check && npx vitest run && npm run build`.**
- [ ] **Step 7: Commit** the frontend changes and tests.

### Task 8: Browser checks, documentation, and end-to-end verification

**Files:**
- Modify: `qa/pages/seo.py`, `qa/tests/test_seo.py`, `qa/tests/test_search.py`, `qa/tests/test_run_history.py`
- Modify: `README.md`, `backend/README.md`, `qa/README.md`
- Modify: `.superpowers/sdd/2026-09-28-seo-analysis/progress.md` (ledger)

**Interfaces:**
- The browser scenario keeps its no-paid-call rule: SEO endpoints are answered with `page.route`, and a completed analysis with agents, trace, budget, and conclusions is seeded directly into `AI_TRACKER_CONFIG_DIR/runs.sqlite3` for the report and history checks.
- New checks: the form shows the `3 + 40` / `40 × M` estimate; the run screen lists six agents and a trace feed; the report shows the conclusions block labelled as model text; the settings tab shows the tool-support result.
- Documentation states the multi-agent flow, the six agents, the budgets, the tool-calling requirement, `user_version = 4`, `seo-agents.sqlite3`, the environment variables, cancellation, and restart behaviour.

- [ ] **Step 1: Extend the QA page object and scenario** for the agent screen, budget, trace feed, conclusions block, and the settings tool-support result; keep the seeding helper aligned with the version-4 schema.
- [ ] **Step 2: Update the documentation** for the new flow, budgets, dependencies, and configuration.
- [ ] **Step 3: Run the backend suite**: `cd backend && uv run pytest -q && uv run ruff check app tests`.
- [ ] **Step 4: Run the frontend suite**: `cd frontend && npm run check && npx vitest run && npm run build`.
- [ ] **Step 5: Run the browser suite for real**: start the backend with a scratch `AI_TRACKER_CONFIG_DIR` and the dev frontend, then `cd qa && QA_HEADLESS=1 AI_TRACKER_CONFIG_DIR=<scratch> uv run pytest`; fix whatever the live run exposes and stop both services afterwards.
- [ ] **Step 6: Update the SDD ledger** with commits, verification results, and deviations.
- [ ] **Step 7: Commit** the browser checks, documentation, and ledger.
