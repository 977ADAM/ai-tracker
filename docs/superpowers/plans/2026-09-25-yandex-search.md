# Deferred Yandex Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deferred Yandex search to the existing brand-check form and report whether the entered site appears in the first ten results for each question and selected region.

**Architecture:** Keep `/api/search` separate from `/api/check`. Pure domain rules validate requests and match hosts; an adapter handles Yandex HTTP/XML; a service owns short-lived in-memory jobs; FastAPI and the SvelteKit BFF expose safe snapshots. The frontend starts both branches independently and polls search status while the page remains open.

**Tech Stack:** Python 3.13, FastAPI, httpx, pytest; SvelteKit 2, Svelte 5, TypeScript, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-25-yandex-search-design.md`

## Global Constraints

- Yandex uses deferred Search API v2 (`/v2/web/searchAsync`), Russian search, XML, page 0, flat grouping, ten results, one document per group, and a top-level numeric region.
- A run has 1–20 questions of at most 400 characters when search is selected and 1–5 distinct regions: at most 100 paid search requests.
- With no search regions, the existing `/api/check` contract and 500-character question limit remain intact. Search-only runs are allowed.
- Target host and its subdomains match; lookalike suffixes do not. URL path, scheme, and port do not influence matching.
- Browser calls only SvelteKit routes; keys and Yandex operation IDs never reach the browser. No history, local storage, language selector, or device selector.
- Closing or reloading the page loses access to the job. Model and search errors remain independent. A failed search pair is not an absent site.
- Preserve the user's untracked `backend/app/api/routers/search.py` until the replacement route is ready; inspect it as a reference, and stage only files owned by each task.

## Review Focus

1. A target `example.ru` must match `www.example.ru` but not `example.ru.attacker.test`; pin this in Task 1's host-matching test.
2. A 401/error body containing a credential must produce only a safe error message; pin this in Task 2's adapter test and Task 4's API response test.
3. A 500-character prompt remains valid for model-only runs but fails before paid search submission; pin this in Task 1's validation test and Task 6's UI test.
4. When one Yandex pair fails, other pairs finish and the failure is not counted as absence; pin this in Task 3's service test and Task 6's rendering test.
5. A forged/expired job ID must not expose an operation or internal exception; pin this in Task 4's 404 test and Task 5's BFF path test.

---

## File map and interfaces

| File | Responsibility |
| --- | --- |
| `backend/app/domain/search.py` | `SearchInput`, `SearchDocument`, `SearchGateway` protocol, region catalog, `normalize_search_request`, `first_matching_result` |
| `backend/app/integrations/yandex_search.py` | `YandexSearchGateway.submit(prompt, region) -> str` and `.result(operation_id) -> tuple[SearchDocument, ...] | None` |
| `backend/app/service/search.py` | `SearchService.start(payload) -> dict`, `.snapshot(job_id) -> dict`, `.close() -> None`; in-memory job state and bounded background work |
| `backend/app/core/errors.py`, `backend/app/api/errors.py` | A safe `SearchJobNotFound` error mapped to HTTP 404 |
| `backend/app/api/schemas/search.py` | Pydantic request and public response schemas |
| `backend/app/api/routers/search.py` | Thin region, create, and snapshot routes, replacing the untracked monolith |
| `backend/app/core/config.py`, `backend/app/api/deps.py`, `backend/app/main.py` | Credential resolution, dependency wiring, task cleanup |
| `frontend/src/lib/server/python-api.ts` and new `frontend/src/routes/api/search/**/+server.ts` | BFF path allowlist, public projection, safe proxy, and region catalog loading |
| `frontend/src/lib/types.ts`, `frontend/src/routes/+page.svelte` | Region controls, conditional validation, independent reports, polling |
| `README.md`, `backend/README.md` | Setup, API and deferred-result behavior |

All Python paths below are relative to `backend/`; all frontend paths to `frontend/`. Run Python commands in `backend/` and frontend commands in `frontend/`.

### Task 1: Pure search rules and region catalog

**Files:** Create `backend/app/domain/search.py`, `backend/tests/test_domain_search.py`.

**Interfaces:** Produce `SearchInput(domain: str, host: str, prompts: tuple[str, ...], regions: tuple[int, ...])`, `SearchDocument(url: str)`, `SearchGateway` async protocol, `REGIONS: tuple[tuple[int, str], ...]`, `normalize_search_request(payload: object) -> SearchInput`, `first_matching_result(host: str, documents: Sequence[SearchDocument]) -> tuple[int, str] | None`.

- [ ] **Step 1: Write failing tests for request limits, catalog IDs, and matching.** Include exact host, `www`, another subdomain, lookalike suffix, malformed/non-HTTP URL, an unknown/duplicate region, 21 questions, 401 characters, and an input with 20 questions × 5 regions. Example assertions:

```python
def test_subdomains_match_but_lookalikes_do_not():
    docs = (SearchDocument('https://example.ru.attacker.test/x'),
            SearchDocument('https://shop.example.ru/p'))
    assert first_matching_result('example.ru', docs) == (2, 'https://shop.example.ru/p')

