# Search Engine Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a «Поисковые системы» tab that manages Yandex availability and credentials, and make regional search honor those settings immediately.

**Architecture:** Store Yandex metadata in a dedicated local settings repository and the API key in the existing `SecretStore`. Resolve UI overrides before environment fallbacks, expose a safe settings API through FastAPI and the SvelteKit BFF, and let each new search job capture its gateway/configuration while existing jobs keep theirs.

**Tech Stack:** Python 3.13+, FastAPI, Pydantic, SQLite-independent JSON settings, keyring, SvelteKit 2, Svelte 5, TypeScript, pytest, Vitest, Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-28-search-engine-settings-design.md`

**Working tree note:** The checkout already contains uncommitted `region_targets` backend changes from the preceding request. Preserve them; Task 2 extends the same backend search files.

## Global Constraints

- The first version manages Yandex only; Google and other search engines are out of scope.
- Yandex is enabled when the settings file or its `enabled` field is absent.
- The UI-saved API key and folder ID override their respective environment values; explicit environment variables continue to override `.env` values.
- The public API never returns the API key; `api_key_source` and `folder_id_source` independently use `ui`, `env`, or `none`.
- `PUT /api/search/settings` accepts only optional `enabled` (boolean), `api_key` (string), and `folder_id` (string); omitted or empty credential fields are unchanged, while `null` and unknown fields are rejected.
- `DELETE /api/search/settings/credentials` resets both UI credential overrides together, is a successful no-op when neither exists, preserves `enabled`, and returns HTTP 200 with the public settings object.
- Existing `region_targets` payloads and legacy Yandex environment variable names remain supported.
- New settings affect new search jobs immediately; active jobs keep their starting configuration.

## Review Focus

- Missing config file or missing `enabled` must resolve to enabled Yandex, and legacy `YANDEX_*` and `API_KEY`/`FOLDER_ID` environment values must retain their precedence — test in Task 1.
- Mixed credential sources and missing environment values must report separate sources and safe null/false fields — test in Task 1.
- Partial updates, empty values, `null`, unknown fields, reset-all, and reset no-op must follow the exact contract — test in Task 2.
- Disabling Yandex must block new direct and combined search requests while preserving model-only runs — test in Tasks 2 and 5.
- Changing credentials during an active job must not switch that job to a different gateway — test in Task 2.

---

### Task 1: Search settings domain and persistence

**Files:**
- Create: `backend/app/domain/search_settings.py`
- Create: `backend/app/db/search_settings.py`
- Test: `backend/tests/test_search_settings.py`
- Test: `backend/tests/test_db_search_settings.py`

**Interfaces:**
- Produces `SearchSettings` as the resolved immutable settings value with `enabled: bool`, internal `api_key: str | None`, `folder_id: str | None`, `api_key_source: Literal["ui", "env", "none"]`, and `folder_id_source: Literal["ui", "env", "none"]`.
- Produces `SearchSettingsRepository(config_dir: Path, secrets: SecretStore, *, env_api_key: str | None, env_folder_id: str | None, service_name: str)` with `load() -> SearchSettings`, `update(payload: Mapping[str, object]) -> SearchSettings`, and `reset_credentials() -> SearchSettings`.
- `load()` resolves UI values over environment values and resolves absent `enabled` as `True`. Public projection is not part of the repository; callers must not serialize `api_key`.

- [ ] **Step 1: Write failing resolution tests** for absent file defaults, absent `enabled`, UI-over-env precedence, independent mixed sources, and absent values producing `api_key_source="none"`, `api_key=None`, and `folder_id=None`.
- [ ] **Step 2: Run the focused domain tests** with `cd backend && uv run pytest tests/test_search_settings.py -q`; confirm failures are due to the missing settings model/resolver.
- [ ] **Step 3: Implement the immutable settings value and source resolution** in `backend/app/domain/search_settings.py`, including public-safe fields derivable without exposing `api_key`.
- [ ] **Step 4: Write failing repository tests** for atomic metadata persistence, restrictive file permissions, keyring storage (key absent from JSON), keyring/metadata rollback on failed writes, partial update, and reset of both overrides including no-op.
- [ ] **Step 5: Run the repository tests** with `cd backend && uv run pytest tests/test_db_search_settings.py -q`; confirm they fail on missing repository behavior.
- [ ] **Step 6: Implement `SearchSettingsRepository`** in `backend/app/db/search_settings.py`; persist only `enabled` and `folder_id`, store the API key under a dedicated keyring account, preserve omitted/empty credential fields, and remove both user overrides in `reset_credentials()`.
- [ ] **Step 7: Run both focused test files** and confirm all default, precedence, permission, secret, update, and reset cases pass.
- [ ] **Step 8: Commit** the domain, repository, and tests.

### Task 2: Runtime configuration and FastAPI resource

**Files:**
- Modify: `backend/app/service/search.py`
- Modify: `backend/app/api/deps.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/core/errors.py` only if a distinct safe disabled-engine error is needed
- Create: `backend/app/service/search_settings.py`
- Create: `backend/app/api/schemas/search_settings.py`
- Create: `backend/app/api/routers/search_settings.py`
- Test: `backend/tests/test_service_search_settings.py`
- Test: `backend/tests/test_api_search_settings.py`
- Test: `backend/tests/test_api_runs.py`
- Test: `backend/tests/test_service_search.py`

**Interfaces:**
- Consumes `SearchSettings` and `SearchSettingsRepository` from Task 1.
- Produces `SearchSettingsService.public() -> dict[str, object]`, `.update(payload: Mapping[str, object]) -> dict[str, object]`, and `.reset_credentials() -> dict[str, object]`.
- Public response shape is exactly `{"yandex": {"enabled": bool, "folder_id": str | None, "has_api_key": bool, "api_key_source": "ui" | "env" | "none", "folder_id_source": "ui" | "env" | "none"}}`.
- FastAPI routes are `GET/PUT /api/search/settings` and `DELETE /api/search/settings/credentials`; DELETE returns 200 and the same public response shape.
- `SearchService.configure(gateway: SearchGateway | None, enabled: bool)` changes the config for new jobs. `start()` captures the current gateway for its background job, and rejects a disabled engine before submitting any request.

- [ ] **Step 1: Write failing service tests** for public projection (including mixed source and no-env cases), partial update, key preservation on empty input, reset of both overrides, and successful reset no-op.
- [ ] **Step 2: Run the focused service tests** with `cd backend && uv run pytest tests/test_service_search_settings.py -q`; confirm failures are feature-related.
- [ ] **Step 3: Implement `SearchSettingsService`** with a Yandex gateway factory backed by the shared `httpx.AsyncClient`; reconfigure `SearchService` after successful persistence and return only the public projection.
- [ ] **Step 4: Write failing runtime tests** proving disabled Yandex submits zero upstream requests, enabled legacy requests still work, and a job started before reconfiguration uses its original gateway.
- [ ] **Step 5: Implement per-job gateway capture and enabled checks** in `SearchService`; keep the current missing-credentials error when Yandex is enabled but no gateway exists.
- [ ] **Step 6: Write failing FastAPI tests** for exact GET response fields, partial PUT with only `enabled`, rejection of `null`/unknown fields, DELETE reset-all, DELETE no-op, and safe response bodies with mixed/no environment sources.
- [ ] **Step 7: Write a failing combined-run test** in `test_api_runs.py`: disable Yandex, start a run with both a provider and a region, verify no search request is submitted, and verify the model branch still completes.
- [ ] **Step 8: Implement strict request/response schemas and the GET/PUT/DELETE route handlers**; register settings routes before the dynamic search-job route.
- [ ] **Step 9: Wire the repository and service into `build_container()`**; retain a reusable production HTTP client before credentials are configured so saving credentials takes effect without restart.
- [ ] **Step 10: Run focused backend settings, search-service, and API tests**; then run `cd backend && uv run pytest -q && uv run ruff check app tests`.
- [ ] **Step 11: Commit** the backend runtime, API, and tests.

### Task 3: SvelteKit BFF and server-loaded settings

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/server/python-api.ts`
- Modify: `frontend/src/lib/server/python-api.test.ts`
- Modify: `frontend/src/routes/+layout.server.ts`
- Create: `frontend/src/routes/api/search/settings/+server.ts`
- Create: `frontend/src/routes/api/search/settings/credentials/+server.ts`

