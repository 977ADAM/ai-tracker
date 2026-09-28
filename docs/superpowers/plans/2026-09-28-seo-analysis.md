# SEO Analysis of a Site and Its Competitors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the brand-check form on the home page with a one-shot SEO analysis: five input fields create a durable analysis that runs six fixed stages (site facts, competitors, query generation, Yandex and model checks, aggregation, report) and exposes a saved report in a separate history.

**Architecture:** New SEO domain rules, ports, services, repository, and routes sit beside the existing brand-check stack and reuse the existing model adapters, `SearchGateway`, `SecretStore`, and SQLite file. A server-side orchestrator owns the six stages, persists every row as it arrives, keeps the Yandex and model branches independent, and survives application restarts by resuming already-submitted deferred Yandex operations. The existing `/api/check`, `/api/search`, `/api/runs` contracts and limits stay unchanged.

**Tech Stack:** Python 3.13+, FastAPI, Pydantic, httpx, SQLite (stdlib) with WAL, keyring, LangChain chat client over an OpenAI-compatible endpoint, SvelteKit 2, Svelte 5, TypeScript, Tailwind v4, pytest, Vitest, Playwright (`qa/`).

**Spec:** `docs/superpowers/specs/2026-09-28-seo-analysis-design.md`

**Working tree note:** The current spec revision is uncommitted. Commit `docs/superpowers/specs/2026-09-28-seo-analysis-design.md` as a `docs:` commit before Task 1, so every task builds on a clean tree. The `.superpowers/sdd/2026-09-28-seo-analysis/` ledger is gitignored and local-only.

## Global Constraints

- The form is one-shot: URL of the home page, business sphere, exactly three key queries, at least one service, one to five model connections. There is no preview step, no confirmation dialog, and no site-data editing before the run.
- The generated-query limit is a fixed SEO constant: at most 20 unique queries per run, at least 5 after one regeneration attempt. There is no limit field in the form and the old 20-query validators stay untouched.
- Search is Yandex only, region 225, top-10 organic results, deferred `searchAsync` mode. Key queries are never sent to consumer models and never enter visibility statistics.
- Company name and extra services come from stage 1. Services entered by the user stay first in the merged list; nothing the user typed is dropped.
- Competitors are domains seen in at least two successful key-query SERPs. The SERP title is evidence only: every competitor metric is computed by host.
- Literal whole-phrase matching only: NFKC, `casefold`, `ё`→`е`, whitespace collapsing, word-boundary punctuation. No morphology, translation, transliteration, or aliases. The existing `/api/check` matching behavior must not change.
- Metrics are computed from stored rows only. An error is never counted as an absent mention or an absent site; an empty denominator renders `—`, never `0 %`.
- Stage 1 and stage 3 failures are fatal and must happen before any paid search or model call. Stage 2 failures degrade to "no competitors"; stage 4 failures are per-row; a summary failure never blocks the report.
- Yandex and model branches are independent. Per-run storage failure stops only that analysis and must not reuse the global `RunService.stopping` event.
- Analyses are durable: created before the first external call, rows saved in separate transactions, SQLite WAL with a bounded `busy_timeout`. Already-submitted Yandex operation IDs are stored so a restart resumes polling them without paying twice; model rows and never-submitted Yandex rows become `interrupted`.
- Cancellation is supported and final: `POST /api/seo/analyses/{id}/cancel` stops new submissions and polls, keeps finished rows, and forbids resuming. Deletion is allowed only in terminal states.
- Secrets never appear in API responses, history, logs, or tests. The public LLM settings response returns endpoint, model, `has_api_key`, and per-field sources, never the key.
- A remote LLM endpoint must be HTTPS. HTTP and IP literals are allowed only for loopback. This needs a new validator; the existing `validate_endpoint` must not be relaxed.
- The LangChain usage is narrowed to a chat client plus manual JSON parsing: no agents, no tools, no `response_format`/tool-calling features, no LangSmith tracing variables.
- Every new BFF path must be added to the allowlist and path union and needs a manual response projector; heavy stages never run inside an HTTP request.
- Tests never call paid external APIs: use fakes and `httpx.MockTransport`.
- Backend commands: `cd backend && uv run pytest -q && uv run ruff check app tests`. Frontend commands: `cd frontend && npm run check && npx vitest run && npm run build`.

## Review Focus

- Stage ordering guarantees: a fatal stage 1 or stage 3 error must produce zero Yandex and zero model calls, and the analysis must end in a terminal failed state — test in Task 5.
- Stage 2 degradation: all three key searches failing must still generate queries and run checks with candidates marked unavailable — test in Tasks 3 and 5.
- Resume semantics: after a simulated restart, already-submitted Yandex operation IDs are polled (no resubmission), model rows and unsubmitted rows become `interrupted`, and the report stays readable — test in Tasks 4 and 5.
- Migration on a populated legacy database: a version-2 `runs.sqlite3` keeps its runs readable, gains the SEO tables, and ends at version 3; `RunRepository` still opens it afterwards — test in Task 4.
- Fetcher security: private/loopback/link-local addresses, DNS rebinding, cross-host redirects, size, redirect count, and timeout limits are enforced, and the connection uses the verified address — test in Task 2.
- Metric correctness: per-category, per-service, branded/unbranded splits, host-only competitor matching, and `—` for empty denominators — test in Task 3.
- BFF safety: new paths are allowlisted, responses are projected, oversized detail responses are paginated, and the settings test gets its own timeout — test in Task 7.
- Secret hygiene and regression: the key never appears in GET/BFF/report payloads, and old `/api/check`, `/api/search`, `/api/runs` tests stay green — test in Tasks 6, 7, and 9.