def test_search_rejects_a_401_character_question():
    with pytest.raises(ValidationError):
        normalize_search_request({'domain': 'example.ru', 'prompts_text': 'x' * 401, 'regions': [1]})
```

- [ ] **Step 2: Run `uv run pytest tests/test_domain_search.py -q`; confirm imports or assertions fail.**
- [ ] **Step 3: Implement the pure module.** Use `urlsplit`, `hostname`, IDNA normalization, and label-boundary suffix matching; reject credentials, malformed hosts, and protocols other than HTTP(S). Normalize newline-separated prompts like `domain/requests.py`. Use a unique documented numeric catalog; include `1` for «Москва и Московская область» and `213` for «Москва» ([Yandex regions](https://yandex.cloud/docs/search-api/reference/regions)). Keep the API maximum as constants `MAX_SEARCH_PROMPT_LENGTH = 400`, `MAX_REGIONS = 5`, `TOP_RESULTS = 10`.

```python
@dataclass(frozen=True)
class SearchDocument:
    url: str

class SearchGateway(Protocol):
    async def submit(self, prompt: str, region: int) -> str: ...
    async def result(self, operation_id: str) -> tuple[SearchDocument, ...] | None: ...

def first_matching_result(host: str, documents: Sequence[SearchDocument]) -> tuple[int, str] | None:
    for position, document in enumerate(documents[:TOP_RESULTS], start=1):
        result_host = result_url_host(document.url)
        if result_host and (result_host == host or result_host.endswith('.' + host)):
            return position, document.url
    return None
```

- [ ] **Step 4: Run `uv run pytest tests/test_domain_search.py -q` and `uv run ruff check app/domain/search.py tests/test_domain_search.py`; confirm pass.**
- [ ] **Step 5: Commit `backend/app/domain/search.py` and its test as `Add pure Yandex search rules`.**

### Task 2: Yandex deferred adapter

**Files:** Create `backend/app/integrations/yandex_search.py`, `backend/tests/test_integrations_yandex_search.py`.

**Interfaces:** Consume Task 1's `SearchDocument` and `SearchGateway`. Produce `YandexSearchGateway(api_key: str, folder_id: str, client: httpx.AsyncClient)` with async `submit` and `result`. Raise `ProviderError` with fixed safe messages for upstream failures.

- [ ] **Step 1: Write failing transport tests using `httpx.MockTransport`.** Assert that `submit('цветы', 1)` sends one `POST https://searchapi.api.cloud.yandex.net/v2/web/searchAsync` with `query.searchType = SEARCH_TYPE_RU`, `query.page = 0`, top-level `region = '1'`, `groupSpec = {'groupMode':'GROUP_MODE_FLAT','groupsOnPage':'10','docsInGroup':'1'}`, `responseFormat = FORMAT_XML`, and `Authorization: Api-Key ...`. Assert `result` returns `None` for `done: false`, parses ordered `<doc><url>...</url></doc>` elements from Base64 XML when done, and raises a safe `ProviderError` for an upstream `401` containing `secret-value`.

```python
async def test_upstream_error_does_not_echo_credentials():
    gateway = YandexSearchGateway('secret-value', 'folder', client)
    with pytest.raises(ProviderError) as raised:
        await gateway.submit('цветы', 1)
    assert 'secret-value' not in str(raised.value)
```

