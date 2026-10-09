# Projects and Repeatable Measurements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Execution method is selected by the user after reviewing this plan.

**Goal:** Replace the main SEO chat with projects configured through forms and manually repeated measurements, including sentiment, sources and comparable history.

**Architecture:** Add independent project and measurement domain rules, repositories and services to the existing FastAPI container. A sequential worker measures every saved query against every selected model and classifies brand mentions through the service LLM. SvelteKit BFF exposes safe projections; project cards and detail pages replace the active chat UI without deleting legacy data or API resources.

**Tech Stack:** Existing Python ≥ 3.13 / FastAPI / SQLite / httpx; SvelteKit 2 / Svelte 5 / TypeScript / Tailwind 4; pytest, Vitest, Playwright. No new product dependencies required.

**Spec:** `docs/superpowers/specs/2026-10-09-projects-and-measurements-design.md`

## User refinements during execution

- Work directly on main, no worktree. Minimal regression tests first, then code.
- Create project with only brand and site; default name=brand. Queries/models are
  configured inside project. Empty collections may be saved; start requires both.
- Documentation explicitly calls out multi-company support through separate projects.

## Global Constraints

- One project: one brand and site, competitors, saved queries, selected models and measurement history; no chat or scheduling in the new interface.
- Brand/name: 1..100 characters; competitors: 0..10; queries: 0..20 unique strings, ≤400 characters and ≤40 words; models: 0..5 unique connections. Start requires ≥1 query and model.
- Competitor record: brand + public site URL. Optional query category: one of the four existing intents. Optional Yandex defaults to disabled.
- Every query × model pair runs once: ≤100 checked-model calls and ≤100 sentiment calls; optional Yandex: ≤20 searches. Existing SEO resource limits stay unchanged.
- One active measurement per project; durable non-secret snapshots; sequential execution; ≤120 seconds per external call; no automatically repeated paid work after restart.
- Sentiment is positive/neutral/negative, or unknown on classification failure. Domain-only mentions do not count as brand mentions.
- Visibility uses successful answers as denominator; empty denominator is null; incomplete coverage disables comparison, not saved results.
- New additive SQLite schema version 7; existing data and old API contracts retained; keys remain in existing secret storage.
- Browser uses BFF only; same-origin mutation guards, allowlisted public projections, sanitized Markdown and existing endpoint restrictions apply.

## Review Focus

- Deleted global connection: historical snapshots remain readable; next start refuses before paid calls (Tasks 2, 4).
- Concurrent start/delete/cancel and a late external response: no second active run, orphan rows or revival of terminal runs (Tasks 2, 4).
- Reordered queries/models versus materially edited settings: order alone preserves series; model, classifier, query or Yandex changes break it (Tasks 1, 3).
- Mixed sentiment, domain-only mentions and invalid evidence: no false neutral or positive counts; stored answers survive classifier failure (Tasks 1, 3, 4).
- Server-side page loading cannot be intercepted by browser routes: isolated QA backend and no mutations of real user configuration (Task 9).

## File boundaries and shared contracts

New backend modules follow the existing `domain`, `db`, `service`, `integrations`,
`api/schemas` and `api/routers` layout. New frontend project contracts live in
`lib/project-types.ts`; BFF project validation lives in `lib/server/projects-api.ts`
instead of extending the already large legacy parser with all new behavior.

Domain types are frozen dataclasses. `ProjectInput` contains name, brand, site_url,
tuple of `Competitor(brand, site_url)`, tuple of `ProjectQuery(text, category)`,
tuple of connection IDs and yandex_enabled. `MeasurementSnapshot` contains
project input, `SeoConnectionSnapshot` tuples, `ClassifierSnapshot(endpoint, model,
prompt_version)`, optional `YandexSnapshot(region, mode)` and metric_version.
No secret is a dataclass field.

