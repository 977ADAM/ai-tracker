# GigaChat brand checker: first release

## Purpose

Build a local web app for a Russian business owner or marketer to check whether GigaChat mentions a brand when answering their own list of questions. Success means a user can enter a brand and several prompts, run a check with their own GigaChat API credentials, and inspect the original answer and an explicit mention result for each prompt.

## Scope and truthfulness

- The first release uses the official GigaChat text generation API only. It measures mentions in responses returned by that API, not presence in internet search results or the consumer GigaChat interface.
- The app does not infer source citations or a site's rank from generated prose. A domain field is optional metadata for future expansion and produces no domain score.
- Each run is a point-in-time sample. The report explains that answers can vary on repeated runs.
- Local, single-user workflow. No accounts, billing, scheduling, historical trends, competitors, or deployment in this release.

## User flow

1. Open the local page and enter a brand name, optional domain, and one prompt per line (up to 20 nonempty prompts).
2. Submit a check. The page sends the inputs to the local backend. API credentials are read from server environment variables and never returned to the browser.
3. The backend sends each prompt unchanged as the user message to GigaChat. It stores no response history.
4. The page displays one row per prompt: status, whether the brand was mentioned, and the original model answer. A summary shows mentions out of successful responses, with failed requests counted separately.
5. Validation and API failures appear beside the affected input or prompt. The app never turns a failed API request into a negative mention result.

## Components

- A small Python HTTP app serves the page and a `POST /api/check` endpoint.
- A GigaChat client handles token acquisition and chat completion calls against the official API. It accepts credentials and scope from environment variables and uses normal TLS verification.
- A text analyzer performs case-insensitive, Unicode-aware brand matching against each answer. It does not guess aliases; the user enters the name they want checked.
- A plain HTML/CSS/JavaScript page provides the form and report. No frontend build system is needed.

## Data and limits

- Request: `brand` (required), `domain` (optional), `prompts` (array of 1–20 nonempty strings).
- Response: normalized brand/domain, per-prompt result (`answer`, `mentioned`, `error`), and successful/failed/mentioned counts.
- Reject empty brands, empty prompt lists, more than 20 prompts, and oversized field values before any paid API call.
- Process prompts sequentially to bound API concurrency. Set request timeouts. Return readable errors for missing credentials, authentication failures, rate limits, and network failures without exposing credentials or raw server internals.

## Verification

- Unit tests for input validation and brand matching, including Unicode case and false positives inside longer words.
- Endpoint tests using a local fake provider, covering success, partial failure, and no configured credentials.
- Manual local check of page layout and report using a fake provider. A live GigaChat check requires user-provided API credentials and is outside automated tests.

## External API references

- [GigaChat API authorization](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/gigachat-api)
- [GigaChat chat completion endpoint](https://developers.sber.ru/docs/ru/gigachat/models/gigachat-3-ultra)
- [GigaChat built-in functions](https://developers.sber.ru/docs/ru/gigachat/guides/functions/calling-builtin-functions)