- [ ] **Step 2: Run `uv run pytest tests/test_integrations_yandex_search.py -q`; confirm failure.**
- [ ] **Step 3: Implement adapter and XML decoder.** Keep request formation and XML parsing in this file. `result` calls the fixed Operation API origin with an ID obtained from `submit`; validate that ID is a safe nonempty token before putting it in a path. Catch `httpx` failures, invalid JSON, bad Base64/XML, operation errors, and absent `response.rawData`; translate all to fixed Russian messages without raw response bodies or secrets. Parse only first-page document order; return at most ten `SearchDocument` values.

```python
async def result(self, operation_id: str) -> tuple[SearchDocument, ...] | None:
    response = await self.client.get(f'{OPERATIONS_URL}/{safe_operation_id(operation_id)}', headers=self.headers)
    operation = require_operation(response)
    if not operation.get('done'):
        return None
    if operation.get('error'):
        raise ProviderError('Поиск Яндекса завершился ошибкой')
    return parse_documents(decode_raw_data(operation['response']['rawData']))[:TOP_RESULTS]
```

- [ ] **Step 4: Run adapter tests and `uv run ruff check app/integrations/yandex_search.py tests/test_integrations_yandex_search.py`; confirm pass.**
- [ ] **Step 5: Commit adapter and tests as `Add deferred Yandex Search API adapter`.**

### Task 3: In-memory search jobs and independent pair results

**Files:** Create `backend/app/service/search.py`, `backend/tests/test_service_search.py`; modify `backend/app/core/errors.py`.

**Interfaces:** Consume Task 1's `SearchGateway`, `SearchInput`, `normalize_search_request`, and `first_matching_result`. Produce `SearchService(gateway: SearchGateway | None, *, poll_interval: float = 30.0, max_concurrency: int = 5)` with async `start(payload: object) -> dict`, sync `snapshot(job_id: str) -> dict`, and async `close() -> None`. Define `SearchJobNotFound(AppError)` in `core/errors.py`. The service owns an in-memory job store class and task registry. `None` gateway means missing credentials.

- [ ] **Step 1: Write failing async service tests with a fake gateway.** Fake `submit` returns opaque IDs and records prompt-region pairs; fake `result` returns `None` once, then documents or raises `ProviderError`. Test that `start` returns before any pair completes, jobs contain ordered results and counts, one failure does not erase a found pair, 20 × 5 produces 100 submits, unknown/expired IDs raise a service error mapped to 404, and `close` cancels pending tasks. Use `poll_interval=0` and `asyncio.Event` instead of real delays.

```python
job = await service.start({'domain': 'example.ru', 'prompts_text': 'цветы', 'regions': [1, 213]})
assert job['total'] == 2
assert service.snapshot(job['id'])['completed'] == 0
fake.ready.set()  # ready is an asyncio.Event held by the fake gateway
await asyncio.sleep(0)  # let the scheduled service task resume
final = service.snapshot(job['id'])
assert [item['status'] for item in final['results']] == ['found', 'error']
assert final['summary']['failed'] == 1
```

- [ ] **Step 2: Run `uv run pytest tests/test_service_search.py -q`; confirm failure.**
- [ ] **Step 3: Implement service and store.** Create each job's ordered pair rows synchronously in `start`, then launch one tracked background task to run them under an `asyncio.Semaphore(5)`. Keep storage behind an `InMemorySearchJobStore` in the same file, used only by `SearchService`. Use `secrets.token_urlsafe` for opaque IDs, 30-second poll intervals with bounded backoff, and snapshot copies rather than exposing mutable state. Statuses are `submitting`, `waiting`, `found`, `absent`, `error`. Count `successful`, `found`, `failed`, and `completed` without counting errors as absent. Expire jobs 24 hours after creation or one hour after completion, whichever comes first; cancel unfinished tasks on expiry/shutdown. Do not write to disk. Raise `SearchJobNotFound` from `snapshot` for missing/expired IDs. Catch expected adapter errors per pair and unexpected failures with a fixed safe message.

```python
async def _run_pair(self, job: SearchJob, index: int, prompt: str, region: int) -> None:
    try:
        async with self.semaphore:
            operation_id = await self.gateway.submit(prompt, region)
        job.rows[index].status = 'waiting'
        while True:
            async with self.semaphore:
                documents = await self.gateway.result(operation_id)
            if documents is not None:
                match = first_matching_result(job.host, documents)
                job.rows[index].finish(match)
                return
            await asyncio.sleep(self.poll_interval)
    except Exception:
        job.rows[index].fail('Не удалось получить выдачу Яндекса')
```