`ModelAnswerRow` contains query_index, connection_id, status, optional SeoAnswer,
brand_mentioned, domain_mentioned, sentiment_status, optional SentimentResult and
safe error. Answer statuses: pending/sent/success/error/cancelled/interrupted.
Sentiment statuses: not_applicable/pending/sent/completed/unknown/cancelled/interrupted.
`SearchResultRow` contains query_index, status, optional internal operation ID,
optional tuple of SearchDocument and safe error; statuses include waiting.
Internal operation IDs are excluded from API schemas.

Public lists use `{items, cursor}`; model/search details use `{items, cursor, kind}`.
Measurement snapshot uses `{id, project_id, status, incomplete, snapshot,
created_at, finished_at, estimate, progress, aggregates, comparison}`.
Project summary includes `{id, name, brand, site_url, connections, updated_at,
latest_measurement, active_measurement}`. All aggregate calculations are server-side.

Repository project signatures: `create(input: ProjectInput) -> dict`,
`update(id: str, input: ProjectInput) -> dict`, `get(id: str) -> dict`,
`list_page(cursor: str | None = None, limit: int = 20) -> dict`,
`delete(id: str) -> None`. Public project/service CRUD methods keep those
signatures except create/update accept `payload: object` and validate first.
Measurement repository write signatures: `save_answer(id: str, row_key:
tuple[int, str], answer: SeoAnswer | None, error: str | None = None) -> bool`,
`save_sentiment(id: str, row_key: tuple[int, str], result: SentimentResult | None,
error: str | None = None) -> bool`, `save_search_operation(id: str, query_index:
int, operation_id: str) -> bool`, `save_search_result(id: str, query_index: int,
documents: tuple[SearchDocument, ...] | None, error: str | None = None) -> bool`.
The repository derives mention flags from the saved snapshot/answer through
domain rules; services do not send client-supplied mention counts.

### Task 1: Project validation, measurement rules and comparison identity

**Files:** Create `backend/app/domain/projects.py`, `backend/app/domain/measurements.py`, `backend/app/domain/sentiment.py`; tests `backend/tests/test_domain_projects.py`, `backend/tests/test_domain_measurements.py`, `backend/tests/test_domain_sentiment.py`.

**Interfaces:** Produce the shared dataclasses above; `normalize_project(payload: object) -> ProjectInput`, `comparison_key(snapshot: MeasurementSnapshot) -> str`, `parse_sentiment(payload: object, answer: str) -> SentimentResult`. SentimentResult is label + evidence. Classifier version starts at `sentiment-v1`; metric version at `project-metrics-v1`.

- [ ] Write tests: a valid 15-query/5-model project plans 75 pairs; reject 21 queries, 6 models, 11 competitors, unknown fields, duplicate normalized queries, private URLs and invalid categories. Accept zero competitors and absent categories.
- [ ] Add identity tests: reversing queries/models/competitors and changing project display name preserves comparison_key; changed query/category/brand/site/model/endpoint/answer mode/thinking flag/classifier model or enabled Yandex region/mode changes it. When Yandex is disabled, unrelated global search settings do not affect identity.
- [ ] Add sentiment parser tests: accept three labels with evidence contained in the answer; reject missing/unknown labels, non-string evidence and invented evidence. Mixed balanced assessment is specified as neutral in the prompt, not guessed by the parser.
- [ ] Run `cd backend && uv run pytest tests/test_domain_projects.py tests/test_domain_measurements.py tests/test_domain_sentiment.py` and confirm the new tests fail because their public functions are absent.
- [ ] Implement validation using existing host, matching and query-limit helpers. Compute comparison identity from a canonical sorted JSON representation hashed with SHA-256, excluding IDs/display names/order and all secrets; include each query's optional category.
- [ ] Re-run the command; expect passing tests. Commit `feat: define projects and repeatable measurement rules` with these six files.

### Task 2: Durable repositories and additive migration

**Files:** Create `backend/app/db/projects.py`, `backend/app/db/measurements.py`, `backend/app/db/project_storage.py`; modify `backend/app/db/runs.py`, `backend/app/db/seo.py`, `backend/app/db/chat.py`; tests `backend/tests/test_db_projects.py`, `backend/tests/test_db_measurements.py`.

