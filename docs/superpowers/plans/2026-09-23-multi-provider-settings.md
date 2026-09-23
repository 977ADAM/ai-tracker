# Multi-provider Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the local app compare GigaChat, DeepSeek, and user-added OpenAI-compatible APIs, with connections saved through an in-app settings screen.

**Architecture:** A provider protocol separates the check loop from vendor authentication. GigaChat remains an OAuth adapter; DeepSeek and user-added services use a bearer-token Chat Completions adapter. A local connection store holds non-secret metadata while the OS credential store holds API keys. The HTTP API and browser UI list/configure providers and group check results by provider.

**Tech Stack:** Python 3.13, FastAPI, httpx, keyring, pytest, plain HTML/CSS/JavaScript.

**Spec:** `docs/superpowers/specs/2026-09-23-multi-provider-settings-design.md`

## Global Constraints

- Local single-user app bound to `127.0.0.1`; no public deployment or permissive CORS.
- Up to 20 prompts and 1–5 selected connections per run.
- Brand mention is exact-name matching of API answers; do not claim search visibility or citations.
- DeepSeek preset is `deepseek-flash` at `https://api.deepseek.com/chat/completions`, with thinking disabled.
- Custom connections use public HTTPS Chat Completions endpoints only; do not follow redirects.
- Metadata persists in `~/.config/ai-tracker/providers.json` or `AI_TRACKER_CONFIG_DIR`; keys use OS keyring only. Never return or log keys.
- Saved GigaChat/DeepSeek keys take priority over existing environment variable fallbacks.

## Review Focus

- A failed keyring write must not replace a working connection or leak a key to JSON.
- A malicious or malformed endpoint URL must be rejected before it can receive a key or prompt.
- A missing key or failed provider must not hide another model's valid answers or count as a negative mention.
- Provider and model names containing HTML must render as text, not markup.
- Duplicate/unknown provider IDs and over-limit selections must be rejected before model calls.

## File Map

- `src/ai_tracker/providers.py`: shared provider protocol/error, model metadata, factory by connection kind.
- `src/ai_tracker/openai_chat.py`: reusable bearer-token Chat Completions adapter.
- `src/ai_tracker/gigachat.py`: import shared error and add explicit resource closing.
- `src/ai_tracker/connections.py`: built-in presets, endpoint validation, metadata persistence, keyring-backed secrets.
- `src/ai_tracker/web.py`: settings routes, selected-provider checks, grouped response, local host guard.
- `src/ai_tracker/static/index.html`, `app.js`, `style.css`: provider selection and grouped report.
- `src/ai_tracker/static/settings.html`, `settings.js`: connection settings screen.
- `README.md`, `pyproject.toml`, `uv.lock`: setup and dependencies.
- `tests/test_openai_chat.py`, `test_connections.py`, `test_web.py`, `test_page.py`: meaningful behavior checks.

### Task 1: Shared provider contract and DeepSeek API adapter

**Files:** Create `src/ai_tracker/providers.py`, `src/ai_tracker/openai_chat.py`, `tests/test_openai_chat.py`; modify `src/ai_tracker/gigachat.py` and `tests/test_gigachat.py` only where needed for shared errors and closing.

**Interfaces:** `AnswerProvider` defines `answer(prompt: str) -> str` and `close() -> None`; `ProviderError` contains a safe message. `OpenAIChatClient(api_key: str, endpoint: str, model: str, *, thinking_disabled: bool = False, transport: httpx.BaseTransport | None = None)` implements it.

- [ ] **Step 1: Write failing transport tests** for bearer authorization, unchanged prompt, model, DeepSeek's `thinking: {type: disabled}`, generic provider without DeepSeek options, empty/malformed answer, 401, 429, timeout, and client closing. Example:

