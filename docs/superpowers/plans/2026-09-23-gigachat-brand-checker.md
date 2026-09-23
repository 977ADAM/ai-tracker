# GigaChat Brand Checker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a local web app that measures brand mentions in GigaChat API answers to up to 20 user prompts.

**Architecture:** FastAPI serves one static page and a JSON check endpoint. A separate client authenticates with GigaChat, while pure functions validate inputs and detect mentions. The endpoint processes prompts sequentially and preserves each answer or safe error.

**Tech Stack:** Python 3.13, FastAPI, httpx, uvicorn, pytest, plain HTML/CSS/JavaScript.

**Spec:** `docs/superpowers/specs/2026-09-23-gigachat-brand-checker-design.md`

## Global Constraints

- The result describes GigaChat API answers only, not search visibility or source citations.
- One local user; no saved results, account system, scheduling, or deployment.
- At most 20 nonempty prompts, at most 500 characters each. Brand at most 100 characters, domain at most 253 characters.
- API credentials remain in server environment variables. Keep TLS certificate verification enabled.
- A failed API call is an error, never a negative brand mention.

## Review Focus

- Cyrillic and Latin case folding: a differently cased standalone brand matches.
- Brand embedded inside a longer word: no mention is recorded.
- One provider failure amid successes: summary excludes the failed prompt from the denominator.
- A malformed or oversized request: no provider call occurs.
- Hostile HTML in an API answer: the page displays it as text.

## File Map

- `src/ai_tracker/checks.py`: input normalization and mention detection.
- `src/ai_tracker/gigachat.py`: OAuth and completion HTTP client; safe provider errors.
- `src/ai_tracker/web.py`: FastAPI app, endpoint, provider orchestration, static asset serving.
- `src/ai_tracker/static/index.html`: form and result view.
- `src/ai_tracker/static/app.js`: browser request and safe rendering.
- `src/ai_tracker/static/style.css`: layout and readable states.
- `src/ai_tracker/__init__.py`: CLI entry point to local server.
- `tests/`: focused behavior and integration tests.
- `README.md`: setup, credentials, usage, and limits.

### Task 1: Validate inputs and detect mentions

**Files:** Create `tests/test_checks.py`, `src/ai_tracker/checks.py`; modify `pyproject.toml` to add pytest test dependency if needed.

**Interfaces:** `normalize_request(payload: object) -> CheckInput` returns a dataclass with `brand: str`, `domain: str`, `prompts: list[str]`; raises `ValueError` for invalid input. `mentions_brand(answer: str, brand: str) -> bool` checks a Unicode word boundary around a casefolded brand phrase.

- [ ] **Step 1: Write failing tests** for trimmed brand/domain/prompts, empty and oversized values, 21 prompts, Unicode case folding, and brand embedded in another word. Example:

```python
def test_cyrillic_brand_needs_word_boundary():
    assert mentions_brand("Советую РОМАШКА для бизнеса", "ромашка")
    assert not mentions_brand("Суперромашка удобнее", "ромашка")

def test_too_many_prompts_rejected():
    with pytest.raises(ValueError, match="20"):
        normalize_request({"brand": "Ромашка", "prompts": ["вопрос"] * 21})
```

- [ ] **Step 2: Run** `uv run --with pytest pytest tests/test_checks.py -q`; verify failures are missing production behavior.
- [ ] **Step 3: Implement** a frozen `CheckInput`, explicit type/length checks, and a compiled regex using `(?<!\w)` and `(?!\w)` over casefolded strings. Strip whitespace but do not rewrite the user's prompt text beyond leading/trailing whitespace.
- [ ] **Step 4: Run** the focused tests and then the full `uv run --with pytest pytest -q` suite; confirm green.
- [ ] **Step 5: Commit** `checks.py` and its tests as `feat: validate brand checks`.

### Task 2: Connect to GigaChat

**Files:** Create `tests/test_gigachat.py`, `src/ai_tracker/gigachat.py`; add `httpx` to project dependencies.

**Interfaces:** `GigaChatClient(auth_key: str, scope: str, model: str = "GigaChat", transport: httpx.BaseTransport | None = None)`; `answer(prompt: str) -> str`; `ProviderError` carries only a safe user-facing message. The client owns a reusable `httpx.Client` and cached access token.

- [ ] **Step 1: Write failing tests** with `httpx.MockTransport`. Assert that the OAuth request has `Authorization: Basic ...`, `RqUID` UUID, and form `scope`; completion uses `Authorization: Bearer ...`, `model`, and a single unchanged user message. Assert that two answers reuse the token; 401, 429, timeout, malformed JSON, and empty answer become safe `ProviderError`s. Example:

```python
def test_reuses_token_for_two_prompts():
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path == "/api/v2/oauth":
            return httpx.Response(200, json={"access_token": "token", "expires_at": 4102444800000})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Ромашка"}}]})
    client = GigaChatClient("key", "GIGACHAT_API_PERS", transport=httpx.MockTransport(handler))
    assert client.answer("Первый вопрос") == "Ромашка"
    assert client.answer("Второй вопрос") == "Ромашка"
    assert sum(r.url.path == "/api/v2/oauth" for r in requests) == 1
```