**Interfaces:** `ProjectRepository(config_dir: Path)` provides initialize/create/update/get/list_page/delete. `MeasurementRepository(config_dir: Path)` provides initialize, `create(project_id, snapshot, estimate) -> str`, `get(id) -> dict`, `list_page(project_id, cursor=None, limit=20) -> dict`, `rows_page(id, kind, cursor=None, limit=50) -> dict`, `mark_sent(id, kind, row_key) -> bool`, `save_answer`, `save_sentiment`, `save_search_operation`, `save_search_result`, `finish(id, status)`, `cancel(id) -> dict`, `recover_unfinished()`, `delete(id)`. Writers return false when a terminal run rejects a late mutation. row_key is `(query_index, connection_id)` for model rows and query_index for search rows. Project storage owns shared transactions, cursor parsing and schema creation, not business orchestration.

- [ ] Write tests for schema-6 fixture migration to 7 with legacy rows intact; opening repositories in different orders never lowers user_version. Newer unsupported schema is rejected before writes. Confirm legacy APIs can still read after migration.
- [ ] Write CRUD/pagination tests with equal timestamps, invalid cursor and cascading delete. History remains after global connection removal; project updates retain prior snapshots. Active-project deletion is a conflict.
- [ ] Write transaction tests: create preallocates exactly Q×K rows and optional Q search rows; two competing creates produce one active measurement; cancellation followed by save/finish cannot revive it; no partial answer/source write; recovery marks active and pending/sent rows interrupted without network calls. Removing a measurement updates latest-result selection.
- [ ] Run `cd backend && uv run pytest tests/test_db_projects.py tests/test_db_measurements.py`; expect failures before implementing repositories.
- [ ] Implement SQLite WAL/busy_timeout/owner-only file behavior using existing repository conventions. Add tables `projects`, `project_measurements`, `project_model_rows`, `project_search_rows`; partial unique index on project_id where status='running'. Transactions re-check project existence and active status. Secret values are never serialized; sources reuse SeoAnswer serialization/validation.
- [ ] Raise all legacy maximum accepted schema versions to 7, including the literal guard in RunRepository. Persist non-secret search snapshots; operation IDs stay internal. Classifier states are independent from checked-model status.
- [ ] Run new repository tests plus `tests/test_db_runs.py tests/test_db_seo.py tests/test_db_chat.py tests/test_web_search_persistence.py`; expect pass. Commit `feat: persist projects and measurement snapshots`.

### Task 3: Report aggregation and sentiment adapter

**Files:** Create `backend/app/domain/measurement_report.py`, `backend/app/integrations/sentiment.py`; modify `backend/app/domain/seo_report.py` only to expose reusable pure helpers, and `backend/app/service/seo_settings.py` for non-secret classifier snapshot/client construction; tests `backend/tests/test_measurement_report.py`, `backend/tests/test_integrations_sentiment.py`, existing report/settings tests.

**Interfaces:** `build_measurement_report(snapshot, model_rows, search_rows) -> dict`, `compare_measurements(current: dict, previous: dict | None) -> dict`; `SentimentClassifier` protocol: `async classify(brand: str, answer: str) -> SentimentResult`. `LlmSentimentClassifier(client: SeoLlmClient)` implements it. `SeoSettingsService.classifier_snapshot() -> ClassifierSnapshot` and `build_classifier(snapshot: ClassifierSnapshot) -> SentimentClassifier` construct a client at captured endpoint/model using the existing key without persisting it.

