# Run History, Results Table, and CSV Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist each form run across reloads and restarts, show combined model/Yandex results and history on the current page, and export a completed run as CSV.

**Architecture:** A `RunService` coordinates the existing model and Yandex services and writes each completed row to a local SQLite `RunRepository`. The frontend starts one run, reads its stored snapshot, and renders detailed results and a common table. FastAPI generates CSV from the same table projection.

**Tech Stack:** Python 3.13, standard-library `sqlite3`/`csv`, FastAPI/Pydantic, SvelteKit/Svelte 5/TypeScript, pytest, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-25-run-history-design.md`

## Global Constraints

- One form submission creates one run for models, Yandex, or both. Preserve direct `/api/check` and `/api/search`.
- Store `runs.sqlite3` in `Settings.config_dir` with owner-only permissions. Do not save API keys, Yandex operation IDs, or raw provider headers.
- Persist each completed model answer and Yandex pair. On startup, interrupt only unfinished rows; never resubmit old requests.
- Only terminal runs may be deleted or exported. Terminal includes provider errors and restart interruption.
- Preserve Yandex's ten-result host rule, ten-per-second submit/result quotas, 1–5 regions, and no language/device controls.
- CSV is one open run: UTF-8 with BOM, semicolon delimiter, quoted fields, the agreed nine columns, and no full model answer text.
- No new production dependency is needed.

## Review Focus

1. Duplicate question text must not overwrite another ordinal result (Task 2 repository test).
2. Restart must retain finished model/search rows and interrupt only pending ones (Task 2 recovery test).
3. SQLite write failure must stop new paid searches and never appear as “site absent” (Task 4 callback test).
4. CSV formula-like text and embedded semicolons/newlines/quotes must remain safe and round-trip (Task 6 export test).
5. Delete/export during the last row's completion must use the committed terminal state (Task 2 atomic-guard test).

---

## File map and interface contracts

| File | Responsibility |
| --- | --- |
| `backend/app/domain/runs.py` | Combined request validation and pure table projection. |
| `backend/app/db/runs.py` | SQLite schema, row updates, cursor pagination, recovery, terminal-only deletion. |
| `backend/app/service/runs.py` | Create a run before external calls and coordinate both branches. |
| `backend/app/service/checks.py` | Optional per-answer callback; old response unchanged. |
| `backend/app/service/search.py` | Optional per-pair callback and expiry notification; old direct-search behavior unchanged. |
| `backend/app/service/run_export.py` | Safe CSV renderer from common table rows. |
| `backend/app/api/schemas/runs.py`, `backend/app/api/routers/runs.py` | HTTP DTOs and run/history/export routes. |
| `backend/app/api/deps.py`, `backend/app/api/router.py`, `backend/app/api/errors.py`, `backend/app/main.py` | Wiring, errors, startup recovery, shutdown. |
| `frontend/src/lib/types.ts`, `frontend/src/lib/server/python-api.ts` | Public run types and allowlisted proxy paths. |
| `frontend/src/routes/api/runs/**/+server.ts` | JSON routes and binary CSV route. |
| `frontend/src/lib/components/RunResults.svelte`, `RunHistory.svelte`, `RunSummaryTable.svelte` | Saved details, history, common table. |
| `frontend/src/routes/+page.svelte`, `+page.server.ts` | One create/poll flow and history on the current page. |

The public snapshot is `{id, created_at, finished_at, status, brand, domain, prompts, provider_ids, regions, models, search, summary_rows}`. Run `status` is `pending`, `done`, or `interrupted`. `models` and `search` are ordered row arrays. A table row is `{prompt, source, language, region, ai_answer, site_found, position, brand_found, status}` with display values as strings. A history item is `{id, created_at, status, prompts}`. `GET /api/runs` returns `{items, next_cursor}`.

### Task 1: Combined input and pure summary projection

**Files:** Create `backend/app/domain/runs.py` and `backend/tests/test_domain_runs.py`.

**Interfaces:** Produce `RunInput(brand, domain, prompts, provider_ids, regions, search_host)`, `normalize_run_request(payload: object) -> RunInput` and `summary_rows(models: list[dict], search: list[dict], *, provider_ids: tuple[str,...], regions: tuple[int,...]) -> list[dict[str,str]]`. Reuse `normalize_check_request`/`normalize_provider_ids` only for chosen models and `normalize_search_request` only for chosen regions.

- [ ] **Step 1: Write failing tests** for model-only, search-only, mixed 400-character search limit, no branch, duplicate prompt text, and the “—” mappings. Pin order with two regions, two prompts and one model.

```python
def test_a_model_row_does_not_claim_site_detection():
    rows = summary_rows(
        models=[{"provider_id": "p", "provider_name": "ChatGPT", "prompt": "цветы",
                 "prompt_index": 0, "status": "mentioned", "answer": "Бренд",
                 "mentioned": True, "error": None}],
        search=[], provider_ids=("p",), regions=(),
    )
    assert rows[0]["site_found"] == "—"
    assert rows[0]["brand_found"] == "Да"
