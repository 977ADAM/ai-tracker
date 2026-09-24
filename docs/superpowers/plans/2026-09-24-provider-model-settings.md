# Provider and Model Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the reference-inspired settings modal where one custom provider owns multiple separately selectable models and one API key.

**Architecture:** The Python domain models provider groups and their models; a settings service coordinates validation, metadata persistence, and key storage. Dedicated `/api/providers/settings` routes serve the modal, while the existing flat provider list and check request continue to address individual model IDs. SvelteKit proxies the settings resource and renders the modal without owning provider rules.

**Tech Stack:** Python 3.13, FastAPI, pytest, keyring, Svelte 5, SvelteKit 2, TypeScript, Tailwind CSS 4, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-24-provider-model-settings-design.md`

## Global Constraints

- Only custom OpenAI Chat Completions-compatible providers are offered in the modal; no General, Plugins, Agent presets, configuration-file, or catalog actions.
- Provider metadata stays in `providers.json`; keys stay in the OS credential store and never appear in metadata or read responses.
- Old single-model connection IDs remain valid as both migrated group and model IDs; the first successful write persists a versioned shape atomically.
- Every provider has at least one model. The model API ID and display name are separate fields.
- The main page selects model IDs individually; the existing limit is five selections and twenty prompts.
- The modal calls `/api/providers/settings` through the SvelteKit BFF. The flat `GET /api/providers` and `POST /api/check` remain for checking.
- Keep the rest of the application's visual language intact; use Russian copy in the modal.

## Review Focus

1. A legacy metadata record with malformed model data must raise a readable storage error and leave the original file and key untouched (Task 1 test).
2. A duplicate model ID across two groups must be rejected before a settings write (Task 2 test).
3. A failed metadata write after changing a key must restore the prior key (Task 1 test).
4. A check using a removed model ID must fail before any external API call (Task 3 test).
5. Closing the dialog with Escape must return focus to the settings opener (Task 5 browser test).

---

### Task 1: Provider groups, legacy migration, and secret persistence

**Files:**
- Create: `backend/app/domain/provider_groups.py`
- Modify: `backend/app/domain/models.py`
- Modify: `backend/app/db/connections.py`
- Test: `backend/tests/test_db_connections.py`
- Test: `backend/tests/test_domain_connections.py`

**Interfaces:**
- Produces: `ProviderModel(id: str, model: str, name: str)` and `ProviderGroup(id: str, name: str, endpoint: str, models: tuple[ProviderModel, ...], kind: str = "openai")`.
- Produces: `ConnectionRepository.groups() -> list[ProviderGroup]`, `group(group_id: str) -> ProviderGroup | None`, `save_group(group: ProviderGroup, api_key: str | None) -> None`, `delete_group(group_id: str) -> None`, and `group_key(group_id: str) -> str | None`.
- Preserves existing repository methods for legacy tests and compatibility callers; route them through one canonical group store rather than a second file format.

- [x] **Step 1: Write failing domain and repository tests.** Use an old `providers.json` entry `{ "custom": [{"id":"old","name":"Old","kind":"openai","endpoint":"https://api.example.com/chat/completions","model":"legacy-model"}], "presets":{} }`. Set fake secret `old -> secret`. Assert `groups()` returns one group with model ID `old`, model API ID `legacy-model`, and `group_key("old") == "secret"`. Add tests for a two-model round trip, malformed legacy model raising `StorageError` without file changes, and failed `_write` restoring the old secret.

  ```python
  group = repository.groups()[0]
  assert (group.id, group.models[0].id, group.models[0].model) == ("old", "old", "legacy-model")
  assert repository.group_key("old") == "secret"
  ```
- [x] **Step 2: Run `cd backend && uv run pytest tests/test_db_connections.py tests/test_domain_connections.py -q`.** Confirm new tests fail because the group interfaces do not exist.
- [x] **Step 3: Implement immutable domain objects and canonical repository mapping.** Use a version marker in the new metadata shape; normalize old records in memory and write the new shape only on successful save/delete. Retain legacy IDs and keyring account names. Reuse the repository's temporary-file, fsync, `os.replace`, and secret rollback behavior. Reject malformed records rather than filtering them out during migration.
- [x] **Step 4: Run the two focused test files, then `cd backend && uv run pytest -q`.** Confirm all existing repository and preset tests still pass.
- [x] **Step 5: Commit the task files.** `git add backend/app/domain/provider_groups.py backend/app/domain/models.py backend/app/db/connections.py backend/tests/test_db_connections.py backend/tests/test_domain_connections.py && git commit -m 'feat: persist provider groups and migrate connections'`.

### Task 2: Settings service and dedicated Python API

**Files:**
- Create: `backend/app/service/provider_settings.py`
- Create: `backend/app/api/routers/provider_settings.py`
- Create: `backend/app/api/schemas/provider_settings.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/api/deps.py`
- Test: `backend/tests/test_service_connections.py`
- Test: `backend/tests/test_api_providers.py`

**Interfaces:**
- Consumes Task 1 repository group methods and domain objects.
- Produces: `ProviderSettingsService.list_public() -> list[dict]`, `save(payload: object, group_id: str | None = None) -> dict`, and `delete(group_id: str) -> None`.
- HTTP contracts: `GET, POST /api/providers/settings` and `PUT, DELETE /api/providers/settings/{group_id}`. A public group contains `id`, `name`, `endpoint`, `configured`, and `models: [{id, model, name}]`; no key field.

- [x] **Step 1: Write failing service and HTTP tests.** POST a group with two model rows, GET the settings list, PUT a renamed model with an empty key, and DELETE the group; assert the key is absent from every response and persists across the empty-key update. Test zero models, duplicate model IDs within a group and across groups, invalid endpoints, overlong names, and `/api/providers/settings` resolving to the static route instead of `/api/providers/{id}`.

  ```python
  response = client.post("/api/providers/settings", json={
      "name": "Demo", "endpoint": "https://api.example.com/chat/completions",
      "api_key": "secret", "models": [{"model": "model-a", "name": "A"}, {"model": "model-b", "name": "B"}],
  })
  assert response.status_code == 200
  assert "api_key" not in response.json()
  assert len(response.json()["models"]) == 2
  ```
- [x] **Step 2: Run `cd backend && uv run pytest tests/test_service_connections.py tests/test_api_providers.py -q`.** Confirm the new route/service assertions fail as expected.
- [x] **Step 3: Add pure validation in `domain/provider_groups.py` and orchestration in `service/provider_settings.py`.** Validate before calling `repository.save_group`. Keep FastAPI types in the router/schema files only. Wire the service through `api/deps.py` and mount the static settings router before the legacy dynamic provider router. Make delete remove the group and its key through the repository.
- [x] **Step 4: Run the focused tests and all backend tests.** `cd backend && uv run pytest -q` must have zero failures.
- [x] **Step 5: Commit the task files.** `git add backend/app/domain/provider_groups.py backend/app/service/provider_settings.py backend/app/api/routers/provider_settings.py backend/app/api/schemas/provider_settings.py backend/app/api/router.py backend/app/api/deps.py backend/tests/test_service_connections.py backend/tests/test_api_providers.py && git commit -m 'feat: expose provider settings resource'`.

### Task 3: Flat model choices and model-level checks

**Files:**
- Modify: `backend/app/service/connections.py`
- Modify: `backend/app/service/checks.py`
- Modify: `backend/app/domain/models.py`
- Modify: `backend/app/integrations/factory.py`
- Modify: `backend/app/api/schemas/providers.py`
- Test: `backend/tests/test_service_checks.py`
- Test: `backend/tests/test_api_checks.py`
- Test: `backend/tests/test_api_providers.py`

**Interfaces:**
- Consumes provider groups and models from Tasks 1–2.
- Preserves `GET /api/providers` as one public row per model and `POST /api/check` with `provider_ids: string[]`; each ID refers to a model.
- Produces a model-specific adapter configuration using the group's endpoint/key and the selected model's API identifier.

- [x] **Step 1: Write failing tests for two models sharing one provider key.** Assert both appear in `/api/providers` with distinct IDs and labels. Submit both IDs to `/api/check`; fake adapter calls must receive each model's API ID and the same group key. Assert an unknown or deleted model ID returns 400 before any adapter call, and one model failure leaves the other model's result intact.

  ```python
  choices = client.get("/api/providers").json()
  ids = [item["id"] for item in choices if item["name"].startswith("Demo")]
  assert len(ids) == 2 and len(set(ids)) == 2
  result = client.post("/api/check", json={"brand": "Demo", "prompts_text": "Where?", "provider_ids": ids})
  assert result.status_code == 200
  assert len(result.json()["checks"]) == 2
  ```
- [x] **Step 2: Run `cd backend && uv run pytest tests/test_service_checks.py tests/test_api_checks.py tests/test_api_providers.py -q`.** Confirm the new model-level assertions fail.
- [x] **Step 3: Implement model resolution in the service layer.** Build an ephemeral connection/adaptor configuration for each selected model from its owning group. Keep API keys server-side. Preserve existing report fields; use a distinct readable provider name per model. Keep preset compatibility tests green.
- [x] **Step 4: Run focused tests and `cd backend && uv run pytest -q`.** Confirm all backend tests pass.
- [x] **Step 5: Commit the task files.** `git add backend/app/service/connections.py backend/app/service/checks.py backend/app/domain/models.py backend/app/integrations/factory.py backend/app/api/schemas/providers.py backend/tests/test_service_checks.py backend/tests/test_api_checks.py backend/tests/test_api_providers.py && git commit -m 'feat: check individual models in provider groups'`.

### Task 4: SvelteKit settings BFF and public types

**Files:**
- Create: `frontend/src/routes/api/providers/settings/+server.ts`
- Create: `frontend/src/routes/api/providers/settings/[id]/+server.ts`
- Modify: `frontend/src/lib/server/python-api.ts`
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/routes/+layout.server.ts`
- Test: `frontend/src/lib/server/python-api.test.ts` (create if absent)