- [ ] Write report fixtures: 75 planned pairs, 70 successful, 32 brand-mentioned; visibility is 32/70, coverage 70/75. Assert positive+neutral+negative+unknown=32, domain-only answer does not increase 32, zero successes gives null. Return per-model and per-query metrics and all row counters.
- [ ] Test citation denominators only include successful completed-search answers; reused brand-position and external-domain ordering match legacy functions. Competitors use explicit saved brand/site pairs. Optional Yandex computes first top-10 match per site/competitor; disabled search is not applicable.
- [ ] Test comparison: same identity and full coverage yields visibility difference in percentage points and count differences; different identity or incomplete coverage gives null deltas with reason. Unknown sentiment disables only sentiment deltas; first measurement has no predecessor.
- [ ] Test classifier request: one completion with separate instructions and JSON-encoded brand/answer data, no tools; validates JSON and evidence; safe errors on timeout/invalid payload, balanced-mixed rubric present. Snapshot uses captured model despite a settings edit. Provider context-limit refusal produces unknown; never silently truncate an answer into a different sentiment assessment.
- [ ] Run `cd backend && uv run pytest tests/test_measurement_report.py tests/test_integrations_sentiment.py`; confirm expected failures.
- [ ] Implement aggregates from successful persisted rows; extract public helpers for position/citations/source counts while retaining existing report behavior and vocabulary. LLM rubric follows the spec; no lexical sentiment fallback and no extra retry. Keep four-decimal share precision and one-decimal display rounding separate.
- [ ] Run new tests plus `tests/test_citation_metrics.py tests/test_domain_seo_report.py tests/test_service_seo_settings.py`; expect pass. Commit `feat: calculate project reports and classify sentiment`.

### Task 4: Project service and sequential measurement lifecycle

**Files:** Create `backend/app/service/projects.py`, `backend/app/service/measurements.py`, `backend/app/service/measurement_worker.py`; modify `backend/app/api/deps/container.py`, `backend/app/main.py`; tests `backend/tests/test_service_projects.py`, `backend/tests/test_service_measurements.py`, `backend/tests/test_measurement_worker.py`.

**Interfaces:** `ProjectService.create/update/get/list_page/delete` return public dictionaries. `MeasurementService.start(project_id: str) -> dict`, get/list_page/rows_page/cancel/delete, `recover_pending() -> None`, `async close() -> None`. `MeasurementWorker.run(measurement_id: str, cancel_event: asyncio.Event) -> None` uses repositories, captured providers/classifier and optional SearchGateway. `MeasurementService` owns tasks and retains resolved in-memory secrets/gateway for each active run; worker does not re-read mutable project settings.

- [ ] Write start tests: unconfigured/deleted connections, absent classifier and enabled-but-unconfigured Yandex reject before row creation and before paid calls. Disabled Yandex never needs credentials. No tool-support probe is required. Updating settings/project during run does not change prompts, endpoints, model IDs or classifier.
- [ ] Write worker tests: 15×5 invokes 75 exact saved prompts, no hidden brand text, no crawl/query generation/agent graph; sequential maximum concurrency=1; absent brand bypasses classifier; classifier error stores unknown and preserves answer; failed model permits subsequent pairs. Count estimate is exact and classification estimate is an upper bound.
- [ ] Test cancellation before/after sent marker and late answer; storage failure stops further calls. Optional Yandex persists operation before polling; waiting can be cancelled; unsuccessful search does not discard AI report. Bound total submit/poll lifecycle to 120 seconds using a monotonic deadline and cancellable short waits.
- [ ] Test competing starts, application shutdown and restart: one active task per project, no automatic retry of sent rows, saved outcomes intact, unfinished measurements become interrupted. Completed with row errors has incomplete=true; all checked-model calls failing gives failed. Classifier errors alone keep completed and report unknown.
- [ ] Run `cd backend && uv run pytest tests/test_service_projects.py tests/test_service_measurements.py tests/test_measurement_worker.py`; confirm initial failures.
- [ ] Implement start validation then transactional creation then background task. Offload synchronous provider calls with asyncio.to_thread; bounded await/cancellation cannot necessarily stop an in-flight network request, so provider cleanup happens after its call settles. Terminal guards prevent late writes. Always close providers and handle task exceptions safely.
- [ ] Wire injectable new repositories, services, worker factories and classifier factory in Container. Startup performs recovery, shutdown cancels/stops new tasks without resuming paid work. Preserve old service lifespan behavior.
- [ ] Run task tests plus `tests/test_api_deps.py tests/test_main.py tests/test_service_seo.py`; expect pass. Commit `feat: execute repeatable project measurements`.