```

- [ ] **Step 2: Confirm red.** Run `cd backend && uv run pytest tests/test_domain_runs.py -q`; expect missing `app.domain.runs`.
- [ ] **Step 3: Implement pure rules.** Preserve one row per ordinal even when prompt text repeats. Search `found/absent` maps site to `Да/Нет`; model `mentioned/absent` maps brand to `Да/Нет`. `error`, `pending` and `interrupted` map unknown values to `—` and distinct status labels.

```python
@dataclass(frozen=True)
class RunInput:
    brand: str
    domain: str
    prompts: tuple[str, ...]
    provider_ids: tuple[str, ...]
    regions: tuple[int, ...]
    search_host: str | None

def normalize_run_request(payload: object) -> RunInput:
    if not isinstance(payload, dict):
        raise ValidationError("Некорректный запрос")
    ids, regions = payload.get("provider_ids", []), payload.get("regions", [])
    if not isinstance(ids, list) or not isinstance(regions, list) or not (ids or regions):
        raise ValidationError("Выберите модель или регион")
    check = normalize_check_request(payload) if ids else None
    search = normalize_search_request(payload) if regions else None
    return RunInput(
        brand=check.brand if check else "",
        domain=search.domain if search else check.domain,
        prompts=search.prompts if search else check.prompts,
        provider_ids=tuple(normalize_provider_ids(payload)) if ids else (),
        regions=search.regions if search else (),
        search_host=search.host if search else None,
    )
```

Implement `summary_rows` by sorting `search` on `(region_index, prompt_index)` and `models` on `(provider order, prompt_index)`, then mapping each source's terminal/pending status exactly as the bullet above. The tests must compare complete row dictionaries, including source, region, language and status, rather than only one flag.

- [ ] **Step 4: Confirm green and commit.** Run `cd backend && uv run pytest tests/test_domain_runs.py -q && uv run ruff check app/domain/runs.py tests/test_domain_runs.py`. Commit both files as `Add combined run rules and result projection`.

### Task 2: Durable SQLite run repository

**Files:** Create `backend/app/db/runs.py` and `backend/tests/test_db_runs.py`; modify `backend/app/core/errors.py` and `backend/app/api/errors.py` for `RunNotFound` → 404 and `RunConflict` → 409.

**Interfaces:** `RunRepository(config_dir: Path)` with `initialize()`, `create(run_id: str, request: RunInput, provider_names: dict[str,str], created_at: str)`, `save_model(run_id, provider_id, prompt_index, result: PromptResult)`, `save_search(run_id, search_index, row: SearchRow)`, `fail_pending_branch(run_id, branch: Literal["model","search"], message: str)`, `interrupt_search(run_id)`, `recover_unfinished()`, `get(run_id) -> dict`, `list_page(cursor: str | None, limit: int = 20) -> dict`, and `delete(run_id) -> None`. A write that makes every selected row terminal updates `finished_at` in the same transaction. The list cursor is base64url without padding of a JSON pair `[created_at, id]`, capped at 256 characters and validated before decoding.

- [ ] **Step 1: Write failing repository tests.** Seed duplicate question rows by ordinal; save one model and one search result; instantiate a second repository over the same directory and verify both persist. Check mode `0o600`, 20-item cursor pagination, rejection of malformed/tampered cursors, no secret columns, and atomic refusal to delete an active run.

```python
def test_restart_keeps_finished_rows_and_interrupts_only_pending(tmp_path, run_input):
    first = RunRepository(tmp_path)
    first.initialize()
    first.create("run-1", run_input, {"p": "ChatGPT"}, "2026-09-25T14:00:00Z")
    first.save_model("run-1", "p", 0, PromptResult("a", "Brand", True, None, "mentioned"))
    second = RunRepository(tmp_path)
    second.initialize()
    second.recover_unfinished()
    saved = second.get("run-1")
    assert saved["models"][0]["status"] == "mentioned"
    assert saved["search"][0]["status"] == "interrupted"
    assert saved["status"] == "interrupted"
