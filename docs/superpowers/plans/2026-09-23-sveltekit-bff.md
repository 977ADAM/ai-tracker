# SvelteKit BFF Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SvelteKit 2/Svelte 5 with Tailwind CSS the local interface and BFF for the existing Python model-checking API.

**Architecture:** SvelteKit serves the two pages and same-origin JSON routes. Its server forwards only fixed API paths to the loopback FastAPI process, which remains the authority for model calls, validation, and keychain persistence. A small local runner starts both processes with one command.

**Tech Stack:** Node.js 20+, SvelteKit 2, Svelte 5, TypeScript, Tailwind CSS 4 with `@tailwindcss/vite`, `@sveltejs/adapter-node`, Vitest, Python 3.13, FastAPI, pytest.

**Spec:** `docs/superpowers/specs/2026-09-23-sveltekit-bff-design.md`

## Global Constraints

- Keep the existing `GET/POST /api/providers`, `PUT/DELETE /api/providers/{id}`, and `POST /api/check` Python contracts and provider behavior.
- Both servers bind to `127.0.0.1`; default Python origin is `http://127.0.0.1:8000`. `AI_TRACKER_API_URL` is server-only and must be a loopback HTTP origin.
- No browser request goes directly to Python; no API key is returned, logged, or stored by SvelteKit.
- A custom connection remains an OpenAI Chat Completions-compatible public HTTPS endpoint; Python remains authoritative for validation.
- Preserve GigaChat, DeepSeek, custom connections, 20 prompts, 1–5 selected providers, provider-specific failures, and point-in-time/API-answer wording.
- ChatGPT and Яндекс (Алиса AI) dedicated integrations are a later stage; this migration must keep provider-agnostic UI structure.
- `npm run dev` and `npm run start` launch both local services after installation/build; SvelteKit is the user entry point.
- Do not remove FastAPI's current pages/static files until the Svelte pages have equivalent functionality and browser verification passes.

## Review Focus

- A malicious connection ID such as `../check` must not change the upstream path; Task 2 tests fixed-route construction and encoded IDs.
- An unavailable or non-JSON Python API must produce a readable 502 without echoing sensitive request data; Task 2 tests both cases.
- An oversized body or cross-origin mutation must be rejected before contacting Python; Task 2 tests the guard.
- A stored key must not appear in list/check responses or reappear in the settings form; Tasks 2 and 4 test this.
- Provider names and answers containing HTML must render as literal text, and one provider's failure must not erase another's group; Tasks 3 and 4 test these states.

## File Map

- `package.json`, `package-lock.json`, `svelte.config.js`, `vite.config.ts`, `tsconfig.json`, `src/app.html`, `src/app.css`: SvelteKit, Tailwind, scripts, and build configuration.
- `scripts/run-local.mjs`: starts/stops Python and SvelteKit for development and built mode.
- `src/lib/server/python-api.ts`: fixed loopback upstream URL, request/response forwarding, safe errors, response projection.
- `src/lib/types.ts`: public provider, check request, and grouped result types shared by pages; `ApiPath` is `'/api/providers' | '/api/check' | \`/api/providers/${string}\`` and is also checked at runtime.
- `src/routes/api/providers/+server.ts`, `src/routes/api/providers/[id]/+server.ts`, `src/routes/api/check/+server.ts`: browser-facing BFF routes.
- `src/routes/+layout.svelte`, `src/routes/+page.server.ts`, `src/routes/+page.svelte`: shared shell and check page.
- `src/routes/settings/+page.server.ts`, `src/routes/settings/+page.svelte`: settings page.
- `src/ai_tracker/web.py`: retain JSON API, remove old page/static routes after parity.
- `tests/test_page.py`: remove obsolete Python page assertions; retain Python API tests in `tests/test_web.py`.
- `src/lib/server/python-api.test.ts`, `src/routes/api/routes.test.ts`, `src/routes/pages.test.ts`, `scripts/run-local.test.mjs`: frontend tests.
- `README.md`, `.gitignore`: local startup, BFF data path, generated file exclusions.

### Task 1: SvelteKit shell and local runner

**Files:** Create the root Node/Svelte configuration, `src/app.html`, `src/app.css`, `src/routes/+layout.svelte`, an initial `src/routes/+page.svelte` shell, `scripts/run-local.mjs`, `scripts/run-local.test.mjs`; update `.gitignore`.