### Task 5: Public API and SvelteKit BFF contracts

**Files:** Create `backend/app/api/schemas/projects.py`, `backend/app/api/schemas/measurements.py`, `backend/app/api/routers/projects.py`, `backend/app/api/routers/measurements.py`; modify `backend/app/api/router.py`, `backend/app/api/deps/dependencies.py`. Create `frontend/src/lib/project-types.ts`, `frontend/src/lib/server/projects-api.ts`, `frontend/src/lib/server/projects-api.test.ts` and route files listed below. Modify `frontend/src/lib/types.ts`, `frontend/src/lib/server/python-api.ts` only for the shared typed path allowlist/transport exports. Tests `backend/tests/test_api_projects.py`, `backend/tests/test_api_measurements.py`.

**Interfaces:** Exact spec paths. POST project→201; POST measurement→202 `{id, project_id, status, estimate}`; deletion→204; conflicts→409. New BFF exports `loadProjectsData()`, `loadProjectData(id: string)`, `publicProject`, `publicProjectList`, `publicMeasurement`, `publicMeasurementRows`; constructors produce validated ApiPath. List cursors default to limits 20/50 and reject invalid values.

**BFF files:** `routes/api/projects/+server.ts`, `routes/api/projects/[id]/+server.ts`, `routes/api/projects/[id]/measurements/+server.ts`, `routes/api/measurements/[id]/+server.ts`, `routes/api/measurements/[id]/rows/+server.ts`, `routes/api/measurements/[id]/cancel/+server.ts`.

- [ ] Add API tests for every method, bad input, conflict, missing ID, cursor/kind validation and no secrets/operation IDs/upstream bodies. Model rows carry safe sources and classifier evidence; snapshot/list never includes full answer text.
- [ ] Add BFF projection tests with injected secret/unknown fields, malformed nested values, null metrics, unknown sentiment and Unicode strings. Validate types instead of accepting arbitrary backend objects. Test same-origin refusal and limit/cursor forwarding.
- [ ] Run backend new API tests and `cd frontend && npx vitest run src/lib/server/projects-api.test.ts`; confirm failures.
- [ ] Implement schema allowlists/routers using dependency injection. Extend existing proxy path recognition without loosening host/body-size rules; answer text and sources stay in paginated rows. New starts have ordinary request timeout because they perform only local checks.
- [ ] Run API tests, BFF tests, `src/lib/server/python-api.test.ts` and `npm run check`; expect pass. Commit `feat: expose project and measurement resources`.

### Task 6: Shared project form and project CRUD pages

**Files:** Create `frontend/src/lib/project-form.ts`, `frontend/src/lib/project-form.test.ts`, `frontend/src/lib/components/ProjectForm.svelte`, `frontend/src/lib/components/ProjectForm.test.ts`, `frontend/src/routes/projects/new/+page.server.ts`, `frontend/src/routes/projects/new/+page.svelte`, `frontend/src/routes/projects/[id]/settings/+page.server.ts`, `frontend/src/routes/projects/[id]/settings/+page.svelte`.

**Interfaces:** `projectDraft(project?: Project) -> ProjectDraft`, `projectPayload(draft: ProjectDraft) -> ProjectInput`; ProjectForm props `initial`, `providers`, `saving`, `errors`, `onSave`. Query editor is a list of text/category rows with add/remove controls; competitors similarly brand/site rows. All fields follow Task 1 bounds and use field-level errors.

