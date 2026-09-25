# Yandex Search in brand checks

## Purpose and agreed outcome

Add Yandex web search to the existing local brand-check form. For each customer question and selected region, report whether the site entered in «Сайт» appears among the first ten Yandex Search API results. The site's exact host and its subdomains count as matches. Users can select one to five regions, and the search runs only when at least one region is selected. Model-answer checks remain available and independent. A search-only run is valid when no model is selected.

This first version uses the lower-cost deferred search mode. Results appear on the current page as they become ready; there is no saved history or recovery after page reload, tab close, or server restart. Language and device controls from the reference screenshot are outside this scope. The search type is Russian, and no device-specific user agent is sent.

## Why deferred mode

The current untracked `backend/app/api/routers/search.py` calls Yandex's deferred endpoint, then waits inside the HTTP request until the operation completes. Yandex says deferred work can take from five minutes to a few hours, so an HTTP request must not wait for completion. The synchronous endpoint returns promptly but costs substantially more. The [current Yandex tariff](https://aistudio.yandex.ru/en/docs/search-api/pricing) lists daytime rates of ₽488 versus ₽30.5 per 1,000 synchronous and deferred requests respectively. One run creates at most 20 questions × 5 regions = 100 deferred search requests. The UI shows that request count before submission; it does not hard-code a monetary estimate.

## User flow

1. The existing form gains a Yandex section with «Добавить регион». Each row contains one region selector and a remove control. There are no selected regions by default; duplicates and more than five rows are disallowed. Region names come from the backend's catalog. The section has no language or device selector.
2. If regions are selected, «Сайт» is required. The existing questions are sent unchanged to both the selected models and Yandex, when both are selected. If no regions are selected, existing model-check behavior and its 500-character question limit remain. With regions selected, each question must be no longer than Yandex's 400-character limit.
3. Before submission, show the number of Yandex requests: question count × region count. A run needs at least one model or one region.
4. The form starts the model check through the existing `/api/check` and the search through `/api/search` independently. Model results can appear while Yandex is still pending. Failure of either branch does not erase the other's results.
5. The Yandex result block shows progress and, for every question-region pair, one of: waiting/submitting, found, not found in the first ten, or error. A found row includes its first matching rank (1–10) and a link to the matching page. The search aggregate counts successful, found, and failed pairs separately from the model mention summary. A failed pair is never counted as an absent site.
6. The page polls the local status route while open and stops polling when all pairs reach a terminal state or the component is destroyed. Reloading or leaving the page discards the displayed job ID. No browser storage, history page, notification, or recovery mechanism is added.

## API contract and lifecycle

- `GET /api/search/regions` returns ordered `{id, name}` entries with documented Yandex numeric region IDs. The catalog is maintained on the Python side and is shared with the frontend through the BFF. The first version includes the commonly used regions already represented in `search.py`, corrected against Yandex's [region reference](https://yandex.cloud/docs/search-api/reference/regions); only distinct, documented IDs are exposed.
- `POST /api/search` accepts `{domain, prompts_text, regions}`. `regions` is a list of 1–5 distinct catalog IDs. It validates the site, 1–20 nonempty questions of at most 400 characters, and the region list before sending paid requests. It creates an in-memory batch and immediately returns `{id, total, status}` with `202 Accepted`. The server generates the opaque ID; clients do not choose Yandex operation IDs.
- `GET /api/search/{id}` returns a snapshot with the original domain, ordered regions, total/completed counts, and ordered pair results. Each pair carries `prompt`, `region_id`, `region_name`, `status`, `position: int | null`, `url: string | null`, and `error: string | null`. Unknown or expired IDs return 404. No API key, folder ID, raw XML, Yandex operation ID, or upstream error body appears in a response.
- Python holds batch state in memory for this local single-user process. A background task submits each question-region request and polls its Yandex operation until completion. Outbound calls are concurrency-limited and status polling uses bounded intervals/backoff; the HTTP route never waits for Yandex completion. Completed and abandoned jobs are removed after a bounded retention period. Shutdown cancels local background tasks. A restart loses jobs as agreed.
- The SvelteKit BFF allowlists these three routes and methods, validates same-origin writes and body size, and returns only the declared public fields. The browser never calls Python or Yandex directly.

## Backend boundaries

- `api/routers/search.py` contains only route declarations, request/response schemas, and dependency calls. It does not read environment variables, call `httpx`, poll operations, parse XML, or decide domain matches.
- `domain/search.py` contains pure input normalization, region catalog rules, host normalization/matching, result/status types, and the first-ten ranking rule. The target can be entered as a hostname or HTTP(S) URL; matching uses the URL host only. `example.ru` matches `example.ru` and hosts ending in `.example.ru`, but not `otherexample.ru`. Invalid or non-HTTP(S) result URLs cannot match.
- `service/search.py` owns batches, the per-pair lifecycle, independent errors, concurrency limits, and snapshots. It depends on a search port/protocol and an in-memory job store abstraction; it does not know `httpx`, FastAPI, or XML.
- `integrations/yandex_search.py` implements the port with Yandex Search API v2. It sends `POST /v2/web/searchAsync` with `SEARCH_TYPE_RU`, page 0, `groupSpec` selecting ten flat groups and one document per group, the selected numeric `region` at the top level, and `FORMAT_XML`. It polls the Operation API using the returned ID, decodes `response.rawData`, and extracts the first ten result documents in order. Yandex's [API reference](https://aistudio.yandex.ru/ru/docs/search-api/api-ref/WebSearchAsync/search) places `region` at the top level, rather than under `query` as implied by the current `search.py`.
- `core/config.py` resolves `YANDEX_SEARCH_API_KEY` and `YANDEX_SEARCH_FOLDER_ID`, with `API_KEY` and `FOLDER_ID` as backward-compatible fallbacks. Existing root `.env` loading is moved to application startup/configuration; adapters receive credentials through dependency construction. Credentials stay server-side and are never included in exceptions or logs.

## Failure semantics and limits

Malformed input is rejected before any Yandex request. Missing credentials reject creation with a readable configuration error. Once a batch starts, an authentication failure, rate limit, network timeout, failed operation, missing `rawData`, invalid Base64/XML, or invalid result shape marks only the affected pair as an error; the response contains a safe, concise message, not Yandex's raw body. Other pairs continue. The UI distinguishes pending, absent, and failed states. A job may remain pending for hours while the page is open.

The first ten results refer to the first page of XML search results, not advertisements or a browser's personalized search page. Yandex's `region` parameter influences ranking; it does not guarantee results exclusively from the selected area. The tool reports a point-in-time API result and does not infer a site's overall search visibility from the first ten results.

## Verification

- Pure domain tests cover hostname and URL normalization, exact/subdomain matching, lookalike suffixes, invalid URLs, duplicate/unknown regions, empty values, and 400-character limits.
- Integration tests use fake HTTP responses for request shape, operation polling, Base64/XML decoding, result order, no match, malformed payloads, timeouts, and safe error redaction. They make no paid Yandex calls.
- Service/API tests cover 202 creation, immediate status snapshot, eventual partial completion, per-pair failure isolation, a 100-request maximum, unknown job IDs, missing credentials, and task cleanup.
- BFF/frontend checks cover route allowlisting and redaction, zero-to-five region selection, conditional site/length validation, search-only and mixed runs, request-count display, independent model results, polling, and pending/found/absent/error rendering.
- Run backend tests, Svelte/TypeScript checks, frontend build, and focused browser QA with mocked Yandex responses. Document the server-side environment settings and that closing the page loses access to pending search results.