---

### Task 1: SEO LLM settings domain, persistence, and JSON chat client

**Files:**
- Create: `backend/app/domain/seo_settings.py`
- Create: `backend/app/domain/seo_llm.py`
- Create: `backend/app/db/seo_settings.py`
- Create: `backend/app/integrations/seo_llm.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_domain_seo_settings.py`
- Test: `backend/tests/test_domain_seo_llm.py`
- Test: `backend/tests/test_db_seo_settings.py`
- Test: `backend/tests/test_integrations_seo_llm.py`
- Test: `backend/tests/test_search_config.py` (environment fallback)

**Interfaces:**
- Produces `SeoSettings` as the resolved immutable value with internal `endpoint: str`, `model: str`, `api_key: str | None`, and public-safe `has_api_key: bool`, `endpoint_source`, `model_source`, `api_key_source` each in `Literal["ui", "env", "none"]`.
- Produces `validate_seo_endpoint(value: object) -> str`: scheme must be `https`, except `http` on loopback; explicit port allowed; `localhost`/`127.0.0.0/8`/`::1` allowed for both schemes; other IP literals rejected; userinfo, query, fragment, backslashes, whitespace, and `//` in the path rejected; path must end with `/chat/completions`.
- Produces `SeoSettingsRepository(config_dir: Path, secrets: SecretStore, *, env_endpoint: str | None, env_model: str | None, env_api_key: str | None, service_name: str)` with `load() -> SeoSettings`, `update(payload: Mapping[str, object]) -> SeoSettings`, and `reset_credentials() -> SeoSettings`. Metadata lives in `seo-settings.json` (owner-only, atomic write); the key lives in keyring under a dedicated account; UI values win over environment values; an omitted or empty key never clears a stored key.
- Produces `parse_json_object(text: str) -> dict[str, object]` raising a domain error on non-object JSON; strips Markdown code fences and surrounding prose.
- Produces `SeoLlmClient(endpoint: str, api_key: str, model: str, client: httpx.AsyncClient)` with `async def complete(system: str, user: str) -> str`, returning assistant text and raising fixed safe `ProviderError` messages for auth, rate limit, transport, and malformed payloads.
- `Settings` gains `seo_llm_endpoint`, `seo_llm_model`, `seo_llm_api_key` from `SEO_LLM_ENDPOINT`, `SEO_LLM_MODEL`, `SEO_LLM_API_KEY`.

- [ ] **Step 1: Write failing endpoint-validator tests** for remote HTTPS acceptance, remote HTTP rejection, loopback HTTP with port acceptance, IP-literal rejection outside loopback, missing `/chat/completions` suffix, and userinfo/query/fragment rejection.
- [ ] **Step 2: Run the focused domain tests** with `cd backend && uv run pytest tests/test_domain_seo_settings.py -q` and confirm they fail for the missing validator and value type.
- [ ] **Step 3: Implement `validate_seo_endpoint`, `SeoSettings`, and source resolution** in `backend/app/domain/seo_settings.py`, plus environment resolution in `backend/app/core/config.py` following the existing `first_value` pattern.
- [ ] **Step 4: Write failing JSON-contract tests** for fenced JSON, JSON with surrounding prose, invalid JSON, JSON arrays, and empty text.
- [ ] **Step 5: Implement `parse_json_object`** in `backend/app/domain/seo_llm.py` and confirm the focused tests pass.
- [ ] **Step 6: Write failing repository tests** for absent-file defaults, UI-over-env precedence per field, independent mixed sources, owner-only permissions, key absent from JSON, rollback when keyring write fails, partial update, empty key preserving the stored key, and full credential reset including the no-op case.
- [ ] **Step 7: Implement `SeoSettingsRepository`** in `backend/app/db/seo_settings.py` and confirm `cd backend && uv run pytest tests/test_db_seo_settings.py -q` passes.
- [ ] **Step 8: Write failing adapter tests** with `httpx.MockTransport` for request shape (model, messages, bearer auth), assistant text extraction, 401/403/429/5xx mapping, timeout mapping, and absence of upstream bodies in errors.
- [ ] **Step 9: Implement `SeoLlmClient`** in `backend/app/integrations/seo_llm.py` with `follow_redirects=False` and bounded timeouts; confirm the focused adapter tests pass.
- [ ] **Step 10: Run `cd backend && uv run pytest tests/test_domain_seo_settings.py tests/test_domain_seo_llm.py tests/test_db_seo_settings.py tests/test_integrations_seo_llm.py tests/test_search_config.py -q && uv run ruff check app tests`.**
- [ ] **Step 11: Commit** the settings domain, repository, client, parser, and tests.

### Task 2: SSRF-safe public site fetcher

**Files:**
- Create: `backend/app/domain/site_fetch.py`
- Create: `backend/app/integrations/site_fetcher.py`
- Test: `backend/tests/test_domain_site_fetch.py`
- Test: `backend/tests/test_integrations_site_fetcher.py`

