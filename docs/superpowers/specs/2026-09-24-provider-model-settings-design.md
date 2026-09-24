# Provider and model settings modal

## Purpose

Make the existing API settings modal resemble the supplied dark settings references and let one custom provider hold several separately selectable models that share one endpoint and API key. The first version contains only the Models section. It does not show inactive General, Plugins, Agent presets, configuration-file, or catalog actions.

## User flow

1. The user opens a large dark modal from the main page. A narrow left rail marks «Модели» as active; the right pane explains that keys configure model access and lists custom provider cards. The modal scrolls internally and adapts to narrow screens.
2. Each card shows the provider name and a configured/unconfigured status. «Настроить» expands an inline editor. The key field is empty, with a placeholder explaining that a new value replaces the saved key. Leaving it empty preserves the key.
3. «Дополнительные настройки» reveals the shared HTTPS Chat Completions endpoint and model rows. Each row has a model ID sent to the API and a display name shown in the interface. The user can add, rename, or remove model rows, then apply or cancel the changes. A provider must retain at least one model.
4. One dashed «Добавить провайдера» action opens an inline creation card for provider name, endpoint, key, and at least one model. There are no built-in provider choices in this flow. A custom provider can be deleted with confirmation; deletion removes its saved key and all of its models.
5. After saving, the modal updates its card and the main page lists each configured model as a separate check option. Removing a model also removes it from that list. Escape, the close button, and the backdrop close the modal; focus returns to the opener. Keyboard focus stays inside the open dialog.

## Data and migration

- A provider group owns `id`, display `name`, OpenAI-compatible `endpoint`, and a nonempty ordered list of models. A model owns a stable `id`, API `model` identifier, and display `name`. Provider and model IDs are distinct concepts even when a migrated record uses the same string for both.
- Provider metadata remains in `providers.json`; API keys remain in the operating-system credential store, keyed by provider group ID. Neither metadata nor read responses contain a key.
- Read existing single-model custom connections as provider groups with one model. Preserve each legacy connection ID as both its group ID and its model ID, so the keyring entry and saved check selections remain valid. The first successful settings write persists the new versioned shape atomically. The migration must not erase keys or silently drop malformed records; a migration failure leaves the old file untouched and produces a readable error.
- Existing preset-related backend paths remain compatible with their current tests, but the shipped application still has no presets. Presets do not appear as choices in the new custom-provider creation flow.

## API and check behavior

- The modal uses its own settings resource:

  | Method | Path | Purpose |
  | --- | --- | --- |
  | `GET` | `/api/providers/settings` | List provider groups and their models without keys |
  | `POST` | `/api/providers/settings` | Create a custom provider group |
  | `PUT` | `/api/providers/settings/{id}` | Update one provider, its shared key, and its models |
  | `DELETE` | `/api/providers/settings/{id}` | Delete one provider, its models, and its saved key |

  These routes exist in both the Python API and the SvelteKit BFF; the browser calls only the BFF. Static `/providers/settings` routes must resolve before the legacy dynamic `/providers/{id}` route. The modal uses no write calls to `/api/providers`.
- Settings writes validate name lengths, HTTPS Chat Completions endpoint rules, model IDs and display names, unique stable model IDs, a nonempty model list, and request size. Updates replace the group's model list as one atomic metadata operation. A blank or omitted key preserves the stored key. Read responses include configuration status but never the key. Existing `/api/providers` write endpoints can remain as compatibility adapters for single-model clients; they must call the same service rules and cannot bypass validation or secret handling.
- Keep `GET /api/providers` as the flat public list consumed by the main page. It returns one choice per model, using the model ID as `id` and a human-readable label that distinguishes models in the same provider. Keep `POST /api/check` with `provider_ids`, treating those IDs as model selections. The server resolves a selected model to its owning provider, uses the provider's key and endpoint, and sends that model's API identifier. The check request cannot supply a key or endpoint.
- A selected missing key, deleted model, or failed model call follows the existing readable-error behavior. One failed model does not erase results for other selected models. The five-selection and twenty-prompt limits stay unchanged.
- The Python settings router handles HTTP parsing and response schemas only. A settings service owns create/update/delete and coordination with the repository; pure domain code validates provider/model invariants; the repository implements metadata persistence and the credential-store port. The check service resolves model IDs through the same domain/repository boundary. The SvelteKit BFF only proxies allowlisted routes and public fields, enforces same-origin writes, and limits request bodies; it contains no provider business rules.

## Visual behavior

- Match the references' charcoal background, rounded full-window-like shell, muted borders, subdued secondary text, inset editor, dashed add action, and clear status indicator. Use Russian copy consistent with the existing application; keep the rest of the app's visual system intact.
- Show only one sidebar item, «Модели». Do not add controls with no behavior. The expanded editor places the key above the advanced settings and keeps apply/cancel actions at its lower right. Model rows show both API ID and display name.
- Keep the form legible at phone widths with a single-column layout, minimum touch targets, visible keyboard focus, and internal scrolling. Errors and success messages appear near the affected provider or creation form.

## Verification

- Backend tests cover old-file migration, key preservation, multi-model metadata round trips, atomic failure rollback, model-level lookup, endpoint validation, and check isolation across models.
- API/BFF tests cover the exact `/api/providers/settings` routes, list and write shapes, secret redaction, invalid model lists, deleted IDs, route precedence over `/api/providers/{id}`, and model selection semantics.
- Browser QA covers opening/closing and keyboard focus, adding a provider and second model, editing a model, replacing and retaining a key without exposing it, deleting a model/provider, seeing separate check options on the main page, and the legacy `/settings` route remaining absent.
- Run Svelte/TypeScript checks, frontend build, backend tests, and browser QA against isolated local services before completion.