```

Define the test's `run_input` fixture as a `RunInput` with two questions, one provider and one region, so the saved first model answer has a different pending model row to interrupt.

- [ ] **Step 2: Confirm red.** Run `cd backend && uv run pytest tests/test_db_runs.py -q`; expect missing repository.
- [ ] **Step 3: Implement schema and transactions.** Tables: `runs(id, created_at, finished_at, brand, domain, prompts_json, provider_ids_json, regions_json)`; `model_rows(run_id, provider_id, prompt_index, provider_name, prompt, status, answer, mentioned, error)`; `search_rows(run_id, search_index, prompt_index, region_index, prompt, region_id, region_name, status, position, url, error)`. Seed each selected pair in `create`. Use short per-method connections, foreign keys, busy timeout and `BEGIN IMMEDIATE` for guarded mutations; `PRAGMA user_version=1`. On startup convert only unfinished rows to `interrupted`. Derive run `pending/done/interrupted` from rows and `finished_at`. Convert SQLite exceptions to safe `StorageError` without echoing SQL, paths or answers.

```python
with connection:
    connection.execute(
        "UPDATE search_rows SET status='interrupted' "
        "WHERE run_id=? AND status IN ('submitting','waiting')", (run_id,)
    )
    _finish_if_terminal(connection, run_id)  # same transaction
```

- [ ] **Step 4: Confirm green and commit.** Run `cd backend && uv run pytest tests/test_db_runs.py -q && uv run ruff check app/db/runs.py app/core/errors.py app/api/errors.py tests/test_db_runs.py`. Commit these files as `Persist run rows and recover interrupted work`.

### Task 3: Publish model answers one at a time

**Files:** Modify `backend/app/service/checks.py` and `backend/tests/test_service_checks.py`.

**Interfaces:** Keep `CheckService.run(payload) -> dict` unchanged for old callers. Add keyword-only `on_result: Callable[[str, int, PromptResult], None] | None = None`. Callback arguments are provider ID, zero-based prompt index and completed result. Callback `StorageError` stops further provider calls and propagates; it is never converted to a negative model result.

- [ ] **Step 1: Write failing tests** with two prompts and one fake provider. Assert the callback sees the first answer before the second provider call. Make the callback raise `StorageError` on its first invocation and assert no second answer is requested.

```python
seen = []
report = service.run(
    payload,
    on_result=lambda provider, index, result: seen.append((provider, index, result.status)),
)
assert seen == [("p", 0, "mentioned"), ("p", 1, "absent")]
assert report["summary"]["successful"] == 2
```

- [ ] **Step 2: Confirm red.** Run `cd backend && uv run pytest tests/test_service_checks.py -q`; expect the new callback test to fail on an unexpected keyword.
- [ ] **Step 3: Add callback at the result boundary.** In `_run_connection` enumerate prompts, call `_ask`, append its `PromptResult` and invoke `on_result(connection.id, index, result)` before asking the next prompt. Let callback errors leave the method; preserve provider closure in `finally` and old report format.

```python
for index, prompt in enumerate(check_input.prompts):
    result = self._ask(provider, setup_error, prompt, check_input.brand)
    results.append(result)
    if on_result is not None:
        on_result(connection.id, index, result)