**Interfaces:**
- Produces `canonical_host(value: object) -> str`: validates an HTTP(S) URL or bare host, lowercases it, strips the trailing dot and a leading `www.`, and raises `ValidationError` with a safe message otherwise. Tasks 3 and 5 import this function; do not duplicate host rules.
- Produces `same_site_host(target: str, candidate: str) -> bool` (exact host or a subdomain of it) and `is_public_address(value: str) -> bool` (rejects loopback, private, link-local, multicast, reserved, unspecified, and local names).
- Produces constants `MAX_FETCH_PAGES = 20`, `MAX_FETCH_BYTES = 1 MiB`, `FETCH_TOTAL_TIMEOUT = 60.0`, `FETCH_CONNECT_TIMEOUT = 10.0`, `MAX_FETCH_REDIRECTS = 5`.
- Produces `SiteFetcher` protocol with `async def fetch(host: str) -> tuple[FetchedPage, ...]` and `FetchedPage` as `(url, title, text)`.
- Produces `HttpxSiteFetcher(client: httpx.AsyncClient, *, resolver: Callable[[str], Awaitable[tuple[str, ...]]] | None = None)` in `integrations/site_fetcher.py`.
- Extraction uses the standard library only: `html.parser` for title, visible text, and same-host links; `urllib.robotparser` for `robots.txt`. No new HTML dependency is added.

- [ ] **Step 1: Write failing rule tests** for `canonical_host` (scheme, path, port, `www.`, trailing dot, invalid input), `same_site_host` (subdomain acceptance, lookalike rejection), and `is_public_address` (every blocked range plus a public address).
- [ ] **Step 2: Implement the rule functions and constants** in `backend/app/domain/site_fetch.py`; confirm `cd backend && uv run pytest tests/test_domain_site_fetch.py -q` passes.
- [ ] **Step 3: Write failing fetcher tests** with an injected resolver and `httpx.MockTransport`: crawl starts at the entered host, follows only same-host links, stops at 20 pages, truncates at 1 MiB, honors the total timeout and connect timeout, follows at most five redirects, re-validates the address after each redirect, refuses a cross-host redirect, skips a URL disallowed by `robots.txt`, ignores non-HTML content, and never executes scripts.
- [ ] **Step 4: Implement address verification and connection pinning** so the socket connects to the verified address while the Host header and TLS SNI use the requested hostname.
- [ ] **Step 5: Implement crawling, robots handling, size and timeout bounds, and text extraction**; each failure becomes a safe error, and a partial crawl returns the pages already read.
- [ ] **Step 6: Run `cd backend && uv run pytest tests/test_domain_site_fetch.py tests/test_integrations_site_fetcher.py -q && uv run ruff check app tests`.**
- [ ] **Step 7: Commit** the fetcher port, adapter, and tests.

### Task 3: SEO rules, prompts, and report metrics

**Files:**
- Create: `backend/app/domain/seo.py`
- Create: `backend/app/domain/seo_prompts.py`
- Create: `backend/app/domain/seo_report.py`
- Modify: `backend/app/domain/matching.py` only to add normalized helpers; `mentions_brand` behavior must not change
- Test: `backend/tests/test_domain_seo.py`
- Test: `backend/tests/test_domain_seo_prompts.py`
- Test: `backend/tests/test_domain_seo_report.py`
- Test: `backend/tests/test_domain_matching.py` (extend)

**Interfaces:**
- Produces `SeoInput` from `normalize_seo_request(payload: object) -> SeoInput` with `url`, `host`, `sphere` (≤200 chars), `seeds` (exactly three distinct non-empty, ≤400 chars and ≤40 words each), `services` (1..20 distinct, ≤100 chars each), and `connection_ids` (1..5 distinct). SEO limits are separate constants; `LIMITS` and `domain/requests.py` stay untouched.
- Produces `GENERATED_QUERY_LIMIT = 20`, `MIN_GENERATED_QUERIES = 5`, `QUERY_CATEGORIES = ("commercial", "informational", "comparative")`, `MAX_QUERY_LENGTH = 400`, `MAX_QUERY_WORDS = 40`.
- Produces normalization helpers in `matching.py`: `normalize_text(value: str) -> str` (NFKC, `casefold`, `ё`→`е`, whitespace collapse) and `mentions_phrase(answer: str, phrase: str) -> bool` with punctuation word boundaries. `mentions_brand` keeps its current implementation and tests.
- Produces `hosts_match(target: str, candidate: str) -> bool` reusing Task 2 host semantics plus leading-`www.` handling.
- Produces `merge_services(user_services: Sequence[str], site_services: Sequence[str]) -> tuple[str, ...]` (user order first, normalized dedupe, user text preserved).
- Produces `rank_candidates(seed_results: Sequence[SeedResult], user_host: str) -> tuple[Candidate, ...]` with `Candidate(host, title, occurrences, average_position, seed_indexes, recurring: bool)`; recurring means two or three successful SERPs; ordering by occurrences then average position then host.
- Produces `accept_generated_queries(payload: object, services: Sequence[str]) -> tuple[GeneratedQuery, ...]` validating schema, category enum, Yandex length/word limits, normalized dedupe, truncation to 20, mapping an unknown service to `None`, and raising a domain error when fewer than 5 unique queries remain.
- Produces `flag_queries(queries, company_name, company_host, candidate_hosts) -> tuple[QueryFlags, ...]` marking `mentions_company_name`, `mentions_company_host`, and `mentions_candidate_host`, with branded meaning either company flag true.
- Produces prompt builders in `seo_prompts.py`: `site_facts_prompt(host: str, pages: Sequence[FetchedPage]) -> tuple[str, str]`, `queries_prompt(input: SeoInput, company_name: str, services: Sequence[str], candidates: Sequence[Candidate]) -> tuple[str, str]`, `summary_prompt(metrics: Mapping[str, object]) -> tuple[str, str]`, plus `site_facts_from_payload(payload) -> SiteFacts` and `queries_from_payload(payload, services) -> ...` schema validators. Untrusted page text must be delimited and explicitly marked as data; no page text is ever placed in the system message.
- Produces `SeoRowOutcome = Literal["found", "absent", "error", "interrupted", "cancelled"]`, `SearchRowValue`, and `ModelRowValue` — the stored-row projections `build_report` consumes. `SeoRepository` in Task 4 persists these values and does not redefine them.
- Produces `build_report(input: SeoInput, company_name: str, services: Sequence[str], candidates: Sequence[Candidate], queries: Sequence[GeneratedQuery], search_rows: Sequence[SearchRowValue], model_rows: Sequence[ModelRowValue]) -> dict[str, object]` with site and recurring-candidate Yandex shares, name/domain/combined AI shares per connection, category and service breakdowns, branded/unbranded splits, and `None` (rendered as `—`) for empty denominators and never-found positions.