**Interfaces:**
- Produces `YandexSearchSettings` with `enabled`, `folder_id`, `has_api_key`, `api_key_source`, and `folder_id_source` typed to the exact values from the spec.
- `loadPageData()` returns `searchSettings: YandexSearchSettings | null` plus a safe `searchSettingsError`; a search-settings load failure must not prevent the existing model settings/form data from loading.
- BFF allows GET/PUT for `/api/search/settings`, DELETE for `/api/search/settings/credentials`, validates/project responses, and never forwards or returns an API key from GET.

- [ ] **Step 1: Write failing `python-api.test.ts` cases** for valid/invalid public settings payloads, rejection of a returned `api_key`, GET/PUT proxying, DELETE with no body, origin checks, and safe upstream failures.
- [ ] **Step 2: Run the focused frontend BFF tests** with `cd frontend && npx vitest run src/lib/server/python-api.test.ts`; confirm new contracts fail.
- [ ] **Step 3: Implement the settings types and public projector** in `types.ts` and `python-api.ts`; add exact allowed paths and dispatch before generic `/api/search/{id}` handling.
- [ ] **Step 4: Add SvelteKit route handlers** for settings GET/PUT and credentials DELETE, using existing `proxyJson` request protections.
- [ ] **Step 5: Extend `loadPageData()`** to load settings independently and include its safe error state; update `+layout.server.ts` data typing only where required.
- [ ] **Step 6: Run focused BFF tests and `cd frontend && npm run check`**; confirm settings failures do not erase the model configuration response.
- [ ] **Step 7: Commit** the BFF, loader, types, and tests.