```

- [ ] **Step 4: Confirm green and commit.** Run `cd backend && uv run pytest tests/test_service_checks.py tests/test_api_checks.py -q`. Commit service and test as `Expose incremental model check results`.

### Task 4: Publish Yandex pairs without changing direct search

**Files:** Modify `backend/app/service/search.py` and `backend/tests/test_service_search.py`.

**Interfaces:** Extend `SearchService.start(payload, *, on_row: Callable[[int, SearchRow], None] | None = None, on_expire: Callable[[], None] | None = None)`. `on_row` receives the original zero-based question-region ordinal after terminal `finish/fail`. Direct `/api/search` calls omit callbacks and retain the old response. Callback `StorageError` aborts that job's sibling pairs before new paid submissions. Expiry invokes `on_expire` so the durable run can interrupt remaining pairs.

- [ ] **Step 1: Write failing tests** for duplicate prompt ordinals, mixed found/error callbacks, callback `StorageError` with 20×5 pairs queued, and expiry notifying `on_expire`. Assert no new submits after storage failure.

```python
seen = []
job = await search.start(
    payload(prompts_text="цветы\nцветы"),
    on_row=lambda index, row: seen.append((index, row.status)),
)
await settle(search, job["id"])
assert [index for index, _ in seen] == [0, 1]
```

- [ ] **Step 2: Confirm red.** Run `cd backend && uv run pytest tests/test_service_search.py -q`; expect the new `on_row` keyword to fail.
- [ ] **Step 3: Add callbacks and fail-fast task handling.** Pass ordinal to `_run_pair`; invoke `on_row` after terminal changes. Use `asyncio.TaskGroup` so a callback `StorageError` cancels queued pairs. Keep existing rate limiters and per-provider-error isolation. Invoke `on_expire` when `_drop_expired` cancels a live job; propagate storage failure rather than setting `UNEXPECTED_FAILURE`. The background task's done callback retrieves/logs its exception safely so the event loop does not emit an unhandled-task warning.

```python
except StorageError:
    raise  # persistence failure aborts the batch
except ProviderError as exc:
    row.fail(str(exc), self.clock())
    if on_row is not None:
        on_row(index, row)
```

- [ ] **Step 4: Confirm green and commit.** Run `cd backend && uv run pytest tests/test_service_search.py tests/test_api_search.py -q`. Commit service and test as `Expose durable Yandex search progress`.

### Task 5: Coordinate and recover one combined run

**Files:** Create `backend/app/service/runs.py` and `backend/tests/test_service_runs.py`; modify `backend/app/api/deps.py` and `backend/app/main.py`.

**Interfaces:** `RunService(repository: RunRepository, checks: CheckService, search: SearchService)` provides `async start(payload: object) -> dict`, `snapshot(run_id) -> dict`, `list_page(cursor=None, limit=20) -> dict`, `delete(run_id) -> None` and `async close()`. `build_container` creates one repository and one service, calls `initialize()` then `recover_unfinished()` before exposing the container; this also makes the existing dependency-override test fixture work. Shutdown closes the run service and search service. Use `asyncio.to_thread` for the synchronous model branch.

- [ ] **Step 1: Write failing service tests.** Fake providers and Yandex gateway cover model-only, search-only and mixed runs. Assert immediate ID, one history item, partial rows, terminal state, unknown provider/invalid region rejection before any paid call, and missing Yandex credentials becoming a terminal search error while models proceed. Inject a repository whose `create` raises `StorageError` and assert no external call.

```python
created = await runs.start({
    "brand": "Ромашка", "domain": "example.ru", "prompts_text": "цветы",
    "provider_ids": ["p"], "regions": [1],
})
assert created["status"] == "pending"
assert runs.snapshot(created["id"])["id"] == created["id"]
assert len(runs.list_page()["items"]) == 1
```

- [ ] **Step 2: Confirm red.** Run `cd backend && uv run pytest tests/test_service_runs.py -q`; expect missing `RunService`.
- [ ] **Step 3: Implement validation, creation and orchestration.** `normalize_run_request` validates both selected branches. Resolve all provider IDs from `CheckService.connections.all()` before `repository.create`. After commit, schedule model work in a tracked background task; search starts with callback to `repository.save_search`. Model callback calls `repository.save_model`. Missing search credentials call `repository.fail_pending_branch(run_id, "search", safe_message)`. A fatal branch error marks only its remaining rows as error when storage works. Track task exceptions and stop new work on `StorageError`; do not make separate form requests to old check/search endpoints. Use a `threading.Event` checked by the model callback; `RunService.close` sets it, preventing a worker from writing another answer after shutdown begins.

```python
run_id = secrets.token_urlsafe(16)
repository.create(run_id, request, provider_names, datetime.now(timezone.utc).isoformat())
if request.provider_ids:
    self.tasks[run_id] = asyncio.create_task(
        asyncio.to_thread(self._run_models, run_id, request)
    )