- [ ] **Step 1: Write failing input-validation tests** for URL/host canonicalization, sphere bounds, three distinct key queries, per-query length and word limits, service and connection bounds, and rejection of unknown fields.
- [ ] **Step 2: Implement `normalize_seo_request` and the SEO constants** in `backend/app/domain/seo.py`; confirm the focused tests pass without touching `LIMITS`.
- [ ] **Step 3: Write failing normalization tests** covering NFKC full-width forms, NBSP, `ё`/`е`, repeated whitespace, punctuation boundaries, multi-word company names, and the unchanged `mentions_brand` results.
- [ ] **Step 4: Implement `normalize_text`, `mentions_phrase`, and `hosts_match`**; keep every existing `test_domain_matching.py` case green.
- [ ] **Step 5: Write failing service-merge and candidate-ranking tests** for user-first ordering, site-service dedupe, occurrences ordering, average-position tie-breaking, one-success and zero-success cases producing no recurring candidates, and user-host and subdomain exclusion.
- [ ] **Step 6: Implement `merge_services` and `rank_candidates`** and confirm the focused tests pass.
- [ ] **Step 7: Write failing generation tests** for valid payloads, code-fenced JSON, bad category, over-long and over-word queries, duplicates, more than 20 entries, unknown service mapping, and the fewer-than-five failure.
- [ ] **Step 8: Implement `accept_generated_queries` and `flag_queries`**, then write the failing prompt tests proving page text never enters the system message and that prompts contain spheres, services, seeds, and candidate hosts.
- [ ] **Step 9: Implement `seo_prompts.py`** and its payload validators; confirm the focused prompt tests pass.
- [ ] **Step 10: Write failing report tests** for site and candidate shares, per-connection name/domain/combined shares, category and service breakdowns, branded versus unbranded denominators, error rows excluded, `—` for empty denominators, and `—` position when never found.
- [ ] **Step 11: Implement `build_report`** and run `cd backend && uv run pytest tests/test_domain_seo.py tests/test_domain_seo_prompts.py tests/test_domain_seo_report.py tests/test_domain_matching.py -q && uv run ruff check app tests`.
- [ ] **Step 12: Commit** the SEO rules, prompts, metrics, and tests.

### Task 4: SEO persistence and schema migration

**Files:**
- Create: `backend/app/db/seo.py`
- Modify: `backend/app/db/runs.py` only to accept supported schema versions
- Modify: `backend/app/api/deps.py` to initialize the SEO repository after the run repository
- Test: `backend/tests/test_db_seo.py`
- Test: `backend/tests/test_db_runs.py` (extend with the version-3 migration case)