**Interfaces:** `scripts/run-local.mjs` exports `commands(mode)` returning the Python and Node child commands, and runs them when executed directly. `npm run dev` starts Python plus Vite; `npm run start` starts Python plus the built Node adapter.

- [ ] **Step 1: Write a failing runner test** with `node:test` that checks the command selection and loopback binding. Include a spawned-child test with stub executables that verifies terminating the runner stops both children:

```js
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { commands } from './run-local.mjs';

test('dev binds both processes to loopback', () => {
  const [python, web] = commands('dev');
  assert.deepEqual(python.args, ['run', 'ai-tracker']);
  assert.match(web.args.join(' '), /127\.0\.0\.1/);
});
```

- [ ] **Step 2: Run** `node --test scripts/run-local.test.mjs`; expect the missing-module failure.
- [ ] **Step 3: Add minimal SvelteKit 2/Svelte 5, TypeScript, adapter-node, Tailwind 4 Vite plugin, Vitest, and svelte-check configuration.** Use the current compatible package releases within these major versions and commit the lockfile. `vite.config.ts` must include both `tailwindcss()` and `sveltekit()`. `src/app.css` imports Tailwind; `+layout.svelte` imports that CSS and renders `children` via Svelte 5 props. The initial `+page.svelte` renders the app title so the root route works before Task 3. `package.json` scripts include `dev`, `build`, `start`, `check`, and `test`:

```ts
import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({ plugins: [tailwindcss(), sveltekit()] });
```

- [ ] **Step 4: Implement `commands(mode)` and process supervision** using `spawn(..., {stdio: 'inherit'})`, `process.execPath` for Vite/adapter-node, `HOST=127.0.0.1` for the adapter, and an interrupt handler that signals both children. The Python command is `uv run ai-tracker`; Vite is launched with `--host 127.0.0.1`. Report missing `uv` or occupied ports and exit nonzero:

```js
export function commands(mode) {
  const python = { command: 'uv', args: ['run', 'ai-tracker'] };
  const web = mode === 'dev'
    ? { command: process.execPath, args: ['node_modules/vite/bin/vite.js', 'dev', '--host', '127.0.0.1'] }
    : { command: process.execPath, args: ['build/index.js'] };
  return [python, web];
}
```

- [ ] **Step 5: Run** `node --test scripts/run-local.test.mjs`, `npm run check`, and `npm run build`; expect success. Also run `uv run --with pytest pytest -q` for the unchanged Python baseline.
- [ ] **Step 6: Commit** as `feat: scaffold SvelteKit local runtime`.

### Task 2: Server-only Python API bridge and BFF routes

**Files:** Create `src/lib/server/python-api.ts`, `src/lib/types.ts`, the three BFF route files and their tests.

**Interfaces:** `ApiPath` is `'/api/providers' | '/api/check' | \`/api/providers/${string}\`` with runtime validation of IDs. `pythonApi(path: ApiPath, init?: RequestInit): Promise<Response>` uses `AI_TRACKER_API_URL`. `proxyJson(request: Request, path: ApiPath, method: string): Promise<Response>` validates same-origin writes, requires JSON on POST/PUT and an empty body on DELETE, enforces a 64 KiB body limit, calls Python, and returns safe JSON. `publicProvider(value)` projects only `id,name,kind,endpoint,model,scope,configured`; `publicCheck(value)` projects the agreed grouped response fields.

- [ ] **Step 1: Write failing tests** with a fake `fetch` for a valid list, create/update/delete/check forwarding, upstream status propagation, timeout/network failure and non-JSON 502, oversized JSON, wrong content type, wrong Origin, and `../check` as an ID. Set `AI_TRACKER_API_URL=https://example.com` in one test and assert it fails before fetch. Assert fake upstream never receives an arbitrary browser URL or request rejected by guards:

```ts
it('rejects a cross-origin key update before Python is called', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'));
  const response = await proxyJson(new Request('http://127.0.0.1:5173/api/providers/deepseek', {
    method: 'PUT', headers: { origin: 'https://other.example', 'content-type': 'application/json' },
    body: JSON.stringify({ api_key: 'secret' })
  }), '/api/providers/deepseek', 'PUT');
  expect(response.status).toBe(403);
  expect(fetchMock).not.toHaveBeenCalled();
  fetchMock.mockRestore();
});
```