- [ ] Write tests for create/edit defaults, optional Yandex off, 20/5/10 bounds, unchanged saved category, missing deleted connection displayed rather than silently dropped, save errors retaining input and double-submit lock. Explicitly assert saving does not POST a measurement.
- [ ] Run `cd frontend && npx vitest run src/lib/project-form.test.ts src/lib/components/ProjectForm.test.ts`; expect failures.
- [ ] Implement shared accessible form, provider selection with mode labels, validation and server error mapping. Saving navigates to project detail; editing preserves active/history snapshots. Add cancel/back links and clear missing-configuration explanation.
- [ ] Re-run task tests and `npm run check`; expect pass. Commit `feat: configure projects through forms`.

### Task 7: Measurement report, history and progress page

**Files:** Create `frontend/src/lib/components/MeasurementReport.svelte`, `MeasurementReport.test.ts`, `MeasurementProgress.svelte`, `MeasurementProgress.test.ts`, `MeasurementHistory.svelte`, `MeasurementHistory.test.ts`, `AnswerDialog.svelte`, `AnswerDialog.test.ts` in the same components directory. Create `frontend/src/routes/projects/[id]/+page.server.ts`, `+page.svelte`, `page.test.ts`.

**Interfaces:** MeasurementReport props snapshot/modelRows/searchRows/cursors/loading/error/onMore. MeasurementProgress props snapshot/onCancel. MeasurementHistory props items/selectedId/cursor/loading/onSelect/onMore/onDelete. AnswerDialog props answer/citations/sentiment/onClose. Detail page owns polling and rows keyed by measurement ID and uses Task 5 BFF contracts.

- [ ] Add tests for completed/partial/error/empty report, unknown sentiment explanation, per-model/query/competitor/source/position metrics, optional search and full historical snapshots after editing project. Test choosing two runs does not mix rows/cursors and paging retains earlier rows through polls.
- [ ] Add tests for late fetch after switching project/unmount, active polling stops at terminal state, cancel conflict/error, disabled duplicate start, exact Q×K estimate shown before launch, history deletion refreshes latest. Keyboard dialog close restores focus; duplicate citation URLs render without keyed-loop crash; malicious Markdown is sanitized.
- [ ] Run component/page tests; expect initial failures.
- [ ] Implement report using existing table/metric conventions but independent new types. Reuse Markdown sanitizer and source URL rules. Show service-model sentiment/evidence as an assessment, errors separately, percent-point deltas with signed labels and unavailable-comparison reasons. Keep full text out of snapshot UI state until rows arrive.
- [ ] Implement detail page initial SSR loading, history cursor and selected result, launch/cancel/delete, cancellable polling every 5 seconds while active, and clear errors. A late response can only update the matching current resource. Do not attach old chat/agent components.
- [ ] Run task Vitest tests and `npm run check`; expect pass. Commit `feat: show project measurement reports and history`.

### Task 8: Project dashboard and global navigation

**Files:** Create `frontend/src/lib/components/ProjectCard.svelte`, `ProjectCard.test.ts`, `VisibilityRing.svelte`, `VisibilityRing.test.ts`; modify `frontend/src/routes/+page.server.ts`, `+page.svelte`, `page.test.ts`, `frontend/src/routes/+layout.svelte` as needed. Keep SettingsPanel reachable through existing layout.

**Interfaces:** ProjectCard props project/onStart/onDelete; VisibilityRing props summary with five parts (positive/neutral/negative/unknown/absent). Main page consumes loadProjectsData and implements cursor pagination, empty state and per-project action loading/error.

- [ ] Write tests for sample 32/75 rounded to 43%, truthful five-part ring totals, no result→dash, partial coverage and unavailable deltas, active progress retaining prior result, provider accessible labels and long titles. Test deletion confirmation, blocked active deletion, empty-state link and settings access.
- [ ] Run `cd frontend && npx vitest run src/lib/components/ProjectCard.test.ts src/lib/components/VisibilityRing.test.ts src/routes/page.test.ts`; confirm new behavior fails with the old chat page.
- [ ] Replace main chat screen with responsive project grid and creation button; use SVG/CSS for ring, existing design tokens and no new icon/chart dependency. Card click opens detail; action buttons do not trigger navigation. Render timestamps with client locale/timezone and hydration-safe initial text.
- [ ] Update old root-page assertions to new project behavior; legacy component tests can remain independently. Keep legacy API routes/data without auto-conversion; do not expose participant UI.
- [ ] Re-run task tests, `npm run check` and `npm run build`; expect pass. Commit `feat: replace chat home with project dashboard`.