**Interfaces:**
- Produces `SeoRepository(config_dir: Path)` over the existing `runs.sqlite3` with `initialize()`, creating SEO tables and raising `PRAGMA user_version` to 3; `RunRepository` must accept versions 0–3 and must not create or alter SEO tables.
- Produces `SeoAnalysisStatus = Literal["running", "completed", "failed", "interrupted", "cancelled"]` and `SeoStageStatus = Literal["pending", "running", "done", "error", "skipped"]`; terminal analysis states are `completed`, `failed`, `interrupted`, `cancelled`. Task 3 keeps ownership of `SeoRowOutcome`, `SearchRowValue`, and `ModelRowValue`; this task persists them without redefining them.
- Produces `create_analysis(input: SeoInput, estimate: Mapping[str, int]) -> str`, `update_stage(analysis_id, stage, status, *, error=None, counters=None)`, `save_site_facts(analysis_id, company_name, services, pages)`, `replace_candidates(analysis_id, candidates)`, `replace_queries(analysis_id, queries)`, `save_search_row(analysis_id, query_index, *, status, operation_id=None, site_position=None, site_url=None, error=None)`, `save_candidate_hits(analysis_id, query_index, hits)`, `save_model_row(analysis_id, connection_id, provider_name, query_index, *, status, answer=None, name_mentioned=None, host_mentioned=None, error=None)`, `save_summary(analysis_id, text | None)`, `finish_analysis(analysis_id)`.
- Produces `resume_plan(analysis_id) -> ResumePlan` with submitted Yandex operation IDs to poll, `mark_interrupted(analysis_id)`, `interrupt_unsubmitted_rows(analysis_id)`, `cancel(analysis_id)`, `delete(analysis_id)`, `list_page(cursor=None, limit=20)`, `snapshot(analysis_id)`, and `rows_page(analysis_id, kind: Literal["model", "search"], cursor=None, limit=50)`.
- Connection handling enables `journal_mode=WAL` and `busy_timeout`, uses one transaction per saved row, keeps file and directory permissions owner-only, and raises the existing safe `StorageError` without leaking SQL.

- [ ] **Step 1: Write failing migration tests** proving a populated version-2 database keeps its runs and rows readable, gains the SEO tables, ends at `user_version = 3`, and can still be opened by `RunRepository` (including `recover_unfinished()`).
- [ ] **Step 2: Relax the version guard in `RunRepository.initialize()`** to a documented supported range and add `initialize()` to `SeoRepository`; confirm the migration tests pass.
- [ ] **Step 3: Write failing persistence tests** for durable analysis creation before external calls, per-row commits visible to a second repository instance, ordered stage updates with counters, candidate and query replacement, and a storage failure surfacing as `StorageError` without partial rows.
- [ ] **Step 4: Implement analysis, stage, site-facts, candidate, query, search-row, candidate-hit, and model-row writes**; confirm the focused tests pass.
- [ ] **Step 5: Write failing lifecycle tests** for cursor pagination newest-first with `next_cursor`, snapshot aggregates and readiness flags, `rows_page` filtering and ordering, cancel, delete of terminal analyses, rejection of deleting an active analysis, and `resume_plan` separating submitted operation IDs from unsubmitted rows.
- [ ] **Step 6: Implement snapshot, pagination, cancel, delete, and resume-plan reads** with a lightweight listing that does not build full report payloads per item.
- [ ] **Step 7: Write failing concurrency tests** saving several hundred rows with two repository instances and asserting no `database is locked` failure under WAL with `busy_timeout`.
- [ ] **Step 8: Enable WAL and `busy_timeout`, then run `cd backend && uv run pytest tests/test_db_seo.py tests/test_db_runs.py -q && uv run ruff check app tests`.**
- [ ] **Step 9: Commit** the SEO repository, migration, and tests.

### Task 5: SEO orchestrator, Yandex document titles, and runtime wiring

**Files:**
- Create: `backend/app/service/seo.py`
- Modify: `backend/app/domain/search.py` to add `SearchDocument.title`
- Modify: `backend/app/integrations/yandex_search.py` to parse `<title>`
- Modify: `backend/app/service/search_settings.py` to expose a read-only gateway snapshot
- Modify: `backend/app/api/deps.py`
- Test: `backend/tests/test_service_seo.py`
- Test: `backend/tests/test_integrations_yandex_search.py` (extend)
- Test: `backend/tests/test_service_search_settings.py` (extend)
- Test: `backend/tests/fakes.py` (add SEO fakes)

**Interfaces:**
- Consumes Task 1 `SeoSettings`, `SeoLlmClient`, `parse_json_object`; Task 2 `HttpxSiteFetcher`, `canonical_host`; Task 3 `SeoInput`, prompt builders, `rank_candidates`, `accept_generated_queries`, `flag_queries`, `build_report`; Task 4 `SeoRepository`.
- Produces `SearchDocument(url: str, title: str = "")`; `parse_documents` reads `<title>` and stores an empty string when absent; `SearchRow` and the old `search_rows` table stay unchanged.
- Produces `SearchSettingsService.gateway_snapshot() -> SearchGateway | None` and `.enabled() -> bool` so the orchestrator can capture the gateway at run start without seeing credentials.
- Produces `SeoService(repository, llm_settings, llm_factory, fetcher, yandex_settings, connections, provider_factory, *, max_model_concurrency=5)`, where `repository` is Task 4 `SeoRepository`, `llm_settings` is Task 1 `SeoSettingsRepository`, `llm_factory: Callable[[], SeoLlmClient | None]` builds the client from resolved settings, `fetcher` is Task 2 `SiteFetcher`, and `yandex_settings` is `SearchSettingsService`, with:
  - `async def start(payload: object) -> dict[str, object]` — validates, rejects a disabled Yandex with the existing safe error, refuses to start without an LLM configuration, creates the durable analysis, spawns one background task, and returns `202` payload `{id, status, estimate}` immediately;
  - `def snapshot(analysis_id) -> dict`, `def list_page(cursor=None) -> dict`, `def rows_page(analysis_id, kind, cursor=None) -> dict`, `def cancel(analysis_id) -> dict`, `def delete(analysis_id) -> None`;
  - `def recover() -> None` — called at startup to mark rows without operation IDs interrupted and to resume polling submitted Yandex operations.