if request.regions and search.gateway is not None:
    await search.start(
        {"domain": request.domain, "prompts": list(request.prompts),
         "regions": list(request.regions)},
        on_row=lambda i, row: repository.save_search(run_id, i, row),
        on_expire=lambda: repository.interrupt_search(run_id),
    )
return {"id": run_id, "status": repository.get(run_id)["status"]}
```

- [ ] **Step 4: Confirm green and commit.** Run `cd backend && uv run pytest tests/test_service_runs.py tests/test_service_checks.py tests/test_service_search.py -q`. Commit service, wiring, lifecycle and test as `Coordinate durable mixed runs`.

### Task 6: HTTP history and secure CSV export

**Files:** Create `backend/app/service/run_export.py`, `backend/app/api/schemas/runs.py`, `backend/app/api/routers/runs.py`, `backend/tests/test_run_export.py` and `backend/tests/test_api_runs.py`; modify `backend/app/api/router.py` and `backend/app/api/deps.py`.

**Interfaces:** `render_run_csv(snapshot: dict) -> bytes` accepts only a terminal snapshot and uses its `summary_rows`. Routes: `POST /api/runs` → 202 `{id,status}`; `GET /api/runs?cursor=...` → `{items,next_cursor}`; `GET /api/runs/{id}` → public snapshot; `DELETE /api/runs/{id}` → 204; `GET /api/runs/{id}/export.csv` → `text/csv; charset=utf-8` with attachment filename `ai-serp-results-YYYY-MM-DD.csv`. Active export/deletion is 409, missing ID 404, storage failure 503.

- [ ] **Step 1: Write failing tests** for response schemas and errors, four combined rows, no API key/operation ID, and the CSV header plus `Регион`/`Статус`. Parse returned bytes with `utf-8-sig` and `csv.reader(delimiter=";")`. Include a prompt beginning `=HYPERLINK` and one with a semicolon/quote; in the direct renderer test, include a source name containing a newline. Assert formula prefixing and exact round-trip.

```python
response = client.get(f"/api/runs/{run_id}/export.csv")
assert response.content.startswith(b"\xef\xbb\xbf")
rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
assert rows[0] == ["Запрос", "Поисковик", "Язык", "Регион", "ИИ-ответ",
                   "Сайт найден", "Позиция", "Бренд найден", "Статус"]
```

- [ ] **Step 2: Confirm red.** Run `cd backend && uv run pytest tests/test_api_runs.py tests/test_run_export.py -q`; expect missing route/module.
- [ ] **Step 3: Implement schemas, routes and CSV.** Use Pydantic fields for the exact public snapshot and return a FastAPI `Response` containing the rendered bytes, `media_type="text/csv; charset=utf-8"` and `Content-Disposition`. Encode `utf-8-sig`. Before writing a user-controlled cell, prefix `'` when its first non-whitespace character is `=`, `+`, `-` or `@`; guard leading tabs/newlines. Keep ordinary Russian text unchanged. Return only the projected nine columns, not answer text or technical metadata. Define `CSV_KEYS` in public-row order `("prompt", "source", "language", "region", "ai_answer", "site_found", "position", "brand_found", "status")` and `CSV_HEADERS` in the same order with the nine Russian labels from Step 1.

```python
def render_run_csv(snapshot: dict) -> bytes:
    if snapshot["status"] == "pending":
        raise RunConflict("Экспорт доступен после завершения прогона")
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(CSV_HEADERS)
    for row in snapshot["summary_rows"]:
        writer.writerow(safe_cell(row[key]) for key in CSV_KEYS)
    return output.getvalue().encode("utf-8-sig")
```

The guard is `safe_cell(value: str) -> str`: return an apostrophe plus `value` when `value.lstrip(" \t\r\n")` begins with `=`, `+`, `-` or `@`, or when `value` begins with a tab/newline; otherwise return `value`. The API route checks the committed snapshot status before calling the renderer.