**Interfaces:**
- Consumes Task 2's exact Python settings paths and response shape.
- Produces SvelteKit JSON responses with only `id`, `name`, `endpoint`, `configured`, `models: [{id, model, name}]` for settings reads/writes.
- Supplies `settingsProviders` in layout data while keeping the flat `providers` for the check page.

- [x] **Step 1: Write failing BFF tests.** Exercise `GET/POST /api/providers/settings` and `PUT/DELETE /api/providers/settings/{id}` through the route handlers or shared proxy with a fake Python response. Assert secret fields are stripped, cross-origin writes return 403, oversized bodies return 413, invalid IDs return 400, and a non-JSON upstream response returns 502.

  ```typescript
  const projected = publicSettingsProvider({ id: 'group-1', name: 'Demo', endpoint: 'https://api.example.com/chat/completions', configured: true, models: [{ id: 'model-1', model: 'api-model', name: 'Demo model' }], api_key: 'secret' });
  expect(projected).not.toHaveProperty('api_key');
  expect(projected.models).toEqual([{ id: 'model-1', model: 'api-model', name: 'Demo model' }]);
  ```
- [x] **Step 2: Run `cd frontend && npx vitest run src/lib/server/python-api.test.ts`.** Confirm the new path/shape tests fail.
- [x] **Step 3: Extend the path allowlist and response projector.** Add a dedicated `publicSettingsProvider` projector, route methods, typed `SettingsProvider` and `SettingsModel`, and layout loading. Keep check-response projection unchanged and do not put business validation in TypeScript.
- [x] **Step 4: Run focused Vitest, `npm run check`, and `npm run build` in `frontend`.** Confirm zero errors.
- [x] **Step 5: Commit the task files.** `git add frontend/src/routes/api/providers/settings frontend/src/lib/server/python-api.ts frontend/src/lib/server/python-api.test.ts frontend/src/lib/types.ts frontend/src/routes/+layout.server.ts && git commit -m 'feat: proxy provider settings through SvelteKit'`.