- [ ] **Step 4: Run `uv run pytest tests/test_service_search.py -q` and Ruff on both files; confirm pass.**
- [ ] **Step 5: Commit service, error type, and tests as `Track deferred Yandex search jobs in memory`.**

### Task 4: FastAPI contract, configuration, and lifecycle

**Files:** Create `backend/app/api/schemas/search.py`, `backend/tests/test_api_search.py`, `backend/tests/test_search_config.py`; replace `backend/app/api/routers/search.py`; modify `backend/app/core/config.py`, `backend/app/api/deps.py`, `backend/app/api/errors.py`, `backend/app/main.py`, `backend/tests/conftest.py`.

**Interfaces:** Consume `SearchService` from Task 3 and `YandexSearchGateway` from Task 2. Produce `GET /api/search/regions`, `POST /api/search`, and `GET /api/search/{job_id}`. Add `search_gateway: SearchGateway | None = None` injection to `build_container` for tests; add `Container.search: SearchService` and `SearchServiceDep`.

- [ ] **Step 1: Write failing API/config tests.** Assert 202 creation and immediate snapshot, 404 unknown ID, static `/regions` precedence over `/{job_id}`, 400 before any gateway call for duplicate/unknown regions and 401-character prompts, 400 for missing credentials, and absence of `api_key`, `folder_id`, Yandex operation IDs, and an upstream `secret-value` in every public response. Test prefixed environment names winning over legacy names and legacy fallback when prefixed names are absent. Use existing `make_client` fixture with injected gateway; do not access real Yandex.

```python
response = client.post('/api/search', json={
    'domain': 'example.ru', 'prompts_text': 'цветы', 'regions': [1],
})
assert response.status_code == 202
assert set(response.json()) == {'id', 'total', 'status'}
assert client.get('/api/search/regions').status_code == 200
assert client.get('/api/search/no-such-job').status_code == 404
```

- [ ] **Step 2: Run `uv run pytest tests/test_api_search.py tests/test_search_config.py -q`; confirm failure.**
- [ ] **Step 3: Move the monolithic route to thin schemas/routes and wire the service.** Put `GET /regions` before dynamic `GET /{job_id}`. `POST` uses `status_code=202`; schemas include only the public contract from the spec. Resolve credentials in `Settings.from_env`: `YANDEX_SEARCH_API_KEY` then `API_KEY`, `YANDEX_SEARCH_FOLDER_ID` then `FOLDER_ID`, ignoring empty values. Load root `.env` at app startup with `override=False` so explicit environment wins. Build the adapter with a shared `httpx.AsyncClient`; close jobs and client in the FastAPI lifespan. Inject a fake gateway in tests. Map `SearchJobNotFound` to 404 with one safe string in `api/errors.py`; keep existing error-handler behavior for other routes. Use `with TestClient(application, ...) as client` for background-task API tests so the lifespan and event loop stay alive across create/status requests.

```python
@router.get('/search/regions', response_model=list[SearchRegionResponse])
def regions() -> list[dict]:
    return [{'id': id, 'name': name} for id, name in REGIONS]

@router.post('/search', response_model=SearchCreatedResponse, status_code=202)
async def start_search(search: SearchServiceDep, payload: SearchRequest) -> dict:
    return await search.start(payload.model_dump())

@router.get('/search/{job_id}', response_model=SearchSnapshotResponse)
def search_status(search: SearchServiceDep, job_id: str) -> dict:
    return search.snapshot(job_id)
```

- [ ] **Step 4: Run `uv run pytest tests/test_api_search.py tests/test_search_config.py tests/test_main.py -q` and `uv run ruff check app tests/test_api_search.py tests/test_search_config.py`; confirm pass.**
- [ ] **Step 5: Commit only the owned backend files as `Expose deferred Yandex search API`.** At this point explicitly stage the previously untracked `backend/app/api/routers/search.py` replacement.

### Task 5: SvelteKit BFF routes and redaction

**Files:** Create `frontend/src/routes/api/search/+server.ts`, `frontend/src/routes/api/search/regions/+server.ts`, `frontend/src/routes/api/search/[id]/+server.ts`; modify `frontend/src/lib/server/python-api.ts`, `frontend/src/lib/server/python-api.test.ts`, `frontend/src/lib/types.ts`.