- [ ] **Step 2: Run** `uv run --with pytest pytest tests/test_gigachat.py -q`; verify it fails because the client is missing.
- [ ] **Step 3: Implement** OAuth at `https://ngw.devices.sberbank.ru:9443/api/v2/oauth` and completion at `https://api.giga.chat/v1/chat/completions`. Set 20-second connect and 60-second read timeouts. Cache the token until 60 seconds before `expires_at` (handle milliseconds). Map authentication, rate limit, connection/timeout, and malformed response errors to Russian messages without response bodies or secrets.
- [ ] **Step 4: Run** focused and full tests; confirm green.
- [ ] **Step 5: Commit** the client, dependency change, and tests as `feat: add GigaChat API client`.

### Task 3: Add the local HTTP flow

**Files:** Create `tests/test_web.py`, `src/ai_tracker/web.py`; modify `src/ai_tracker/__init__.py` and `pyproject.toml` for FastAPI, uvicorn, and package static files.

**Interfaces:** `create_app(provider=None) -> FastAPI`. `POST /api/check` takes JSON `brand`, optional `domain`, and `prompts`. Results are `{"brand", "domain", "results": [{"prompt", "answer", "mentioned", "error"}], "summary": {"successful", "failed", "mentioned"}}`. Missing credentials yield HTTP 503 before a provider call; invalid inputs yield HTTP 400. Task 4 adds `GET /` and static assets.

- [ ] **Step 1: Write failing endpoint tests** with `fastapi.testclient.TestClient` and an in-memory provider whose `answer` returns text or raises `ProviderError`. Assert correct rows and counts, partial failure handling, invalid input prevents provider use, and absent `GIGACHAT_AUTH_KEY` yields 503. Example:

```python
def test_partial_failure_is_not_negative_mention():
    class Provider:
        def answer(self, prompt):
            if prompt == "ошибка":
                raise ProviderError("Сервис временно недоступен")
            return "Ромашка рекомендует этот вариант"
    response = TestClient(create_app(Provider())).post("/api/check", json={
        "brand": "Ромашка", "prompts": ["успех", "ошибка"]})
    assert response.status_code == 200
    assert response.json()["summary"] == {"successful": 1, "failed": 1, "mentioned": 1}
    assert response.json()["results"][1]["mentioned"] is None
```

- [ ] **Step 2: Run** `uv run --with pytest pytest tests/test_web.py -q`; verify the missing endpoint fails.
- [ ] **Step 3: Implement** a sync endpoint that validates once, obtains the configured client, iterates prompts sequentially, and catches only `ProviderError` per prompt. Change `main()` to start uvicorn on `127.0.0.1:8000` and avoid binding publicly.
- [ ] **Step 4: Run** focused and full tests; confirm green.
- [ ] **Step 5: Commit** the endpoint, entry point, dependency changes, and tests as `feat: serve local brand checks`.

### Task 4: Build the form and report

**Files:** Create `src/ai_tracker/static/index.html`, `app.js`, `style.css`, `tests/test_page.py`; modify `README.md`, `pyproject.toml` package data if necessary.

**Interfaces:** The page submits `POST /api/check` with the endpoint schema. It renders counts and each answer with `textContent` or DOM text nodes. The page copy states the API sample and source limitation.

- [ ] **Step 1: Write a failing page smoke test** that GET `/` includes brand, domain, prompt inputs, a submit button, and the point-in-time/uncertainty note; verify `/static/app.js` and `/static/style.css` are served. Add a browser-level check that an answer containing `<script>` is shown literally and does not execute.
- [ ] **Step 2: Run** `uv run --with pytest pytest tests/test_page.py -q`; verify the page/static checks fail.
- [ ] **Step 3: Implement** a responsive form, loading/empty/error states, report summary and answer cards. Split pasted prompts on newline, remove empty lines, and show the 20-prompt limit before submission. Use `textContent` for every user or provider string. Add a README with `uv sync`, `GIGACHAT_AUTH_KEY`, optional `GIGACHAT_SCOPE` and `GIGACHAT_MODEL`, `uv run ai-tracker`, and the local URL.
- [ ] **Step 4: Run** focused and full tests. Launch locally with a fake provider for visual inspection at desktop and mobile widths. Do not make a paid live call without user credentials.
- [ ] **Step 5: Commit** the page, docs, and tests as `feat: show GigaChat brand report`.

## Final Verification

- [ ] Run `uv run --with pytest pytest -q` and verify zero failures.
- [ ] Run `uv run ai-tracker`, open `http://127.0.0.1:8000`, and inspect form, loading, successful result, partial error, and mobile layout with a fake provider.
- [ ] Review the spec against the UI: no claim that the app measures web search ranking, source citations, or domain visibility.
- [ ] Review `git diff` and `git status`; report any live-API limitation caused by missing credentials.