- Stage implementations keep the spec order: (1) fetch and extract site facts, (2) three key searches in Yandex and candidate ranking, (3) generate and validate queries, (4) Yandex and model checks in independent branches, (5) aggregate metrics and build the summary, (6) persist the report.
- Per-analysis stop flag plus `StorageError` handling: a storage failure stops only this analysis and marks it failed without touching other analyses or `RunService`.

- [ ] **Step 1: Write failing gateway tests** for `<title>` extraction, absent title, malformed XML, and unchanged existing document order and error mapping.
- [ ] **Step 2: Add `SearchDocument.title` and `<title>` parsing**; keep every existing Yandex test green (`cd backend && uv run pytest tests/test_integrations_yandex_search.py tests/test_domain_search.py tests/test_service_search.py -q`).
- [ ] **Step 3: Write failing settings-service tests** for `gateway_snapshot()` returning the configured gateway, `None` before configuration, and a stable gateway for a job that started earlier; keep the existing settings tests green.
- [ ] **Step 4: Implement `gateway_snapshot()` and `enabled()`** without exposing credentials.
- [ ] **Step 5: Write failing orchestrator happy-path tests** with fake fetcher, fake LLM, fake gateway, and fake provider factory: `202` shape with the `3 + 20` and `20 × M` estimate, six stages reaching terminal states in order, site facts and merged services stored, candidates ranked, queries generated and persisted with flags, both branches writing rows, report built, analysis completed, and no paid call before stage 4.
- [ ] **Step 6: Implement the orchestrator skeleton, stage state machine, and single background task**; confirm the happy-path tests pass.
- [ ] **Step 7: Write failing failure-path tests** for a crawl error and an LLM error at stage 1 (no Yandex and no model calls, analysis `failed`), fewer than five generated queries (one retry, then failure), all three key searches failing (run continues with candidates unavailable), a single Yandex row failing while model rows succeed, one model connection failing while others and Yandex succeed, and a summary failure that still completes the report.
- [ ] **Step 8: Implement retry, degradation, branch independence, and per-row error persistence**; confirm the failure-path tests pass.
- [ ] **Step 9: Write failing lifecycle tests** for cancel stopping submissions and polls, delete of a terminal analysis, deletion conflict while running, storage failure isolating one analysis, and `recover()` resuming submitted Yandex operations after a simulated restart while marking model and unsubmitted rows interrupted.
- [ ] **Step 10: Implement cancel, delete, storage-failure isolation, and `recover()`**; wire the SEO repository, service, fetcher, and LLM factory into `build_container()` and call `recover()` at startup.
- [ ] **Step 11: Run `cd backend && uv run pytest -q && uv run ruff check app tests`** and confirm the full backend suite is green.
- [ ] **Step 12: Commit** the orchestrator, Yandex title support, wiring, and tests.

### Task 6: SEO FastAPI resources for settings and analyses

**Files:**
- Create: `backend/app/service/seo_settings.py`
- Create: `backend/app/api/schemas/seo_settings.py`
- Create: `backend/app/api/schemas/seo.py`
- Create: `backend/app/api/routers/seo_settings.py`
- Create: `backend/app/api/routers/seo.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/api/deps.py`
- Test: `backend/tests/test_service_seo_settings.py`
- Test: `backend/tests/test_api_seo_settings.py`
- Test: `backend/tests/test_api_seo.py`

**Interfaces:**
- Consumes Task 1 settings domain and repository, Task 5 `SeoService`.
- Produces `SeoSettingsService.public() -> dict`, `.update(payload) -> dict`, `.reset_credentials() -> dict`, `.test() -> dict`, `.build_client() -> SeoLlmClient | None` (over the shared `httpx.AsyncClient`); public shape is exactly `{"endpoint", "model", "has_api_key", "endpoint_source", "model_source", "api_key_source"}`.
- Routes: `GET/PUT /api/seo/settings`, `DELETE /api/seo/settings/credentials`, `POST /api/seo/settings/test`, `POST /api/seo/analyses`, `GET /api/seo/analyses`, `GET /api/seo/analyses/{id}`, `GET /api/seo/analyses/{id}/rows`, `POST /api/seo/analyses/{id}/cancel`, `DELETE /api/seo/analyses/{id}`.
- Response bodies never contain the API key, upstream bodies, Yandex operation IDs, or internal exception text; `POST /api/seo/analyses` returns `202` with `{id, status, estimate}` including the upper bounds; `GET /{id}` returns stages, inputs, extracted facts, candidates, aggregates, and readiness flags but no model answer text; `rows` returns paginated detail with answers.