- [ ] **Step 4: Confirm green and commit.** Run `cd backend && uv run pytest tests/test_api_runs.py tests/test_run_export.py tests/test_api_checks.py tests/test_api_search.py -q && uv run ruff check app tests`. Commit the HTTP/CSV files as `Expose run history and CSV export`.

### Task 7: Safe SvelteKit proxy and public run types

**Files:** Modify `frontend/src/lib/types.ts`, `frontend/src/lib/server/python-api.ts` and `frontend/src/lib/server/python-api.test.ts`. Create `frontend/src/routes/api/runs/+server.ts`, `frontend/src/routes/api/runs/[id]/+server.ts` and `frontend/src/routes/api/runs/[id]/export.csv/+server.ts`.

**Interfaces:** Add `RunCreated`, `RunHistoryItem`, `RunSnapshot` and `RunSummaryRow` mirroring Task 5/6. `runPath(id)` validates opaque IDs; `publicRunSnapshot` and `publicRunList` allowlist fields. `proxyCsv(request, path)` forwards only the trusted Python CSV bytes and safe download headers; it never parses CSV as JSON or forwards arbitrary upstream headers.

- [ ] **Step 1: Write failing Vitest tests** for allowed IDs, forged paths, extra secret fields in snapshots, cross-origin delete, malformed upstream JSON, and CSV BOM bytes preserved with safe `Content-Type`/`Content-Disposition`.

```typescript
expect(runPath('abc-123_X')).toBe('/api/runs/abc-123_X');
expect(() => runPath('../providers')).toThrow();
expect(publicRunSnapshot({ ...validSnapshot, api_key: 'secret' })).not.toHaveProperty('api_key');
```

- [ ] **Step 2: Confirm red.** Run `cd frontend && npx vitest run src/lib/server/python-api.test.ts`; expect missing run helpers.
- [ ] **Step 3: Implement exact proxy paths.** Extend `ApiPath` and `validPath` for collection, item and `/export.csv` suffix. Match static export before a generic item. Route `POST/GET` collection, `GET/DELETE` item and `GET` export. Add `runListPath(cursor: string | null)` that accepts only the repository's URL-safe opaque cursor (`[A-Za-z0-9_-]{1,256}`), constructs `/api/runs?cursor=...` internally and rejects all other query parameters; validate this path separately because the current `validPath` permits no query string. Handle the new 204 DELETE response before `proxyJson` tries to parse JSON. Reuse existing origin, size and JSON safety checks; for CSV require `text/csv`, cap downloaded bytes and synthesize a safe filename/header rather than forwarding upstream header text unchecked. The `GET /api/runs` SvelteKit handler parses only `cursor` from `request.url` and passes the validated `runListPath` to the proxy.

```typescript
export function runPath(id: string): ApiPath {
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(id)) throw new Error('Invalid run ID');
  return ('/api/runs/' + encodeURIComponent(id)) as ApiPath;
}
export function runExportPath(id: string): ApiPath {
  return (runPath(id) + '/export.csv') as ApiPath;
}
```

- [ ] **Step 4: Confirm green and commit.** Run `cd frontend && npx vitest run src/lib/server/python-api.test.ts && npm run check`. Commit proxy/types/routes/test as `Proxy saved runs and CSV safely`.

### Task 8: Current-page run view, table and history

**Files:** Create `frontend/src/lib/components/RunResults.svelte`, `RunSummaryTable.svelte`, `RunHistory.svelte` and tests `RunSummaryTable.test.ts`, `RunHistory.test.ts`; modify `frontend/src/routes/+page.svelte` and `frontend/src/routes/+page.server.ts`. `SearchReport.svelte` remains the view for the old direct-search contract; `RunResults.svelte` handles durable `interrupted` rows.

**Interfaces:** The page holds `activeRunId`/`RunSnapshot` and one 30-second poll timer. Its submit sends only `POST /api/runs`; history selection sends `GET /api/runs/{id}`. `RunResults` renders stored model/search detail including interrupted rows. `RunSummaryTable` renders `snapshot.summary_rows`; its export link exists only if `status !== "pending"`. `RunHistory` shows newest-first paginated items, «Показать ещё», view and terminal-only delete confirmation.