### Task 4: Settings modal navigation and Yandex settings panel

**Files:**
- Modify: `frontend/src/routes/+layout.svelte`
- Create: `frontend/src/lib/components/SearchSettingsPanel.svelte`
- Create: `frontend/src/lib/components/SearchSettingsPanel.test.ts`
- Test: `frontend/src/routes/+layout.test.ts`
- Modify: `frontend/src/app.css` only if shared modal styles need a small adjustment

**Interfaces:**
- `SearchSettingsPanel` receives the public settings, safe load error, and save/reset callbacks (or uses the established same-origin BFF fetch pattern); it never receives an API key value.
- Modal navigation exposes keyboard-accessible «Модели» and «Поисковые системы» tabs; «Модели» remains the initial tab.

- [ ] **Step 1: Write failing panel tests** for enabled state, folder ID, key-presence/source indicators without key disclosure, saving `enabled` alone, saving changed nonempty credentials, empty key preserving the stored key, and reset action.
- [ ] **Step 2: Run the panel tests** with `cd frontend && npx vitest run src/lib/components/SearchSettingsPanel.test.ts`; confirm the new component behavior fails.
- [ ] **Step 3: Implement `SearchSettingsPanel.svelte`** with the approved partial-update and reset semantics, safe status messaging, and disabled/busy/error states.
- [ ] **Step 4: Add tab navigation in `+layout.svelte`** and render the new panel when its tab is selected while leaving the existing model panel intact.
- [ ] **Step 5: Add a layout interaction test** proving both tabs are reachable, the default is «Модели», and activating «Поисковые системы» displays the Yandex panel.
- [ ] **Step 6: Run panel/layout tests and `cd frontend && npm run check`**.
- [ ] **Step 7: Commit** the modal, panel, and tests.

### Task 5: Regional form integration and end-to-end verification

**Files:**
- Modify: `frontend/src/routes/+page.svelte`
- Modify: `frontend/src/lib/search-form.ts`
- Modify: `frontend/src/lib/search-form.test.ts`
- Modify: `frontend/src/lib/types.ts` if run/search response types need the current `engine` field
- Test: `frontend/src/routes/+page.test.ts` (create if needed for region form behavior)
- Modify: `README.md` and `backend/README.md` only for user-facing setup/settings documentation

**Interfaces:**
- The page consumes `searchSettings` from `loadPageData()` and offers only enabled engines in the region form.
- When Yandex is disabled, the user can still submit model-only runs; no disabled Yandex target is sent to the backend.
- Saving settings from the modal refreshes layout/page data without a full page reload.

- [ ] **Step 1: Write failing form tests** proving enabled Yandex remains selectable by default, disabled Yandex is unavailable, and model-only validation/submission remains possible when search is disabled.
- [ ] **Step 2: Run focused form/page tests** and confirm the disabled-engine cases fail before implementation.
- [ ] **Step 3: Update `+page.svelte` and `search-form.ts`** to render/select only enabled search engines, suppress stale disabled targets from requests, and keep region/request counts consistent.
- [ ] **Step 4: Wire modal save/reset to refresh page data** and verify updated availability is reflected without a browser reload.
- [ ] **Step 5: Add/update documentation** for the settings tab, keyring storage, env fallbacks, and credential reset behavior.
- [ ] **Step 6: Run final verification**: `cd backend && uv run pytest -q && uv run ruff check app tests`, then `cd frontend && npm run check && npx vitest run && npm run build`.
- [ ] **Step 7: Review the full diff for secret exposure and compatibility**; confirm GET/BFF never contains the key and active search jobs retain their captured gateway.
- [ ] **Step 8: Commit** the form integration, docs, and tests.