**Interfaces:** Consume Python's Task 4 JSON shapes. Produce `searchPath(id: string): ApiPath`, `publicSearchCreated`, `publicSearchRegions`, and `publicSearchSnapshot` in `python-api.ts`; export TypeScript `SearchCreated`, `SearchRegion`, `SearchSnapshot`, and `SearchRow`.

- [ ] **Step 1: Write failing Vitest tests.** Test that create returns only `id,total,status`, snapshots strip `operation_id`, `api_key`, and `folder_id` at top and nested row levels, region lists strip extra fields, malformed IDs such as `../providers` are rejected, forged/expired job responses stay 404, cross-origin POST is rejected before upstream fetch, and non-JSON upstream responses become safe 502 errors.

```ts
expect(publicSearchSnapshot({
  id: 'job-1', domain: 'example.ru', regions: [1], total: 1, completed: 1,
  summary: { successful: 1, found: 1, failed: 0 },
  results: [{ prompt: 'цветы', region_id: 1, region_name: 'Москва и Московская область',
    status: 'found', position: 2, url: 'https://shop.example.ru/x', error: null,
    operation_id: 'private' }], api_key: 'private'
}).results[0]).not.toHaveProperty('operation_id');
expect(() => searchPath('../check')).toThrow();
```

- [ ] **Step 2: Run `npx vitest run src/lib/server/python-api.test.ts`; confirm failure.**
- [ ] **Step 3: Add allowlisted BFF paths and projections.** Put exact static `/api/search/regions` before `/api/search/${id}` in `validPath`; use `^[A-Za-z0-9_-]{1,128}$` for opaque job IDs. Route files delegate only their allowed method to `proxyJson`. Extend `pythonApi` and `proxyJson` branches so `/api/search` POST returns `publicSearchCreated`, `/api/search/regions` GET returns `publicSearchRegions`, and `/api/search/{id}` GET returns `publicSearchSnapshot`; all other paths still reject. Extend `loadPageData()` with an independent region fetch that returns `searchRegions: SearchRegion[]` and `searchRegionError: string`, without turning a failed catalog request into the existing model-list `loadError`. Keep the existing body limit, same-origin checks, and loopback-only upstream origin.

```ts
export function searchPath(id: string): ApiPath {
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(id)) throw new Error('Invalid search ID');
  return `/api/search/${encodeURIComponent(id)}`;
}
// src/routes/api/search/[id]/+server.ts
export const GET: RequestHandler = ({ request, params }) =>
  proxyJson(request, searchPath(params.id), 'GET');
```

- [ ] **Step 4: Run `npx vitest run src/lib/server/python-api.test.ts`, `npm run check`, and `npm run build`; confirm pass.**
- [ ] **Step 5: Commit BFF files and tests as `Proxy Yandex search jobs through SvelteKit`.**

### Task 6: Region controls, independent results, and polling

**Files:** Modify `frontend/src/routes/+page.svelte`; create `frontend/src/lib/components/SearchReport.svelte`, `frontend/src/lib/components/SearchReport.test.ts`, `frontend/src/lib/search-form.test.ts`, `frontend/src/lib/search-form.ts`.

**Interfaces:** Consume Task 5's TypeScript types and BFF routes. `search-form.ts` produces `validateRun({brand, domain, promptsText, providerIds, regions}) -> string | null`, `requestCount(promptsText, regions) -> number`. `SearchReport` accepts `{snapshot: SearchSnapshot | null, error: string}`.

- [ ] **Step 1: Write failing form/report tests.** Cover zero regions by default, 1–5 distinct IDs, a required site only when regions are selected, 400-character search questions versus 500-character model-only questions, a search-only run with no model, 20 × 5 displaying 100 requests, and separate pending/found/absent/error rows. A failed row must not be rendered as «Сайт не найден». Use Svelte Testing Library for report rendering; use a focused Playwright test in Task 7 for the full page interaction.

```ts
expect(validateRun({ brand: '', domain: 'example.ru', promptsText: 'цветы',
  providerIds: [], regions: [1] })).toBeNull();
expect(validateRun({ brand: 'Бренд', domain: 'example.ru', promptsText: 'x'.repeat(401),
  providerIds: [], regions: [1] })).toMatch(/400/);
expect(requestCount('первый\nвторой', [1, 213])).toBe(4);
```

