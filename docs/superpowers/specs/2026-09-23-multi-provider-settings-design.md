# Multi-provider checks and API settings

## Purpose

Extend the local brand checker so a user can run the same prompts against GigaChat and DeepSeek, compare model-specific mention results, and add future OpenAI Chat Completions-compatible services from an in-app settings screen. Connections and keys persist across restarts on the same computer.

## Scope

- Ship built-in GigaChat and DeepSeek connection templates. DeepSeek uses the current `deepseek-flash` model and `https://api.deepseek.com/chat/completions`; disable DeepSeek thinking mode for this quick diagnostic check.
- Let the user add and edit a named OpenAI-compatible connection with an HTTPS chat-completions URL, model ID, and API key, and remove a saved connection.
- Let the user select one or more configured connections for a run. Both built-in connections are visible; a missing key shows a setup state rather than pretending the model ran.
- Keep the existing local single-user workflow, limit of 20 prompts, exact brand-name matching, and explicit point-in-time/API-answer language. No web search, domain citation scoring, automatic cost estimate, account system, or public deployment.
- Arbitrary non-compatible HTTP APIs require a provider adapter in a later version. The settings screen accepts OpenAI Chat Completions-compatible services only.

## Architecture

- A small provider protocol exposes `answer(prompt) -> str`; adapters own vendor-specific authentication and response parsing.
- `GigaChatClient` remains a dedicated OAuth adapter. `OpenAIChatClient` handles bearer-token chat completions for DeepSeek and user-added compatible services.
- A provider registry maps each configured connection's kind to its adapter and supplies display names and configuration state to the UI. A new OpenAI-compatible service needs only a saved connection; a new protocol needs a new adapter and registry entry.
- Provider metadata (ID, display name, kind, endpoint, model, and any non-secret preset options) lives in `~/.config/ai-tracker/providers.json`, with an `AI_TRACKER_CONFIG_DIR` override for tests and portability. Write updates atomically. The built-in IDs are `gigachat` and `deepseek`; custom connections receive UUID IDs.
- API keys live in the operating system credential store through Python `keyring`, keyed by a generated connection ID. Metadata and API responses never contain a key. If credential storage is unavailable or denied, saving fails with a clear error; there is no plaintext fallback.
- The existing `GIGACHAT_AUTH_KEY` and related environment settings remain supported as a fallback for the built-in GigaChat connection. A key saved in settings takes priority. Optional `DEEPSEEK_API_KEY` also provides a fallback for the built-in DeepSeek connection.

## User flow and API

1. On the settings view, the user sees GigaChat and DeepSeek presets plus saved custom connections. Each shows whether it is ready; it never shows a stored key.
2. The user enters a key for a preset or creates a custom OpenAI-compatible connection. The form states that the key will be sent to the endpoint shown. A blank key when editing preserves the existing key.
3. Settings endpoints list connections, create/update one, and remove one. They validate names, model IDs, endpoints, and request sizes before writing. Removing a connection removes its associated key; the built-in templates remain available for configuring again.
4. On the check view, the user selects one or more ready connections and enters brand/domain/prompts. The backend resolves selected IDs from its registry; the browser cannot send arbitrary endpoint URLs or API keys with a check request.
5. Results are grouped by connection. Each group has successful, failed, and mentioned counts and per-prompt answer/error. One provider failing does not erase another's results. No failed prompt is counted as a negative mention.

The `POST /api/check` request adds `provider_ids: string[]` (1–5 configured IDs). For backward compatibility, an omitted list selects built-in GigaChat. The response includes `checks: [{provider_id, provider_name, summary, results}]`; each result retains `prompt`, `answer`, `mentioned`, and `error`. The page renders the new shape and uses text nodes for all external strings.

## Security and errors

- Bind only to `127.0.0.1`; accept `localhost`/loopback Host headers, with no permissive CORS. The app is not designed for public exposure.
- Custom endpoints require HTTPS, a public hostname, no embedded username/password, query, or fragment, and no redirect following. Reject IP literals, localhost, `.local`, and obvious private/internal hostnames. This is a guardrail for the local app, not a claim of a complete SSRF defense.
- Secrets are accepted only on the local settings POST/PUT endpoints, are not logged, and are never included in list/check responses. On save failure, leave the previous connection usable.
- Provider clients keep TLS certificate verification enabled and close their HTTP resources after each run. GigaChat's documented certificate setup remains required.
- Authentication, rate limit, network, malformed response, and credential-store failures have readable, provider-specific messages. Invalid selections or malformed settings return HTTP 400 before any paid model call.

## Verification

- Unit tests for provider registry, metadata roundtrip/atomic update, endpoint validation, and fake credential storage, including a failed save that leaves prior settings intact.
- HTTP transport tests for DeepSeek's bearer token, current model ID, disabled thinking, answer parsing, and safe errors.
- Endpoint tests for one/both providers, missing keys, partial failures, invalid IDs, and existing GigaChat request fallback.
- Page checks for settings and provider selection; manual browser check of normal, error, and hostile-HTML responses at desktop width. A live paid request needs user-supplied credentials and is not required for automated verification.

## References

- [DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)
- [DeepSeek current models](https://api-docs.deepseek.com/quick_start/pricing/)
- [Python keyring documentation](https://keyring.readthedocs.io/en/stable/)