### Task 5: Reference-inspired accessible modal

**Files:**
- Modify: `frontend/src/routes/+layout.svelte`
- Modify: `frontend/src/lib/components/SettingsPanel.svelte`
- Modify: `frontend/src/app.css` only if shared utility styles cannot express the design
- Test: `qa/pages/settings.py`
- Test: `qa/tests/test_add_provider.py`

**Interfaces:**
- Consumes Task 4's settings BFF and `SettingsProvider` type.
- Preserves the header button «Настройки API», dialog role/name, and a flat main-page model list.

- [x] **Step 1: Rewrite the QA page object for the new controls and add failing browser scenarios.** Cover one provider with two model rows, apply/cancel editing, key remaining hidden, model deletion, provider deletion, separate check options, Escape focus return, and `/settings` returning 404. Scope locators to the dialog and provider card.

  ```python
  settings_page.open().add_provider("Demo", "https://api.example.com/chat/completions", "secret")
  settings_page.add_model("Demo", api_id="model-b", display_name="Model B")
  settings_page.apply("Demo")
  expect(settings_page.page.get_by_role("checkbox", name="Demo · Model B")).to_be_visible()
  ```
- [x] **Step 2: Run isolated Python API and SvelteKit servers, then `cd qa && QA_HEADLESS=1 uv run pytest -q`.** Confirm the new UI scenarios fail for missing controls or behavior, not missing services.
- [x] **Step 3: Implement the modal shell and settings panel.** Use charcoal surfaces, rounded shell, a single active «Модели» rail item, provider cards, inset edit/create form, collapsed advanced settings, model rows, dashed add action, responsive single-column layout, and local status messages. Call only `/api/providers/settings`; invalidate layout/page data after writes. Keep the key input blank after reads and writes. Use Escape, backdrop, and close button; trap focus while open and restore focus on close.
- [x] **Step 4: Run `npm run check`, `npm run build`, and the full isolated QA suite.** Check the dialog at desktop and phone widths in a browser; fix overflow or inaccessible controls before proceeding.
- [x] **Step 5: Commit the task files.** `git add frontend/src/routes/+layout.svelte frontend/src/lib/components/SettingsPanel.svelte frontend/src/app.css qa/pages/settings.py qa/tests/test_add_provider.py && git commit -m 'feat: redesign provider model settings modal'`.

### Task 6: Documentation and end-to-end verification

**Files:**
- Modify: `backend/README.md`
- Modify: `qa/README.md`
- Modify: `qa/app.py` only if service probes need updating
- Test: `backend/tests/` and `qa/tests/` (run the full suites)

**Interfaces:**
- Documents the exact settings API paths, shared-key model behavior, migration, and QA workflow.

- [x] **Step 1: Update the two READMEs with a settings endpoint table and the model/group distinction.** Show `GET/POST /api/providers/settings`, `PUT/DELETE /api/providers/settings/{id}`, flat `/api/providers`, and model IDs in `/api/check`.
- [x] **Step 2: Run `cd backend && uv run pytest -q`, `cd frontend && npm run check && npm run build && npx vitest run`, and the full QA suite with isolated servers.** Record exact pass/fail counts; investigate any failure before claiming completion.
- [x] **Step 3: Inspect `git diff --check`, `git status --short`, and the route table.** Confirm only intended files changed, no key text is present in metadata or API responses, and `/settings` still answers 404.
- [x] **Step 4: Commit documentation.** `git add backend/README.md qa/README.md qa/app.py && git commit -m 'docs: describe provider model settings and checks'`.