- [ ] **Step 2: Run `npx vitest run src/lib/search-form.test.ts src/lib/components/SearchReport.test.ts`; confirm failure.**
- [ ] **Step 3: Implement the UI.** Add region rows with accessible selects and remove buttons plus «Добавить регион» to the existing form. Use `data.searchRegions` and `data.searchRegionError` from Task 5; a catalog error must not block model-only checks. Display current request count. On submit validate before sending either branch; call `/api/check` only if models are selected and `/api/search` only if regions are selected. Fetch the first `/api/search/{id}` snapshot immediately after creation, then poll every 30 seconds while nonterminal; stop timer on completion, a newer run, or component destruction. Do not use local/session storage. Show model report and `SearchReport` independently; keep prior model-only display unchanged when no region is selected.

```ts
if (selected.length) void runModelCheck({ brand, domain, prompts_text: promptsText, provider_ids: selected });
if (regions.length) void startSearch({ domain, prompts_text: promptsText, regions });

function stopSearchPolling() {
  if (pollTimer !== undefined) clearTimeout(pollTimer);
  pollTimer = undefined;
}
```

- [ ] **Step 4: Run the new Vitest files, `npm run check`, and `npm run build`; confirm pass.**
- [ ] **Step 5: Commit UI and tests as `Show regional Yandex search in brand checks`.**

### Task 7: Browser flow, documentation, and final verification

**Files:** Create `qa/tests/test_search.py`; modify `README.md`, `backend/README.md`, `qa/README.md`.

**Interfaces:** Exercise the complete Task 4–6 contract without real Yandex calls. Use Playwright route interception for `/api/search`, `/api/search/regions`, and `/api/search/{id}`. In the mixed-run case also intercept `/api/check` so no paid model call occurs.

- [ ] **Step 1: Add a browser test with controlled search responses.** Visit `/`, add two distinct regions, enter `example.ru` and one question, assert «2 запроса к Яндексу», submit without a selected model, return one pending and one found pair, then advance Playwright's clock past the 30-second poll and return a final snapshot with one found and one error. Assert the result link and rank, error text, and no «не найден» label on the failed pair. A second test creates a temporary provider through the existing QA helper, intercepts `/api/check` with a fake report, selects that model, and verifies its report remains visible when search returns an error. Mock both paid APIs in the browser; the QA fixture removes the temporary provider.

```python
page.route('**/api/search/regions', lambda route: route.fulfill(json=[
    {'id': 1, 'name': 'Москва и Московская область'},
    {'id': 213, 'name': 'Москва'},
]))
page.route('**/api/search', lambda route: route.fulfill(status=202, json={
    'id': 'job-1', 'total': 2, 'status': 'pending',
}))
```

- [ ] **Step 2: Run `QA_HEADLESS=1 uv run pytest tests/test_search.py -q` with isolated local backend/frontend processes; confirm it exercises the mocked flow rather than skipping.**
- [ ] **Step 3: Document launch and limits.** Fill the empty root README with `make install`, `make backend`, `make frontend`, required Yandex key/folder variables, and the deferred search workflow. Explain 20 × 5 = 100 request maximum, first-ten organic XML scope, pending results lost on page close/reload/server restart, and the distinction from model mentions. Update backend route table and QA instructions. Do not copy any real `.env` value into docs.
- [ ] **Step 4: Run final verification:** `cd backend && uv run pytest && uv run ruff check app tests`; `cd frontend && npx vitest run && npm run check && npm run build`; `cd qa && QA_HEADLESS=1 uv run pytest tests/test_search.py -q` against isolated services. Check `git diff --check` and `git status --short`, and confirm no generated files or credentials were staged. Resolve only concrete failures.
- [ ] **Step 5: Commit browser check and docs as `Document and verify deferred Yandex search`.**

## Execution notes

- The current `search.py` is untracked user work. The replacement is part of Task 4; do not discard or overwrite it before Tasks 1–3 establish the new boundaries.
- Tests should use injected fake gateways, `httpx.MockTransport`, and browser route interception. Do not call Yandex in automated tests.
- `GET /api/search/regions` must be declared before `GET /api/search/{job_id}` in both Python and SvelteKit routing logic.
- This plan's tasks depend on the public Python and TypeScript interfaces listed in the file map. Finish each task's test cycle before its commit.