```python
def test_deepseek_request_uses_current_model_and_no_thinking():
    def handler(request):
        assert request.url == "https://api.deepseek.com/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body == {"model": "deepseek-flash", "messages": [{"role": "user", "content": "Где заказать цветы?"}], "thinking": {"type": "disabled"}}
        return httpx.Response(200, json={"choices": [{"message": {"content": "Ромашка"}}]})
    provider = OpenAIChatClient("test-key", "https://api.deepseek.com/chat/completions", "deepseek-flash", thinking_disabled=True, transport=httpx.MockTransport(handler))
    assert provider.answer("Где заказать цветы?") == "Ромашка"
```

- [ ] **Step 2: Run** `uv run --with pytest pytest tests/test_openai_chat.py -q`; expect failure because the adapter is missing.
- [ ] **Step 3: Implement** the adapter with normal TLS verification, 20-second connect/60-second read timeouts, no redirects, and safe Russian errors. Move `ProviderError` to `providers.py` and preserve a compatibility import from `gigachat.py`. Add `close()` to both adapters and test that the HTTP client closes.
- [ ] **Step 4: Run** focused tests and `uv run --with pytest pytest -q`; confirm all current behavior remains green.
- [ ] **Step 5: Commit** as `feat: add reusable chat completion provider`.

### Task 2: Persistent connections and secret storage

**Files:** Create `src/ai_tracker/connections.py`, `tests/test_connections.py`; add `keyring` dependency in `pyproject.toml` and update `uv.lock`.

**Interfaces:** `ConnectionStore(config_dir: Path, secrets: SecretStore)` supplies `list_connections()`, `save_connection(payload, connection_id=None)`, `delete_connection(id)`, and `get_key(id)`. `SecretStore` has `get_password`, `set_password`, `delete_password`; the production instance delegates to `keyring`. Built-in IDs: `gigachat`, `deepseek`. Custom IDs: UUIDs. A public connection dictionary includes `id`, `name`, `kind`, `endpoint`, `model`, `configured`, never the key.

- [ ] **Step 1: Write failing tests** with `tmp_path` and an in-memory secret store. Cover built-in presets, saved custom connection surviving a second `ConnectionStore` instance, omitted edit key retaining the old key, delete removing the key, failed keyring write leaving prior metadata/key intact, and absent keyring refusing save. Example:

```python
def test_saved_key_is_not_in_metadata(tmp_path, fake_secrets):
    store = ConnectionStore(tmp_path, fake_secrets)
    saved = store.save_connection({"name": "Тест", "kind": "openai", "endpoint": "https://api.example.com/v1/chat/completions", "model": "example-model", "api_key": "secret-value"})
    assert store.get_key(saved["id"]) == "secret-value"
    assert "secret-value" not in (tmp_path / "providers.json").read_text()
    assert "api_key" not in saved
```

- [ ] **Step 2: Write URL validation tests** rejecting HTTP, IP literals, localhost, `.local`, dotless hosts, embedded credentials, query/fragment, and paths that do not end in `/chat/completions`; accept valid public HTTPS hosts with prefixes such as `/v1` or `/api/v1`.
- [ ] **Step 3: Run** `uv run --with pytest pytest tests/test_connections.py -q`; expect missing store/validation failures.
- [ ] **Step 4: Implement** metadata as atomic JSON replacement (`tempfile` in the same directory, `os.replace`, file mode 0600), keyring service `ai-tracker` with one entry per ID, and rollback of metadata/key on save failure. Built-in presets keep fixed endpoint/model; editing them changes only credentials and GigaChat scope. Preserve environment fallbacks when no saved key exists.
- [ ] **Step 5: Run** focused and full tests; commit as `feat: save provider connections locally`.

### Task 3: Settings and multi-provider check endpoints

**Files:** Modify `src/ai_tracker/web.py`, `src/ai_tracker/checks.py`, `tests/test_web.py`; use the new registry/store. Add trusted-host middleware.

