# SvelteKit BFF and frontend migration

## Purpose and agreed direction

Make SvelteKit 2, Svelte 5, and Tailwind CSS the local app's user interface. The existing Python FastAPI service remains responsible for provider calls, brand matching, connection metadata, and OS keychain storage. SvelteKit is a backend for the frontend (BFF): the browser sends requests only to its origin, and SvelteKit's server calls the Python API over loopback.

The product remains a local, single-user brand mention checker. It preserves GigaChat, DeepSeek, custom OpenAI-compatible connections, up to 20 prompts, 1–5 selected providers, per-provider result groups, and the distinction between API answers and web/search citations. A single-command local start is the working assumption; the user has not selected a different launch workflow.

ChatGPT and Яндекс (Алиса AI) are planned for a later stage. This migration does not add their dedicated connection templates or adapters. It preserves the existing provider registry and connection settings so those services can be added without rebuilding the frontend workflow. A service with an OpenAI Chat Completions-compatible API may use the current custom-connection form; a service with a different protocol will need a Python adapter and registry entry in that later stage. The product should describe API answers accurately and not imply that an API call reproduces the consumer chat application's answer.

## Alternatives considered

1. **Thin BFF (selected).** SvelteKit server routes forward validated requests to the existing FastAPI endpoints. Python remains the sole source of provider and secret rules. This minimizes duplicated behavior and keeps the migration focused on the UI and server boundary.
2. **SvelteKit form actions with duplicated service rules.** Form actions could give progressive enhancement, but duplicating validation and key handling across Node and Python would create two sources of truth. This is unnecessary for the local app.

Direct browser-to-Python calls do not meet the requested BFF architecture.

## Runtime and code layout

- Add a conventional SvelteKit project at the repository root (`package.json`, `svelte.config.js`, `vite.config.ts`, `src/routes`, `src/lib`, `src/app.css`, `src/app.html`). Python code remains under `src/ai_tracker`.
- Use Svelte 5 runes for interactive state and Tailwind CSS through its official Vite integration. Use the Node adapter for a server build; static export would remove the BFF.
- Serve the UI and BFF on `127.0.0.1` at the SvelteKit port. Keep FastAPI on `127.0.0.1:8000`, never on a public interface. `AI_TRACKER_API_URL` is server-only and accepts a loopback HTTP origin, with `http://127.0.0.1:8000` as its default. No browser bundle receives this setting or a saved provider key.
- A repository-level `npm run dev` starts both FastAPI and SvelteKit, stops both when interrupted, and reports an occupied port or missing runtime clearly. Setup still requires `uv sync` and `npm install`. A repository-level `npm run start` similarly starts the built Node adapter and FastAPI after `npm run build`.
- Replace the old FastAPI-rendered pages and static assets after parity is verified. FastAPI retains its `/api/*` endpoints and tests; SvelteKit owns `/`, `/settings`, and the browser-facing `/api/*` routes.

## BFF contract and data flow

The browser-facing routes mirror the existing API:

| SvelteKit route | Python route | Purpose |
| --- | --- | --- |
| `GET /api/providers` | `GET /api/providers` | List public provider metadata and configured state |
| `POST /api/providers` | `POST /api/providers` | Create an OpenAI-compatible connection |
| `PUT /api/providers/[id]` | `PUT /api/providers/{id}` | Edit a connection or preset key |
| `DELETE /api/providers/[id]` | `DELETE /api/providers/{id}` | Remove a custom connection or reset a preset key |
| `POST /api/check` | `POST /api/check` | Check selected providers and return grouped results |

All upstream URLs are constructed server-side from fixed route patterns and encoded IDs. The browser cannot supply an upstream URL. The BFF accepts JSON only on mutation routes, enforces a modest body limit, forwards the necessary fields, and returns the Python API's safe JSON body and status. It neither stores nor logs API keys, prompts, or model answers. A failed/unavailable Python service becomes a concise 502 response. Timeouts should allow the existing sequential 5-provider × 20-prompt check while still yielding a readable failure; do not use a short generic proxy timeout that truncates a valid run.

The initial provider list may be loaded via `+page.server.ts` for server rendering; later list refreshes and all writes use the BFF routes. Keep the response shapes compatible with the existing Python contract. Components use normal Svelte text interpolation for provider names, prompts, answers, and errors, never raw HTML injection.

## UI and behavior

- Rebuild the current two pages as responsive Svelte components styled with Tailwind. Preserve the existing user flow and nontechnical Russian copy: provider selection, brand/domain/prompts, loading and validation states, grouped summaries and answer cards; preset/custom connection cards and a form for endpoint/model/key.
- Clearly mark unconfigured providers. Only configured providers can be selected. A blank key on edit retains the saved key; a stored key is never re-displayed. Preset key reset remains available, with the environment-variable fallback explained.
- Keep exact-name matching and point-in-time language. Domain is context only; the app does not check citations or search visibility.
- Show Python validation and provider errors without exposing a stack trace or key. One provider's failure remains confined to its result group.

## Local security boundary

- Both servers bind to loopback. SvelteKit BFF endpoints reject cross-origin mutation requests and do not enable permissive CORS. The Python API keeps its trusted-host guard.
- API keys are entered in the local page and sent over the same-origin BFF route to Python, where the OS keychain stores them. The BFF returns only the public response metadata. The BFF does not persist keys to files, cookies, logs, or browser storage.
- Keep endpoint validation in Python: custom providers still require a public HTTPS Chat Completions URL. SvelteKit may give immediate UI feedback, but Python remains authoritative.
- Treat provider/model/answer text as untrusted when rendered. Svelte's escaped interpolation is the default; avoid `{@html}` for API content.

## Verification and migration

- Add BFF route tests with a fake upstream: correct method/path/body/status forwarding, unavailable upstream, malformed/oversized requests, no key in GET/check responses, and loopback-only upstream selection.
- Add Svelte component/browser checks for both pages, provider selection, keyless state, successful and partial-failure groups, hostile HTML rendered literally, and responsive layout.
- Keep the Python test suite green, then remove obsolete FastAPI page tests and static assets only after the new UI reaches parity. Verify `npm run check`, frontend tests, `npm run build`, Python tests, and a browser run using fake providers. Live paid API calls are outside automated verification.
- Update README with setup, one-command local start, both service ports, the BFF data path, and key storage. The SvelteKit URL becomes the entry point.

## References

- [SvelteKit routing and server endpoints](https://svelte.dev/docs/kit/routing)
- [SvelteKit server-only modules](https://svelte.dev/docs/kit/server-only-modules)
- [SvelteKit Node adapter](https://svelte.dev/docs/kit/adapter-node)
- [Tailwind CSS installation with SvelteKit](https://tailwindcss.com/docs/installation/framework-guides/sveltekit)