- [ ] **Step 1: Write failing component tests** for mixed table mappings (`—` for unchecked model site and Yandex brand), error/interrupted status, no export link while pending, terminal export link, and disabled delete for active runs. Put page-level browser assertions in Task 9, including a second submit while a run is pending.

```typescript
render(RunSummaryTable, { props: { snapshot: pendingMixedRun } });
expect(screen.getByText('Сайт найден')).toBeTruthy();
expect(screen.queryByRole('link', { name: 'Экспорт' })).toBeNull();
```

- [ ] **Step 2: Confirm red.** Run `cd frontend && npx vitest run src/lib/components/RunSummaryTable.test.ts src/lib/components/RunHistory.test.ts`; expect missing components.
- [ ] **Step 3: Implement the unified page flow.** Remove the old two-fetch `runModelCheck`/`runSearch` path from form submission. One `runCombined` sends brand, domain, prompts, provider IDs and region IDs. Load the first history page on entry; after creation prepend its item and show it. Poll the open run while pending; refresh its history row; stop on terminal or component destroy. Keep a separate pending-run ID from the currently viewed history ID: the submit button and handler stay blocked while that run is pending, even if the user views an older result. «Посмотреть задачу» loads its snapshot, sets the active ID and scrolls to results. Show saved model answers and Yandex links; remove obsolete “results lost on reload” copy. Preserve form validation and provider/region controls.

```typescript
async function runCombined() {
  const response = await fetch('/api/runs', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ brand, domain, prompts_text: promptsText,
                           provider_ids: selected, regions: chosenRegions })
  });
  if (!response.ok) throw new Error('Не удалось запустить проверку');
  const created: RunCreated = await response.json();
  activeRunId = created.id;
  await loadRun(created.id);
  await loadHistoryFirstPage();
}
```

- [ ] **Step 4: Confirm green and commit.** Run `cd frontend && npx vitest run && npm run check && npm run build`. Commit components/page/tests as `Show combined run results and history`.

### Task 9: End-to-end verification and documentation

**Files:** Create `qa/tests/test_run_history.py`; modify `backend/README.md` and user-facing copy in `frontend/src/routes/+page.svelte` that still describes transient results.

**Interfaces:** No new production API. QA uses controlled API responses and a temporary run ID; it verifies the integrated flow against running local services.

- [ ] **Step 1: Write the browser test** for mixed run → partial table → completed table → CSV download → reload → open history entry → delete. Add several Yandex regions and server-returned `interrupted` rows. Assert the form never sends separate `POST /api/check` or `POST /api/search` and cannot send a second paid run while the first remains pending.

```python
with page.expect_download() as download_info:
    page.get_by_role("link", name="Экспорт").click()
download = download_info.value
assert download.suggested_filename.endswith(".csv")
page.reload()
page.get_by_role("button", name="Посмотреть задачу").first.click()
expect(page.get_by_role("heading", name="Таблица результатов")).to_be_visible()
```

- [ ] **Step 2: Confirm red against missing UI.** Run `cd qa && QA_HEADLESS=1 uv run pytest tests/test_run_history.py -q`; expect the new workflow assertion to fail before page work is complete. If Task 8 already made it pass, record that; do not alter a passing test to manufacture failure.
- [ ] **Step 3: Finish README and user copy.** Document `runs.sqlite3` under `AI_TRACKER_CONFIG_DIR`, restart interruption, terminal-only delete/export and no automatic retention. Remove “results lost on reload” statements. Check the screenshot reference at desktop and narrow widths; ensure horizontal table scrolling and readable controls.
- [ ] **Step 4: Run final verification.** Sequentially run `cd backend && uv run pytest -q && uv run ruff check app tests`, `cd frontend && npx vitest run && npm run check && npm run build`, then `cd qa && QA_HEADLESS=1 uv run pytest tests/test_run_history.py tests/test_search.py -q`. Confirm actual outputs, inspect `git diff --check` and fix only concrete failures.
- [ ] **Step 5: Commit and review.** Commit QA/docs/final corrections as `Verify saved run history end to end`. Request one whole-branch review with `superpowers:requesting-code-review` before calling the feature complete; address actionable findings, rerun affected checks, then use `superpowers:finishing-a-development-branch` for integration.