**Interfaces:** `create_app(provider=None, store=None, provider_factory=None, allowed_hosts=None)` keeps a legacy injected provider for existing tests; the production host allowlist is `localhost` and `127.0.0.1`, while tests pass `allowed_hosts=["testserver"]`. `GET /api/providers` lists public connections; `POST /api/providers`, `PUT /api/providers/{id}`, and `DELETE /api/providers/{id}` manage them. `POST /api/check` accepts `provider_ids` and returns `{brand, domain, checks: [{provider_id, provider_name, summary, results}]}`. Omitted IDs select `gigachat`.

- [ ] **Step 1: Write failing endpoint tests** with fake store/providers. Assert two providers get the same prompts and isolated summaries; one provider failure does not erase the other; unknown, duplicate, or six IDs return 400 before calls; missing key becomes a provider error; settings GET omits keys; invalid settings return 400. Example:

```python
def test_one_provider_failure_keeps_other_results(client):
    response = client.post("/api/check", json={"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ["gigachat", "deepseek"]})
    assert response.status_code == 200
    assert response.json()["checks"][0]["summary"] == {"successful": 1, "failed": 0, "mentioned": 1}
    assert response.json()["checks"][1]["summary"] == {"successful": 0, "failed": 1, "mentioned": 0}
```

- [ ] **Step 2: Run** `uv run --with pytest pytest tests/test_web.py -q`; expect new behavior to fail.
- [ ] **Step 3: Implement** provider lookup by saved ID, construction by kind, keyring/environment priority, sequential per-provider/per-prompt calls, provider-specific error groups, and `finally: close()` on app-owned clients. Require configured IDs from the registry, with missing keys rendered as per-provider errors. Use `TrustedHostMiddleware` for `localhost` and `127.0.0.1`; keep CORS unset. Settings changes must never echo keys.
- [ ] **Step 4: Run** focused and full tests; commit as `feat: check multiple saved providers`.

### Task 4: Settings screen and model comparison report

**Files:** Modify `src/ai_tracker/static/index.html`, `app.js`, `style.css`, `src/ai_tracker/web.py`, `tests/test_page.py`; create `settings.html` and `settings.js`; update `README.md`.

**Interfaces:** The check form loads `GET /api/providers`, submits selected `provider_ids`, and renders `checks` grouped by provider. The settings screen calls the settings endpoints and never displays a stored key. Built-in DeepSeek is ready to configure from the first launch.

- [ ] **Step 1: Write failing page smoke tests** for `/settings`, browser assets, provider-selection controls, and copy explaining the API-answer limitation. Add a browser-level manual script using fake providers to verify a provider name/answer containing `<script>` is shown literally and does not execute.
- [ ] **Step 2: Run** `uv run --with pytest pytest tests/test_page.py -q`; expect new route/controls to fail.
- [ ] **Step 3: Implement** a responsive settings page with preset cards, custom connection form, configured status, edit/remove actions, and a note that the key is sent to the entered endpoint. On the check page, show selectable provider cards and separate summaries/answer cards per provider, with loading and error states. Use `textContent` for every provider-controlled and user-controlled value. Document `DEEPSEEK_API_KEY`, keyring behavior, supported endpoint format, and migration from `GIGACHAT_AUTH_KEY` in README.
- [ ] **Step 4: Run** focused/full tests, build the wheel, and inspect both pages in the local browser with fake providers. Verify keyless setup, successful DeepSeek/GigaChat groups, partial failure, and hostile HTML.
- [ ] **Step 5: Commit** as `feat: configure and compare AI providers`.

## Final Verification

- [ ] Run the complete test suite and `uv build`; inspect outputs and wheel contents.
- [ ] Start the app with fake providers and inspect normal, error, and empty-key UI states. Live paid requests require user keys and are not part of automated verification.
- [ ] Check the UI and README against the spec: no search/citation claim, no key returned, local-only host binding.
- [ ] Review `git diff --check`, `git status`, and full branch diff before reporting completion.