- [ ] **Step 1: Write failing settings-service tests** for public projection, partial update, empty key preservation, reset, and a successful settings test that never returns the secret.
- [ ] **Step 2: Implement `SeoSettingsService`** and confirm `cd backend && uv run pytest tests/test_service_seo_settings.py -q` passes.
- [ ] **Step 3: Write failing settings API tests** for exact GET fields, partial PUT, rejection of `null` and unknown fields, DELETE reset and no-op, `POST /test` success and failure shapes, and no secret anywhere in bodies or error messages.
- [ ] **Step 4: Implement the settings schemas and router** and register the settings router before the analyses router in `api/router.py`.
- [ ] **Step 5: Write failing analyses API tests** for `202` creation with estimate, invalid input rejection before any external call, disabled-Yandex rejection, missing LLM configuration rejection, history pagination, snapshot shape, rows filtering and pagination, cancel of a running analysis, conflict on deleting a running analysis, `404` for unknown IDs, and absence of operation IDs and secrets.
- [ ] **Step 6: Implement the analyses schemas and router** and register both SEO routers in `api/router.py`.
- [ ] **Step 7: Wire services into `build_container()`** with injectable overrides for tests and confirm existing container tests still pass.
- [ ] **Step 8: Run `cd backend && uv run pytest -q && uv run ruff check app tests`.**
- [ ] **Step 9: Commit** the SEO services, schemas, routes, and tests.