### Task 9: Isolated end-to-end checks and documentation

**Files:** Create `qa/pages/projects.py`, `qa/pages/projects_api.py`, `qa/tests/test_projects.py`, `qa/project_test_server.py`; modify `qa/conftest.py`, `qa/README.md`, `qa/tests/test_add_provider.py` only where navigation expectations changed, `README.md`, `tech.md`, `backend/README.md`. Update legacy `qa/tests/test_seo.py`, `test_search.py`, `test_run_history.py` to remove obsolete chat-UI expectations while retaining useful API/legacy compatibility checks in backend tests.

**Interfaces:** ProjectsPage is an accessible-selector page object; ProjectsApi is a deterministic server-side test backend, not only page.route mocks. QA launches a SvelteKit instance pointed at this isolated backend. Fixtures use temporary config/database and an in-memory SecretStore; project scenario tests never inherit live-instance cleanup or real keyring writes.

- [ ] Write Playwright scenario: create 15 queries/5 fake models → run 75 pairs → read source and sentiment evidence → run again → assert signed deltas → edit query → assert new series → cancel next run → delete finished run/project. Add all-failure, unknown sentiment and missing-provider scenarios.
- [ ] Run new QA scenarios against isolated fixture services; confirm expected failure before harness/page objects are implemented. Services absent or tests skipped do not count as success.
- [ ] Implement fixture backend responding to SSR and browser BFF requests, isolated SvelteKit process and automatic cleanup. Use port allocation and wait for health, not arbitrary sleeps. Mark project scenarios `isolated_projects` and make legacy require_running_services/no_connection_survives_a_test autouse fixtures bypass them before looking up the live application fixture. Avoid deleting/creating real providers through the old autouse fixtures.
- [ ] Update documents: project form, manual launch, Q×K budget plus sentiment calls, optional Yandex, comparison identity/partial-data rules, interrupted behavior, retained legacy APIs and QA isolation. Clarify sentiment is model assessment and no schedule/chat in active UI.
- [ ] Run `cd backend && uv run pytest` and `uv run ruff check app tests` (report pre-existing failures separately without unrelated rewrites); `cd frontend && npx vitest run`, `npm run check`, `npm run lint`, `npm run format:check`, `npm run build`; `cd qa && QA_HEADLESS=1 uv run pytest tests/test_projects.py` using isolated fixtures. Formatting fixes are limited to touched files.
- [ ] Inspect desktop and narrow-screen dashboard/form/report screenshots and dialog keyboard flow. Record actual passing counts and any remaining limitations; never mark a skipped browser suite verified.
- [ ] Run `git diff --check`; commit `test: verify project measurements end to end` with QA and docs. Perform final branch review focused on migration, late writes, secrets, denominators and paid-call duplication before claiming completion.

## Self-review and execution handoff

All spec sections map to tasks: validation (1), storage/compatibility (2), sentiment
and metrics (3), lifecycle/budgets (4), API/BFF (5), form (6), detail/history (7),
cards/main UI (8), verification/docs (9). Interfaces are shared above; new worker
does not fake legacy SeoInput/site readiness. The five Review Focus conditions
have named assertions in their owning tasks.

Execution is sequential by dependency: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9.
Tasks each end in a targeted passing check and scoped commit. Before execution,
read spec and plan, inspect current branch/worktree and user changes, then use
using-git-worktrees as applicable. No implementation has been authorized by
approval of the spec alone: user reviews this plan and selects the execution
method. Recommended: native execution in this chat, because these nine tasks
share contracts and most risk is in their integration.