- [ ] **Step 2: Run** `npm test -- src/lib/server/python-api.test.ts src/routes/api/routes.test.ts`; expect missing-module failures.
- [ ] **Step 3: Implement the server-only bridge.** Parse `AI_TRACKER_API_URL` with `URL`; require `http:`, hostname exactly `127.0.0.1` or `localhost`, and no credentials/path (except `/`), query, or fragment. Build Python paths from a closed set (`/api/providers`, `/api/check`, `/api/providers/${encodeURIComponent(id)}`) and reject IDs containing `/`, `\\`, `.` segments, or controls. Never copy browser-provided `Host`/`Authorization` headers. Catch fetch errors and return `{detail:'Python API недоступен'}` with 502. Reject non-JSON upstream. Project public provider fields from successful list/create/update responses; similarly project check responses to `brand,domain,checks` with each group limited to `provider_id,provider_name,summary,results` and each result limited to `prompt,answer,mentioned,error`:

```ts
const allowed = ['id', 'name', 'kind', 'endpoint', 'model', 'scope', 'configured'] as const;
export function publicProvider(value: Record<string, unknown>) {
  return Object.fromEntries(allowed.filter((key) => key in value).map((key) => [key, value[key]]));
}
```

- [ ] **Step 4: Implement `+server.ts` methods** that call the shared bridge. GET list and DELETE do not forward a body. POST/PUT/check require JSON. All use fixed methods and route IDs. Preserve upstream 400/503 details and grouped check shape. Check `Content-Length` when present and actual UTF-8 byte length after read; cap at 64 KiB. Keep no generic short timeout on `/api/check` so a legitimate 100-call sequential run is not cut off:

```ts
// src/routes/api/check/+server.ts
import type { RequestHandler } from './$types';
import { proxyJson } from '$lib/server/python-api';
export const POST: RequestHandler = ({ request }) => proxyJson(request, '/api/check', 'POST');
```
- [ ] **Step 5: Run** the focused Vitest suite and `npm run check`; confirm all assertions pass, then commit as `feat: add SvelteKit Python API bridge`.

### Task 3: Check page and grouped report

**Files:** Create `src/routes/+page.server.ts`, `src/routes/+page.svelte`, `src/routes/pages.test.ts`; expand `src/app.css` with only small theme/base rules while layout and page use Tailwind utilities.

**Interfaces:** Server load gets public providers via the bridge. The page submits `{brand, domain, prompts, provider_ids}` to same-origin `/api/check` and consumes `{brand,domain,checks}`. Use Svelte 5 `$state` and `$derived`; model-facing strings render via escaped `{value}` interpolation.

- [ ] **Step 1: Write failing component tests** with a fake provider load and mocked same-origin fetch: keyless providers cannot be selected; one selected provider sends its ID; two groups show separate counts; partial failure shows an error badge and does not count as a missed mention; `<script>alert(1)</script>` in an answer appears as text with no inserted script element; >20 prompts blocks submission; an initial Python API outage shows a readable setup error rather than an empty page:

```ts
import { render } from '@testing-library/svelte';
import CheckPage from './+page.svelte';

const view = render(CheckPage, { data: { providers: [{ id: 'deepseek', name: 'DeepSeek', configured: false, kind: 'openai', endpoint: 'https://api.deepseek.com/chat/completions', model: 'deepseek-flash' }] } });
expect(view.getByLabelText(/DeepSeek/).hasAttribute('disabled')).toBe(true);
```
- [ ] **Step 2: Run** `npm test -- src/routes/pages.test.ts`; expect missing-page failures.
- [ ] **Step 3: Implement layout and check page** with provider cards, brand/domain fields, newline prompt input and count, 1–5 selection validation, loading/empty/error states, and grouped summary/answer cards. Keep the Russian copy that says the result is a point-in-time API answer and does not check citations/search. Use `bind:value`, `onclick`, `$state`, `$derived`, and `{#each}`; never `{@html}` for API content:

```svelte
<script lang="ts">
  let brand = $state('');
  let promptsText = $state('');
  let prompts = $derived(promptsText.split(/\r?\n/).map((p) => p.trim()).filter(Boolean));
</script>
<p>Вопросов: {prompts.length} / 20</p>
```

- [ ] **Step 4: Run** focused frontend tests, `npm run check`, `npm run build`, and the Python suite. Commit as `feat: build Svelte check page`.

### Task 4: Connection settings page

**Files:** Create `src/routes/settings/+page.server.ts`, `src/routes/settings/+page.svelte`; extend `src/routes/pages.test.ts`.