### Task 7: SvelteKit BFF, server-loaded state, and the LLM settings panel

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/server/python-api.ts`
- Modify: `frontend/src/lib/server/python-api.test.ts`
- Modify: `frontend/src/routes/+layout.server.ts`
- Modify: `frontend/src/routes/+layout.svelte`
- Create: `frontend/src/lib/components/SeoSettingsPanel.svelte`
- Create: `frontend/src/lib/components/SeoSettingsPanel.test.ts`
- Create: `frontend/src/routes/api/seo/settings/+server.ts`
- Create: `frontend/src/routes/api/seo/settings/credentials/+server.ts`
- Create: `frontend/src/routes/api/seo/settings/test/+server.ts`
- Create: `frontend/src/routes/api/seo/analyses/+server.ts`
- Create: `frontend/src/routes/api/seo/analyses/[id]/+server.ts`
- Create: `frontend/src/routes/api/seo/analyses/[id]/cancel/+server.ts`
- Create: `frontend/src/routes/api/seo/analyses/[id]/rows/+server.ts`
- Test: `frontend/src/lib/components/SettingsLayout.test.ts` (extend)

**Interfaces:**
- Produces `SeoSettings` (`endpoint`, `model`, `has_api_key`, `endpoint_source`, `model_source`, `api_key_source`) and SEO analysis types (`SeoAnalysisCreated`, `SeoAnalysisSnapshot`, `SeoStage`, `SeoCandidate`, `SeoAggregates`, `SeoRowsPage`) in `types.ts`.
- Extends the `ApiPath` union and the allowlist with the SEO paths, adds a projector for every SEO response (unknown shapes rejected), keeps the shared origin and body-size checks, and applies a path-scoped timeout to `POST /api/seo/settings/test` instead of the shared short timeout.
- `loadPageData()` returns `seoSettings: SeoSettings | null` plus a safe `seoSettingsError`; the SEO settings load must not break providers, form, regions, or Yandex settings loading.
- `SeoSettingsPanel` receives only the public settings and callbacks: it never receives or renders a key, preserves the stored key on an empty field, and offers the reset action.
- The settings modal gains a third keyboard-accessible tab «SEO-анализ» while «Модели» remains the initial tab.

- [ ] **Step 1: Write failing `python-api.test.ts` cases** for SEO settings projection with a rejected secret field, settings test timeout behavior, analyses creation with `202`, snapshot projection, rows pagination with cursor validation, cancel, delete, and safe upstream failures.
- [ ] **Step 2: Implement types, allowlist entries, path builders, and projectors**; confirm `cd frontend && npx vitest run src/lib/server/python-api.test.ts` passes.
- [ ] **Step 3: Add the SvelteKit route handlers** for the settings, credentials, test, analyses, cancel, and rows paths using `proxyJson`.
- [ ] **Step 4: Extend `loadPageData()`** and `+layout.server.ts` typing for independent SEO settings loading.
- [ ] **Step 5: Write failing panel tests** for empty and configured states, source indicators, save with a changed endpoint/model, save with an empty key preserving the stored one, the connection test result, reset, and error states.
- [ ] **Step 6: Implement `SeoSettingsPanel.svelte`** following the existing Yandex settings panel.
- [ ] **Step 7: Add the third tab** in `+layout.svelte` and extend `SettingsLayout.test.ts` for tab reachability, default tab, and panel rendering.
- [ ] **Step 8: Run `cd frontend && npm run check && npx vitest run src/lib/server/python-api.test.ts src/lib/components/SeoSettingsPanel.test.ts src/lib/components/SettingsLayout.test.ts`.**
- [ ] **Step 9: Commit** the BFF, types, loader, panel, and tests.

### Task 8: SEO form and run screen

**Files:**
- Create: `frontend/src/lib/seo-form.ts`
- Create: `frontend/src/lib/seo-form.test.ts`
- Create: `frontend/src/lib/components/SeoForm.svelte`
- Create: `frontend/src/lib/components/SeoRunProgress.svelte`
- Create: `frontend/src/lib/components/SeoRunProgress.test.ts`
- Modify: `frontend/src/routes/+page.svelte`
- Modify: `frontend/src/routes/+page.server.ts`
- Test: `frontend/src/lib/components/SeoForm.test.ts`

**Interfaces:**
- Produces form rules in `seo-form.ts`: URL and sphere validation, exactly three distinct key queries, at least one service, one to five selected connections, and estimate helpers returning `{upperSearch: 23, upperModel: 20 * M, actualSearch: 3 + K, actualModel: K * M}`.
- Produces `SeoForm.svelte` with URL, sphere, three key-query inputs, a services textarea (one per line), connection checkboxes defaulting from the form config, the upper estimate next to the submit button, and notices that the run uses the configured LLM, is billed, and may take minutes to hours.
- Produces `SeoRunProgress.svelte` rendering the six named stages («Анализ сайта», «Поиск конкурентов», «Генерация запросов», «Проверки в ИИ и Поиске», «Анализ результатов», «Отчёт») with counters, actual `K` and `K × M`, per-source partial errors, and a cancel action.
- The home page starts an analysis through `POST /api/seo/analyses`, polls the snapshot every 30 seconds while it is active, stops on terminal states, recovers an active analysis found on the first history page after a reload, and no longer renders the old brand-check form or its results.

- [ ] **Step 1: Write failing `seo-form.test.ts` cases** for valid and invalid inputs, duplicate key queries, missing services, connection bounds, estimates before generation with `M` connections, and actual estimates after `K` is known.
- [ ] **Step 2: Implement `seo-form.ts`** and confirm `cd frontend && npx vitest run src/lib/seo-form.test.ts` passes.
- [ ] **Step 3: Write failing `SeoForm.test.ts` cases** for field rendering, default connection selection, disabled submit states, estimate text, and the LLM and billing notices.
- [ ] **Step 4: Implement `SeoForm.svelte`** with accessible labels and error messages.
- [ ] **Step 5: Write failing `SeoRunProgress.test.ts` cases** for pending, running, done, error, and cancelled stages, counters, partial errors, actual estimates, and the cancel action.
- [ ] **Step 6: Implement `SeoRunProgress.svelte`** and confirm its focused tests pass.
- [ ] **Step 7: Rewire `+page.svelte` and `+page.server.ts`** to the SEO form and run screen, keep polling and reload recovery, and stop rendering the old form and results.
- [ ] **Step 8: Run `cd frontend && npm run check && npx vitest run && npm run build`.**
- [ ] **Step 9: Commit** the SEO form, run screen, page rewiring, and tests.

### Task 9: SEO report, history, documentation, and end-to-end verification

**Files:**
- Create: `frontend/src/lib/components/SeoReport.svelte`
- Create: `frontend/src/lib/components/SeoReport.test.ts`
- Create: `frontend/src/lib/components/SeoHistory.svelte`
- Create: `frontend/src/lib/components/SeoHistory.test.ts`
- Modify: `frontend/src/routes/+page.svelte`
- Modify: `frontend/src/lib/types.ts` only if report projections need refinement
- Modify: `README.md`
- Modify: `backend/README.md`
- Create: `qa/pages/seo.py`
- Create: `qa/tests/test_seo.py`
- Test: `frontend/src/lib/components/SeoReport.test.ts`

**Interfaces:**
- Produces `SeoReport.svelte` with the site and competitor Yandex shares, average positions, per-connection name/domain/combined AI shares, category and service breakdowns, branded/unbranded splits, the candidate list with evidence and titles, the paginated detail rows with saved model answers, and `—` for every empty denominator or never-found position.
- Produces `SeoHistory.svelte` with newest-first entries, status, open, and delete for terminal states, a «Показать ещё» cursor action, and an empty state.
- The report and history render only from saved data; opening a saved analysis never triggers external calls.

- [ ] **Step 1: Write failing `SeoReport.test.ts` cases** for site aggregates, competitor aggregates, per-connection shares, category and service sections, branded versus unbranded rows, candidate evidence with titles, `—` rendering, detail pagination, and saved answer display.
- [ ] **Step 2: Implement `SeoReport.svelte`** and confirm its focused test passes.
- [ ] **Step 3: Write failing `SeoHistory.test.ts` cases** for list rendering, cursor loading, opening a saved report, delete availability per status, and the empty state.
- [ ] **Step 4: Implement `SeoHistory.svelte`**, then wire report and history into `+page.svelte` so a saved analysis opens without new external calls.
- [ ] **Step 5: Add the Playwright scenario** in `qa/tests/test_seo.py` with a page object in `qa/pages/seo.py`: fill the form, start an analysis against locally faked upstreams, observe the six stages, cancel a run, open the saved report, and delete it.
- [ ] **Step 6: Update `README.md` and `backend/README.md`** for the SEO scenario, the LLM settings, environment variables, the fixed 20-query limit, the six stages, cancel and resume behavior, and the fact that old runs stay reachable only through their API routes.
- [ ] **Step 7: Run backend verification**: `cd backend && uv run pytest -q && uv run ruff check app tests`.
- [ ] **Step 8: Run frontend verification**: `cd frontend && npm run check && npx vitest run && npm run build`.
- [ ] **Step 9: Run the browser scenario** against a locally started backend and frontend with faked upstreams and confirm the report, history, cancel, and delete flows.
- [ ] **Step 10: Review the full diff** for secret exposure, unchanged old routes and limits, `—` correctness, and absent paid calls in tests; then **Commit** the report, history, QA scenario, and documentation.