**Interfaces:** Server load gets the public provider list. Browser writes through SvelteKit `/api/providers` routes, then refreshes list through the same origin. Built-ins edit only `api_key` and GigaChat `scope`; custom connections edit name/endpoint/model/key. A blank edit key leaves the Python-stored key unchanged.

- [ ] **Step 1: Write failing page tests** for preset/custom cards, configured status, built-in edit fields locked, blank key on edit, new custom provider payload, custom delete, preset key reset, failed save message, and a saved key never rendered in the form or HTML. Include a provider name with `<img onerror=...>` and assert it is escaped:

```ts
import { render } from '@testing-library/svelte';
import SettingsPage from './settings/+page.svelte';

const view = render(SettingsPage, { data: { providers: [{ id: 'gigachat', name: '<img onerror=alert(1)>', configured: true, kind: 'gigachat', endpoint: null, model: 'GigaChat', scope: 'GIGACHAT_API_PERS' }] } });
expect(view.container.querySelector('img')).toBeNull();
expect(view.getByText('<img onerror=alert(1)>')).toBeTruthy();
```
- [ ] **Step 2: Run** `npm test -- src/routes/pages.test.ts`; expect settings-page failures.
- [ ] **Step 3: Implement settings page** using Tailwind utilities and native form controls. Key input is `type=password` with an empty value whenever an edit opens. State whether the key goes to the displayed API endpoint, that stored keys are not shown again, and that an environment key can keep a preset active after reset. Use `encodeURIComponent(connection.id)` in BFF route URLs and Svelte text interpolation for all provider metadata:

```svelte
<input type="password" autocomplete="new-password" bind:value={apiKey} />
<button type="button" onclick={() => { apiKey = ''; editing = connection.id; }}>Настроить</button>
```

- [ ] **Step 4: Run** focused frontend tests, `npm run check`, `npm run build`, and Python suite. Commit as `feat: build Svelte connection settings`.

### Task 5: Migration cleanup, startup, and browser verification

**Files:** Modify `src/ai_tracker/web.py`, `README.md`, `.gitignore`; remove obsolete `src/ai_tracker/static/*` and `tests/test_page.py`; adjust `tests/test_web.py` only where page removal affects API tests.

**Interfaces:** FastAPI serves only `/api/*`; SvelteKit serves `/`, `/settings`, and same-origin `/api/*`. `npm run dev` and `npm run start` are supported local entry points.

- [ ] **Step 1: Write a failing Python test** that `GET /` and `GET /settings` are absent from FastAPI while `GET /api/providers` and `POST /api/check` remain. Run focused tests and confirm the old pages still respond; the child cleanup test is already owned by Task 1:

```python
from fastapi.testclient import TestClient
from ai_tracker.web import create_app

def test_python_app_exposes_api_only():
    client = TestClient(create_app(allowed_hosts=["testserver"]))
    assert client.get("/").status_code == 404
    assert client.get("/settings").status_code == 404
    assert client.get("/api/providers").status_code == 200
```
- [ ] **Step 2: Remove FastAPI's page/static routes and old assets**, leaving trusted-host protection and JSON endpoints intact. Update README with Node/Python requirements, `uv sync`, `npm install`, `npm run dev`, `npm run build`, `npm run start`, two loopback ports, keychain ownership, and the BFF data path. Add `.svelte-kit/`, `node_modules/`, `.vite/`, and `build/` as generated exclusions:

```python
application = FastAPI(title="ИИ-трекинг API")
application.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])
# Register only /api/* routes below.
```

- [ ] **Step 3: Run** `npm test`, `npm run check`, `npm run build`, `uv run --with pytest pytest -q`, and `git diff --check`. Start `npm run dev` with fake Python providers and inspect both pages at desktop and narrow width: keyless setup, GigaChat/DeepSeek groups, partial failure, hostile HTML literal. Start built mode with `npm run start` and check the same-origin BFF response. Ensure the browser's network requests go to SvelteKit only.
- [ ] **Step 4: Commit** as `feat: make SvelteKit the local entry point`.

## Final Verification

- [ ] Run all frontend and Python tests on the final tree and build the SvelteKit Node output and Python wheel.
- [ ] Inspect `git diff --check`, clean status, and branch diff against `main`.
- [ ] Check the UI and README against the spec. No live paid model call is needed without user keys.
- [ ] Request an independent branch review, fix actionable findings, and rerun affected checks.
