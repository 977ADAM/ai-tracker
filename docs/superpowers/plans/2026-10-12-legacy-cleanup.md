# Legacy Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Убрать из приложения всю поверхность, которая существует только ради совместимости с прежними сценариями (проверка упоминаний, сохранённые прогоны, прямой поиск Яндекса, `/api/form`), вместе с её таблицами в PostgreSQL и описанием в документации.

**Architecture:** Удаление идёт по потребителям, а не по слоям: сначала интерфейс и BFF перестают пользоваться ресурсами, затем снимаются HTTP-маршруты и их зависимости, затем сервисы, репозиторий и доменные модули, затем срезаются оставшиеся части живых модулей, и только последней ревизией Alembic уходят таблицы. Каждый шаг заканчивается зелёным прогоном и отдельным коммитом, поэтому промежуточные состояния репозитория рабочие.

**Tech Stack:** Python ≥ 3.13 (FastAPI, pydantic, psycopg, Alembic, pytest), SvelteKit 2 / Svelte 5 / TypeScript (Vitest, svelte-check, ESLint, Prettier).

**Spec:** `docs/superpowers/specs/2026-10-12-legacy-cleanup-design.md`

## Global Constraints

- Работаем напрямую в `main`, без worktree; отдельный коммит на задачу.
- Схему PostgreSQL создаёт и меняет только Alembic; приложение миграции не запускает.
- `docs/superpowers/{specs,plans}` не изменяются — это архив итераций.
- Слой совместимости с SQLite в `app/core/database.py` (`_translate`, `_IGNORED_PREFIXES`, `Positional Row`, `executescript`, `table_columns`) не трогаем. Удаляются только `require_project` и `Connection.executemany`, потерявшие последнего потребителя.
- Живые ресурсы обязаны остаться рабочими: `/api/projects*`, `/api/measurements*`, `/api/config`, `/api/providers`, `/api/providers/settings*`, `/api/search/settings`, `/api/search/settings/credentials`, `/api/seo/settings*`.
- Ключи не попадают ни в ответы API, ни в `providers.json`, ни в текст ошибок; сообщения об ошибках остаются фиксированными русскими строками.
- В этом окружении `uv` работает только с `UV_CACHE_DIR=/Users/adam977/repos/ai-tracker/.uv-cache`.
- Backend-тесты используют живой PostgreSQL с временной схемой; внешние HTTP-вызовы замоканы, платных запросов нет.
- Базовый путь сборки интерфейса (`AI_TRACKER_BASE_PATH`, `/clustering/tracker`) и относительные ссылки не затрагиваются.

## Review Focus

1. **Настройки Яндекса против удаления соседей.** `/api/search/settings` и `/api/search/settings/credentials` объявлены в отдельном роутере, но живут в том же префиксе, что и снимаемые `/api/search`, `/api/search/{job_id}`, `/api/search/regions`; после их удаления экран настроек обязан продолжать работать. Тест — Task 2, `test_the_search_settings_routes_survive_the_cleanup`.
2. **Ветка Яндекса в замере после срезки очереди.** `SearchSettingsService.gateway_snapshot()` и `enabled()` остаются единственным живым контрактом `SearchService`; замер с `yandex_enabled` обязан по-прежнему получать gateway. Тест — Task 4, прогон `tests/test_service_search_settings.py` и `tests/test_search_settings.py` плюс прогон `tests/test_projects_measurements.py`.
3. **Форма данных layout после удаления полей.** `loadPageData()` перестаёт возвращать `form` и `searchRegions`; страницы проекта должны продолжать получать `providers`, `SettingsPanel` — `settingsProviders`, `+layout.svelte` — настройки. Тест — Task 1, `keeps the fields the pages and the settings dialog consume`.
4. **Предохранитель миграции.** Непустая `runs` обязана остановить миграцию, а не потерять строки; `downgrade` обязан вернуть таблицы. Тест — Task 6, `test_the_migration_refuses_to_drop_saved_runs` и `test_the_legacy_tables_are_gone`.
5. **Согласованность тестовых фикстур со схемой.** `tests/conftest.py` перечисляет таблицы для `TRUNCATE`; после снятия таблиц этот список обязан измениться, иначе падает весь набор. Проверка — Task 6, полный прогон `pytest` зелёный.

---

### Task 1: Снять мёртвую поверхность интерфейса

**Files:**
- Delete: `frontend/src/routes/api/check/+server.ts`, `frontend/src/routes/api/form/+server.ts`, `frontend/src/routes/api/runs/+server.ts`, `frontend/src/routes/api/runs/[id]/+server.ts`, `frontend/src/routes/api/runs/[id]/export.csv/+server.ts`, `frontend/src/routes/api/search/+server.ts`, `frontend/src/routes/api/search/[id]/+server.ts`, `frontend/src/routes/api/search/regions/+server.ts`
- Delete: `frontend/src/lib/components/RunHistory.svelte`, `RunHistory.test.ts`, `RunResults.svelte`, `RunSummaryTable.svelte`, `RunSummaryTable.test.ts`, `SearchReport.svelte`, `SearchReport.test.ts`
- Delete: `frontend/src/lib/search-form.ts`, `frontend/src/lib/search-form.test.ts`
- Modify: `frontend/src/lib/types.ts`, `frontend/src/lib/server/python-api.ts`, `frontend/src/lib/server/python-api.test.ts`

**Interfaces:**
- Consumes: ничего из предыдущих задач.
- Produces: `loadPageData(): Promise<{ providers; settingsProviders; searchSettings; searchSettingsError; seoSettings; seoSettingsError; loadError }>` — поля `form`, `searchRegions`, `searchRegionError` исчезают; тип `ApiPath` без снятых путей. Задачи 3–6 на интерфейс больше не ссылаются.

- [ ] **Step 1: Написать падающие тесты отсутствия**

Добавить в `frontend/src/lib/server/python-api.test.ts` блок, а из списка статических импортов файла убрать `publicRunSnapshot`, `publicRunList`, `runPath`, `runListPath`, `runExportPath`, `searchPath`, `proxyCsv`, `publicSearchRegions`, `publicSearchSnapshot`:

```ts
describe('retired compatibility surface', () => {
  it('no longer exports the projections of removed resources', async () => {
    const api = (await import('./python-api')) as Record<string, unknown>;
    for (const name of [
      'publicRunCreated', 'publicRunSnapshot', 'publicRunList', 'publicCheck',
      'publicSearchCreated', 'publicSearchSnapshot', 'publicSearchRegions', 'publicForm',
      'runPath', 'runListPath', 'runExportPath', 'searchPath', 'proxyCsv',
    ])
      expect(api[name]).toBeUndefined();
  });

  it('rejects the retired paths before any upstream call', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    for (const path of ['/api/runs', '/api/check', '/api/form', '/api/search/regions'] as never[]) {
      const response = await proxyJson(new Request('http://127.0.0.1:5173/'), path, 'GET');
      expect(response.status).toBe(400);
    }
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd frontend && npx vitest run src/lib/server/python-api.test.ts`
Expected: FAIL — символы ещё экспортируются, снятые пути проходят проверку.

- [ ] **Step 3: Удалить маршруты BFF, компоненты и `search-form`**

Удалить все файлы из списка `Delete` выше (девять маршрутов, семь файлов компонентов, два файла `search-form`).

- [ ] **Step 4: Почистить `types.ts`**

Из объединения `ApiPath` убрать `/api/check`, `/api/form`, `/api/search`, `/api/search/regions`, `/api/runs`, `` `/api/runs?cursor=${string}` ``, `` `/api/runs/${string}` ``, `` `/api/search/${string}` ``. Удалить типы `FormConfig`, `SearchRegion`, `SearchCreated`, `SearchSnapshot`, `RunCreated`, `RunHistoryItem`, `RunHistoryPage`, `RunModelRow`, `RunSearchRow`, `RunSnapshot`, `RunStatus`, `SearchJobStatus`, `SearchRowStatus` и `SearchRow`. Одноимённый `SearchRow` в `frontend/src/lib/project-types.ts` **остаётся** — он описывает живой разрез замера.

- [ ] **Step 5: Почистить `python-api.ts`**

Удалить `runPath`, `runExportPath`, `runListPath`, `searchPath`, `publicRunCreated`, `publicRunSnapshot`, `publicRunList`, `publicCheck`, `publicSearchCreated`, `publicSearchSnapshot`, `publicSearchRegions`, `publicForm`, `proxyCsv`, `loadSearchRegions`, константу `MAX_CSV_BYTES` и внутренние парсеры снятых типов. Из `validPath` убрать ветки снятых путей, из `apiTimeoutMs` — ветку `/api/check`. В `loadPageData` убрать запрос `/api/form`, поля `form`, `searchRegions`, `searchRegionError` и соответствующие импорты типов.

- [ ] **Step 6: Удалить кейсы снятых ресурсов из `python-api.test.ts`**

Убрать тесты, ссылающиеся на удалённые экспорты и пути (в том числе «allows only opaque job IDs in search paths», «rejects unknown search paths», кейсы CSV-выгрузки, `runs`-проекций, `search`-снапшотов). В тестах `loadPageData` убрать проверки `data.form` и ожидания запроса `/api/search/regions` и добавить отдельный тест на форму данных, которую читают страницы проекта и диалог настроек (Review Focus 3):

```ts
it('keeps the fields the pages and the settings dialog consume', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      if (String(url).endsWith('/api/providers')) return Promise.resolve(jsonResponse([]));
      if (String(url).endsWith('/api/providers/settings')) return Promise.resolve(jsonResponse([]));
      if (String(url).endsWith('/api/search/settings'))
        return Promise.resolve(jsonResponse(publicSearchState));
      if (String(url).endsWith('/api/seo/settings'))
        return Promise.resolve(
          jsonResponse({
            endpoint: 'https://api.example.com/chat/completions',
            model: 'm',
            has_api_key: true,
            endpoint_source: 'ui',
            model_source: 'ui',
            api_key_source: 'ui',
          }),
        );
      return Promise.resolve(new Response('nope', { status: 500 }));
    }),
  );
  const data = await loadPageData();
  expect(Object.keys(data).sort()).toEqual([
    'loadError', 'providers', 'searchSettings', 'searchSettingsError',
    'seoSettings', 'seoSettingsError', 'settingsProviders',
  ]);
  expect(data.providers).toEqual([]);
  expect(data.loadError).toBe('');
});
```

Вспомогательная функция объявляется рядом с тестом: `const jsonResponse = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } });`

- [ ] **Step 7: Прогнать тесты**

Run: `cd frontend && npx vitest run`
Expected: PASS, включая два новых теста отсутствия.

- [ ] **Step 8: Проверить типы и сборку**

Run: `cd frontend && npm run check && npm run build`
Expected: обе команды без ошибок; сборка создаёт `frontend/build`.

- [ ] **Step 9: Коммит**

```bash
git add -A frontend
git commit -m "refactor(frontend): drop the retired BFF routes and components"
```

---

### Task 2: Снять мёртвый HTTP-контур backend

**Files:**
- Delete: `backend/app/api/routers/{checks,runs,search,form}.py`, `backend/app/api/schemas/{checks,runs,search,form}.py`, `backend/tests/{test_api_checks,test_api_runs,test_api_search}.py`
- Modify: `backend/app/api/router.py`, `backend/app/api/schemas/__init__.py`, `backend/app/api/deps/dependencies.py`, `backend/app/api/deps/__init__.py`, `backend/tests/test_main.py`, `backend/tests/test_api_deps.py`, `backend/tests/test_api_schemas.py`

**Interfaces:**
- Consumes: ничего из Task 1.
- Produces: набор маршрутов без `/api/check`, `/api/runs*`, `/api/search`, `/api/search/{job_id}`, `/api/search/regions`, `/api/form`; `app.api.deps.__all__` без `CheckServiceDep`, `FormServiceDep`, `RunServiceDep`, `SearchServiceDep` и их аксессоров. `Container`, сервисы и `core/errors.py` на этом шаге не меняются.

- [ ] **Step 1: Написать падающие тесты**

В `backend/tests/test_main.py` добавить `import pytest` и тест:

```python
@pytest.mark.parametrize(
    "path",
    ["/api/check", "/api/form", "/api/runs", "/api/search/regions"],
)
def test_the_retired_routes_are_gone(client, path):
    assert client.get(path).status_code == 404
```

В `backend/tests/test_main.py` заменить проверку `assert client.get("/api/form").status_code == 200` в `test_the_api_lives_under_a_prefix` на `assert client.get("/api/providers").status_code == 200`.

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd backend && UV_CACHE_DIR=/Users/adam977/repos/ai-tracker/.uv-cache uv run pytest tests/test_main.py -q`
Expected: FAIL — `/api/check` отвечает 405, `/api/form` 200, `/api/runs` 200, `/api/search/regions` 200.

- [ ] **Step 3: Удалить роутеры, схемы и их тесты**

Удалить файлы из списка `Delete` выше.

- [ ] **Step 4: Почистить сборку маршрутов и схем**

`app/api/router.py`: убрать `include_router` для `checks`, `runs`, `search`, `form` и соответствующие импорты. `app/api/schemas/__init__.py`: убрать импорты и имена `checks`, `form`, `search` из `__all__`; `common`, `providers` остаются.

- [ ] **Step 5: Почистить зависимости**

`app/api/deps/dependencies.py`: удалить `get_check_service`, `get_form_service`, `get_run_service`, `get_search_service` и алиасы `CheckServiceDep`, `FormServiceDep`, `RunServiceDep`, `SearchServiceDep` вместе с их типами-импортами. `app/api/deps/__init__.py`: убрать их из импортов и `__all__`.

- [ ] **Step 6: Перенацелить тесты схем на живые ресурсы**

`tests/test_api_schemas.py`:
- в импортах оставить только `ProviderResponse`, убрать `CheckResponse`, `FormResponse` и константы `BROWSER_FORM_FIELDS`, `BROWSER_CHECK_FIELDS`;
- удалить `test_form_payload_carries_exactly_the_documented_fields` и `test_check_payload_carries_exactly_the_documented_fields`;
- `test_a_wrong_typed_body_is_rejected_as_400_not_422` → `client.post("/api/projects", json={"brand": "Ромашка", "site_url": "https://example.com", "queries": "не список"})`, ожидание `{"detail": "Некорректное поле «queries»"}`;
- `test_a_missing_required_field_is_rejected_as_400` → `client.post("/api/projects", json={"site_url": "https://example.com"})`, ожидание `{"detail": "Некорректное поле «brand»"}`;
- `test_a_missing_body_is_rejected_as_400` → `client.post("/api/projects")`, ожидание `{"detail": "Некорректный запрос"}`;
- `test_a_rejected_schema_never_reaches_the_service` → то же тело `{"brand": "Ромашка", "site_url": "https://example.com", "queries": "не список"}`, проверка `spy.keys == []`;
- в `test_openapi_documents_every_operation` заменить набор путей на:

```python
    assert set(spec["paths"]) == {
        "/api/projects", "/api/projects/{id}", "/api/projects/{id}/measurements", "/api/projects/{id}/generate", "/api/projects/import-prompts",
        "/api/measurements/{id}", "/api/measurements/{id}/rows", "/api/measurements/{id}/cancel",
        "/api/config",
        "/api/providers", "/api/providers/{connection_id}",
        "/api/providers/settings", "/api/providers/settings/{group_id}",
        "/api/search/settings", "/api/search/settings/credentials",
        "/api/seo/settings", "/api/seo/settings/credentials", "/api/seo/settings/test",
    }
```

и в цикле имён компонентов оставить `ProviderWriteRequest`, `ProviderResponse`, `ErrorResponse`, `SearchSettingsWriteRequest`, `SearchSettingsResponse`, `YandexSettingsResponse`, `SeoSettingsWriteRequest`, `SeoSettingsResponse`, `SeoSettingsTestResponse`.

- [ ] **Step 7: Перенацелить тесты ошибок и обновить `test_api_deps.py`**

`tests/test_main.py`: импорт `get_check_service` заменить на `get_provider_settings_service`;
- `test_an_application_error_is_reported_as_one_string` → `client.post("/api/providers/settings", json={})`, ожидание 400 и `{"detail": "Укажите название до 100 символов"}`;
- `test_an_unexpected_error_stays_json_shaped_and_silent` → `app.dependency_overrides[get_provider_settings_service] = lambda: Broken()`, тело `json={}`, ожидание 500 и `{"detail": "Внутренняя ошибка сервиса"}`.

`tests/test_api_deps.py`: из `DEPENDENCIES` убрать `CheckServiceDep`, `FormServiceDep`, `RunServiceDep`, `SearchServiceDep`; из словаря `fields` в `test_the_routers_get_the_service_their_alias_names` — `checks`, `form`, `runs`, `search` (для `SearchServiceDep`; поле `search` контейнера остаётся, но его alias удалён).

- [ ] **Step 8: Добавить тест живой границы настроек Яндекса (Review Focus 1)**

В `tests/test_main.py`:

```python
def test_the_search_settings_routes_survive_the_cleanup(client):
    assert client.get("/api/search/settings").status_code == 200
    assert client.delete("/api/search/settings/credentials").status_code == 200
```

- [ ] **Step 9: Прогнать набор**

Run: `cd backend && UV_CACHE_DIR=/Users/adam977/repos/ai-tracker/.uv-cache uv run pytest -q`
Expected: PASS.

- [ ] **Step 10: Коммит**

```bash
git add -A backend
git commit -m "refactor(api): drop the retired check, runs, search and form routes"
```

---

### Task 3: Убрать сервисы, репозиторий и домен снятых сценариев

**Files:**
- Delete: `backend/app/service/{checks,runs,run_export,form}.py`, `backend/app/db/runs.py`, `backend/app/domain/{runs,report,requests}.py`, `backend/tests/{test_service_checks,test_service_runs,test_db_runs,test_domain_runs,test_domain_report,test_run_export}.py`
- Modify: `backend/app/api/deps/container.py`, `backend/app/main.py`, `backend/tests/test_main.py`, `backend/tests/test_api_deps.py`

**Interfaces:**
- Consumes: набор маршрутов из Task 2 (на удаляемые сервисы больше никто не ссылается).
- Produces: `Container` без полей `checks`, `runs`, `form`; в `app.state.container` остаются `settings`, `repository`, `connections`, `provider_settings`, `config`, `search`, `runs`-репозитория нет, `search_client`, `search_settings`, `seo_settings`, `projects`, `project_generation`, `measurements`.

- [ ] **Step 1: Написать падающий тест отсутствия**

В `backend/tests/test_api_deps.py`:

```python
def test_the_container_drops_the_retired_services():
    assert {"checks", "runs", "form"}.isdisjoint(deps.Container.__dataclass_fields__)
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && UV_CACHE_DIR=/Users/adam977/repos/ai-tracker/.uv-cache uv run pytest tests/test_api_deps.py -q`
Expected: FAIL — поля ещё существуют.

- [ ] **Step 3: Удалить сервисы, репозиторий, доменные модули и их тесты**

Удалить файлы из списка `Delete` выше.

- [ ] **Step 4: Почистить контейнер и `lifespan`**

`app/api/deps/container.py`: убрать импорты и поля `checks`, `runs`, `form`, создание `RunRepository`, вызов `run_repository.recover_unfinished()`, создание `CheckService`, `RunService`, `FormService` и передачу `runs` в `Container`. `app/main.py`: в `lifespan` убрать `await container.runs.close()`, сохранив закрытие `measurements`, `search`, `search_client` и `database.close_pools()`.

- [ ] **Step 5: Обновить тест `lifespan`**

В `tests/test_main.py` в `test_the_lifespan_closes_every_background_worker` убрать `runs` из `SimpleNamespace` и из проверки `(runs.closed, measurements.closed, search.closed)` → `(measurements.closed, search.closed) == (1, 1)`, сохранив проверку `assert measurements.closed == 0` внутри контекста.

- [ ] **Step 6: Прогнать набор**

Run: `cd backend && UV_CACHE_DIR=/Users/adam977/repos/ai-tracker/.uv-cache uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Коммит**

```bash
git add -A backend
git commit -m "refactor(backend): drop the services and domain of retired flows"
```

---

### Task 4: Срезать очередь поисковых заданий

**Files:**
- Modify: `backend/app/service/search.py`, `backend/app/domain/search.py`, `backend/app/core/errors.py`, `backend/app/api/errors.py`, `backend/tests/conftest.py`
- Delete: `backend/tests/test_service_search.py`
- Test: `backend/tests/test_service_search_gateway.py` (создать)

**Interfaces:**
- Consumes: Task 3 (единственные потребители очереди — удалённые `RunService` и роутер `/api/search`).
- Produces: `SearchService` с `__init__(self, gateway: SearchGateway | None)`, `configure(gateway, enabled)`, атрибутами `gateway`, `enabled` и `close()`. `domain/search.py` сохраняет `SearchGateway`, `SearchDocument`, `KNOWN_REGION_IDS`, `ALLOWED_SCHEMES`, `first_matching_result`, `result_url_host`, `normalize_search_host`, `TOP_RESULTS`. `SearchJobNotFound` исчезает из `app/core/errors.py` и из `STATUS_BY_ERROR`.

- [ ] **Step 1: Написать падающий тест живого контракта**

Создать `backend/tests/test_service_search_gateway.py`:

```python
"""The search service is only the gateway holder the settings and measurement need."""

import pytest

from app.service.search import SearchService


@pytest.mark.anyio
async def test_the_service_only_holds_the_configured_gateway():
    service = SearchService(None)
    assert service.gateway is None
    assert service.enabled is True  # Настройки по умолчанию считают Яндекс доступным.
    service.configure("gateway-sentinel", True)
    assert service.gateway == "gateway-sentinel"
    service.configure(None, False)
    assert service.enabled is False
    await service.close()


def test_the_job_queue_is_gone():
    for name in ("start", "snapshot", "abort"):
        assert not hasattr(SearchService, name)
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && UV_CACHE_DIR=/Users/adam977/repos/ai-tracker/.uv-cache uv run pytest tests/test_service_search_gateway.py -q`
Expected: FAIL на `test_the_job_queue_is_gone` — методы очереди ещё есть.

- [ ] **Step 3: Срезать `service/search.py`**

Оставить `SearchService` в таком виде: `__init__(self, gateway: SearchGateway | None)` со `self.gateway = gateway` и `self.enabled = True`, метод `configure(self, gateway, enabled)`, асинхронный `close()` без задач (безопасный при повторном вызове) и `__all__ = ["SearchService"]`. Удалить реестр заданий (`InMemorySearchJobStore`), ограничитель частоты (`AsyncRequestRateLimiter`), TTL и периодическую очистку, `start`, `snapshot`, `abort`, `_create_job`, `_drop_expired`, `_task_done`, `_cleanup_expired_periodically`, `_run`, `_run_pair`, модели `SearchJob`/`SearchJobState`/`SearchRow` и словарь статусов, а также `SearchJobNotFound` из импортов. Импортирующие модули после Tasks 2–3: `container.py` (`SearchService(None)`), `service/search_settings.py`, `tests/test_service_search_settings.py`.

- [ ] **Step 4: Почистить `domain/search.py`**

Удалить `SearchInput`, `normalize_search_request`, `_normalize_prompts`, `_normalize_regions`, `_normalize_region_targets`, `_host` и сообщения валидации запроса, на которые больше никто не ссылается. Оставить протокол `SearchGateway`, `SearchDocument`, `KNOWN_REGION_IDS`, `ALLOWED_SCHEMES`, `first_matching_result`, `result_url_host`, `normalize_search_host`, `TOP_RESULTS`. Проверить отсутствие висящих импортов `LIMITS` и `MAX_PROMPTS_TEXT_LENGTH` после удаления (если они остались только в удалённых функциях — убрать из импортов строки).

- [ ] **Step 5: Убрать `SearchJobNotFound`**

`app/core/errors.py`: удалить класс. `app/api/errors.py`: удалить его из импортов и из `STATUS_BY_ERROR`.

- [ ] **Step 6: Удалить тесты очереди и обновить комментарий фикстуры**

Удалить `backend/tests/test_service_search.py` (все его кейсы описывают очередь). В `tests/conftest.py` в докстроке `make_client` заменить «the search service keeps job state in memory, so every request of one client must reach the same service» на «the container is built once per client, so every request of one client reaches the same services».

- [ ] **Step 7: Прогнать затронутые наборы**

Run: `cd backend && UV_CACHE_DIR=/Users/adam977/repos/ai-tracker/.uv-cache uv run pytest tests/test_service_search_gateway.py tests/test_service_search_settings.py tests/test_search_settings.py tests/test_projects_measurements.py -q`
Expected: PASS — включая ветку Яндекса в замере (Review Focus 2).

- [ ] **Step 8: Прогнать весь набор**

Run: `cd backend && UV_CACHE_DIR=/Users/adam977/repos/ai-tracker/.uv-cache uv run pytest -q`
Expected: PASS.

- [ ] **Step 9: Коммит**

```bash
git add -A backend
git commit -m "refactor(search): keep only the gateway holder the app still uses"
```

---

### Task 5: Убрать оставшиеся мёртвые доменные и БД-хелперы

**Files:**
- Modify: `backend/app/domain/models.py`, `backend/app/domain/__init__.py`, `backend/app/domain/matching.py`, `backend/app/domain/limits.py`, `backend/app/core/database.py`, `backend/app/core/errors.py`, `backend/app/api/errors.py`, `backend/tests/test_domain_matching.py`
- Test: `backend/tests/test_domain_removed_helpers.py` (создать)

**Interfaces:**
- Consumes: Task 3 и Task 4 (последние потребители удаляемых имён исчезли).
- Produces: `app.domain.models.Connection` без изменений; `app.domain.__init__` реэкспортирует только `Connection`; `app.domain.matching` без `mentions_brand`; `app.domain.limits` без `LIMITS` и `MAX_PROMPTS_TEXT_LENGTH`; `app.core.database` без `require_project` и `Connection.executemany`.

- [ ] **Step 1: Написать падающий тест отсутствия**

Создать `backend/tests/test_domain_removed_helpers.py`:

```python
"""Names that only the retired flows used are gone."""

from app.core import database
from app.domain import limits, matching, models


def test_the_retired_domain_names_are_gone():
    assert not hasattr(matching, "mentions_brand")
    assert not hasattr(limits, "LIMITS")
    assert not hasattr(limits, "MAX_PROMPTS_TEXT_LENGTH")
    for name in ("CheckInput", "CheckReport", "CheckSummary", "PromptResult", "ProviderCheck"):
        assert not hasattr(models, name)


def test_the_retired_database_helpers_are_gone():
    assert not hasattr(database, "require_project")
    assert not hasattr(database.Connection, "executemany")
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && UV_CACHE_DIR=/Users/adam977/repos/ai-tracker/.uv-cache uv run pytest tests/test_domain_removed_helpers.py -q`
Expected: FAIL на первом же отсутствующем имени.

- [ ] **Step 3: Почистить домен**

`app/domain/models.py`: удалить `CheckInput`, `CheckReport`, `CheckSummary`, `PromptResult`, `ProviderCheck` и константы `RESULT_ABSENT`, `RESULT_ERROR`, `RESULT_MENTIONED`; `Connection` и его импорты остаются. `app/domain/__init__.py`: оставить единственный реэкспорт `Connection` из `models`, убрав `LIMITS` и все имена проверки из импортов и `__all__`. `app/domain/matching.py`: удалить `mentions_brand`, поправив докстроку модуля — там остаётся только матчер ИИ-трекера. `app/domain/limits.py`: удалить `LIMITS` и `MAX_PROMPTS_TEXT_LENGTH`, оставив `MAX_API_KEY_LENGTH`, `MAX_NAME_LENGTH`, `MAX_MODEL_LENGTH`, `MAX_ENDPOINT_LENGTH`, и переписав докстроку модуля (лимиты больше не отдаются браузеру).

- [ ] **Step 4: Почистить БД и ошибки**

`app/core/database.py`: удалить `require_project`, метод `Connection.executemany` и упоминания обоих в докстроке модуля. `app/core/errors.py`: удалить `ChatNotFound`. `app/api/errors.py`: удалить `ChatNotFound` из импортов и из `STATUS_BY_ERROR`.

- [ ] **Step 5: Почистить тесты матчинга**

В `backend/tests/test_domain_matching.py` убрать импорт `mentions_brand` и два его утверждения, сохранив кейсы `mentions_phrase`, `normalize_text` и `mentions_host`.

- [ ] **Step 6: Прогнать набор**

Run: `cd backend && UV_CACHE_DIR=/Users/adam977/repos/ai-tracker/.uv-cache uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Коммит**

```bash
git add -A backend
git commit -m "refactor(domain): remove the helpers left without consumers"
```

---

### Task 6: Снять legacy-таблицы миграцией

**Files:**
- Create: `backend/migrations/versions/0002_drop_legacy_runs.py`, `backend/tests/test_migration_legacy_drop.py`
- Modify: `backend/tests/conftest.py:52-62`

**Interfaces:**
- Consumes: Task 3 и Task 5 (в коде не осталось обращений к `runs`, `model_rows`, `search_rows`).
- Produces: ревизия `0002_drop_legacy_runs` с `down_revision = "0001_projects_root"`; `run_alembic(dsn, *args) -> subprocess.CompletedProcess` из нового тестового файла и `legacy_tables(dsn) -> set[str]`.

- [ ] **Step 1: Написать падающие тесты**

Создать `backend/tests/test_migration_legacy_drop.py`:

```python
"""The legacy run tables leave the schema, and saved rows stop the drop."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from app.core import database
from tests.conftest import BASE_DSN, schema_dsn

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
FUSE_MESSAGE = "В таблице runs есть сохранённые прогоны"


def legacy_tables(dsn: str) -> set[str]:
    with database.connect(dsn) as connection:
        rows = connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()"
        ).fetchall()
    return {row["table_name"] for row in rows}


def run_alembic(dsn: str, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *arguments],
        cwd=BACKEND_ROOT,
        env={**os.environ, "AI_TRACKER_DATABASE_URL": dsn},
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_legacy_tables_are_gone(database_dsn):
    assert legacy_tables(database_dsn).isdisjoint({"runs", "model_rows", "search_rows"})


def test_the_migration_refuses_to_drop_saved_runs():
    name = "guard_" + uuid4().hex[:12]
    dsn = schema_dsn(BASE_DSN, name)
    admin = database.connect(BASE_DSN, autocommit=True)
    try:
        admin.execute(f'CREATE SCHEMA "{name}"')
        assert run_alembic(dsn, "upgrade", "0001_projects_root").returncode == 0
        with database.connect(dsn) as connection:
            connection.execute(
                "INSERT INTO projects VALUES(?,?,?,?,?)", ("p1", "{}", 1, "now", "now")
            )
            connection.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?)",
                ("r1", "p1", "now", None, "Бренд", "example.ru", "[]", "[]", "[]"),
            )
        result = run_alembic(dsn, "upgrade", "head")
        assert result.returncode != 0
        assert FUSE_MESSAGE in (result.stderr + result.stdout)
        assert "runs" in legacy_tables(dsn)
    finally:
        admin.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
        admin.close()
        # The pool opened for the guard schema must not outlive it.
        database.close_pools()
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd backend && UV_CACHE_DIR=/Users/adam977/repos/ai-tracker/.uv-cache uv run pytest tests/test_migration_legacy_drop.py -q`
Expected: FAIL — таблицы ещё в схеме, `upgrade head` завершается успешно.

- [ ] **Step 3: Написать миграцию**

Создать `backend/migrations/versions/0002_drop_legacy_runs.py`:

```python
"""Drop the tables of the retired runs and direct-search scenarios.

Revision ID: 0002_drop_legacy_runs
Revises: 0001_projects_root
"""

from __future__ import annotations

from alembic import op

revision = "0002_drop_legacy_runs"
down_revision = "0001_projects_root"
branch_labels = None
depends_on = None

FUSE_MESSAGE = (
    "В таблице runs есть сохранённые прогоны: удалите их вручную или "
    "откажитесь от этой миграции, чтобы не потерять данные"
)


def upgrade() -> None:
    saved = op.get_bind().exec_driver_sql("SELECT count(*) FROM runs").scalar()
    if saved:
        raise RuntimeError(FUSE_MESSAGE)
    for table in ("search_rows", "model_rows", "runs"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


def downgrade() -> None:
    # Structure only: the rows are gone for good, but the revision stays reversible.
    # The three statements are copied verbatim from `0001_projects_root.TABLES`:
    # first the `runs` entry (its `run_project_history` index is created right after
    # it in that module), then `model_rows`, then `search_rows`.
    for _name, statement in LEGACY_TABLES:
        op.execute(statement)
```

где `LEGACY_TABLES` — кортеж из трёх пар `(имя, DDL)`, скопированных из
`backend/migrations/versions/0001_projects_root.py` без изменений. Три `CREATE TABLE`
в `downgrade` должны совпадать с исходными по колонкам, типам и `REFERENCES`, иначе
следующий `upgrade head` пройдёт, но схема будет не той, что описана в `0001`.

- [ ] **Step 4: Обновить список таблиц в фикстурах**

`backend/tests/conftest.py`: `APPLICATION_TABLES` → `("project_search_rows", "project_model_rows", "project_measurements", "projects")`; комментарий над константой оставить в силе.

- [ ] **Step 5: Прогнать весь набор**

Run: `cd backend && UV_CACHE_DIR=/Users/adam977/repos/ai-tracker/.uv-cache uv run pytest -q`
Expected: PASS; фикстура `clean_database` больше не называет снятые таблицы (Review Focus 5).

- [ ] **Step 6: Проверить миграцию в обе стороны на рабочей базе**

Run:
```bash
cd backend && UV_CACHE_DIR=/Users/adam977/repos/ai-tracker/.uv-cache uv run alembic upgrade head \
  && UV_CACHE_DIR=/Users/adam977/repos/ai-tracker/.uv-cache uv run alembic downgrade -1 \
  && UV_CACHE_DIR=/Users/adam977/repos/ai-tracker/.uv-cache uv run alembic upgrade head
```
Expected: все три команды успешны; в рабочей базе legacy-таблицы пусты, поэтому предохранитель не срабатывает.

- [ ] **Step 7: Коммит**

```bash
git add -A backend
git commit -m "feat(migrations): drop the legacy runs tables with a data fuse"
```

---

### Task 7: Синхронизировать документацию

**Files:**
- Modify: `README.md`, `tech.md`, `backend/README.md`, `frontend/README.md`, `qa/README.md`

**Interfaces:**
- Consumes: Tasks 1–6 (описанного в документации кода больше нет).
- Produces: документация, описывающая только актуальный продукт.

- [ ] **Step 1: Обновить корневой README**

Удалить разделы «Как проверяется выдача (совместимость)» и «Ограничения отложенного режима (совместимость)» целиком. Из разделов «Проекты», «Ключи» и «Отмена и сохранность данных» убрать оговорки про сохранённые прогоны, прямой поиск и API совместимости. В разделе «Документация» оставить ссылки на актуальные документы слоёв.

- [ ] **Step 2: Обновить `tech.md`**

Из §5 убрать таблицу «Совместимость: проверки, прямой поиск и сохранённые прогоны» и упоминания `/api/runs`, `/api/search`, `/api/check`, `/api/form` из основного списка. Из §1 убрать пункт «Отдельные API остаются». Пересчитать бюджеты и карту репозитория там, где упомянуты снятые модули.

- [ ] **Step 3: Обновить README слоёв**

`backend/README.md`: убрать описания `/api/check`, `/api/runs`, `/api/search`, `/api/form` и соответствующих слоёв (`service/checks.py`, `service/runs.py`, `db/runs.py`, `domain/report.py`). `frontend/README.md`: убрать абзац про исторические компоненты `RunHistory`/`RunResults`/`RunSummaryTable`/`SearchReport`, убрать `/api/runs`, `/api/check`, `/api/form`, `/api/search/regions` из перечня BFF-маршрутов и пересчитать число тестовых файлов после Task 1.

- [ ] **Step 4: Обновить README браузерных проверок**

`qa/README.md`: убрать упоминания удалённых наборов и API-совместимости; оставить описание изолированного сценария `tests/test_projects.py` и проверку настроек на живом инстансе.

- [ ] **Step 5: Проверить отсутствие осиротевших упоминаний**

Run:
```bash
grep -rn "api/runs\|api/check\|/api/form\|RunHistory\|SearchReport\|RunSummaryTable" README.md tech.md backend/README.md frontend/README.md qa/README.md || echo "clean"
```
Expected: `clean`.

- [ ] **Step 6: Коммит**

```bash
git add README.md tech.md backend/README.md frontend/README.md qa/README.md
git commit -m "docs: describe only the current product"
```

---

### Task 8: Финальная проверка

**Files:**
- Modify: только если проверка выявит пропущенное — исправления вносятся здесь же.

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces: подтверждённое состояние «готово к деплою».

- [ ] **Step 1: Полный поиск осиротевших ссылок**

Run:
```bash
grep -rn "api/runs\|api/check\|/api/form\|/api/search/regions\|RunHistory\|RunSummaryTable\|RunResults\|SearchReport\|publicCheck\|publicRunList\|mentions_brand\|CheckService\|RunService\|FormService\|ChatNotFound\|SearchJobNotFound" \
  --include=*.py --include=*.ts --include=*.svelte --include=*.md \
  backend/app backend/tests frontend/src qa README.md tech.md backend/README.md frontend/README.md qa/README.md \
  || echo "clean"
```
Expected: `clean`. Любое совпадение — исправить и вернуться к проверке.

- [ ] **Step 2: Проверки интерфейса**

Run: `make check && cd frontend && npx vitest run && npm run build`
Expected: типы, форматирование, линт, тесты и сборка без ошибок.

- [ ] **Step 3: Проверки backend**

Run: `cd backend && UV_CACHE_DIR=/Users/adam977/repos/ai-tracker/.uv-cache uv run pytest -q`
Expected: PASS, ни одного пропущенного или упавшего теста.

- [ ] **Step 4: Убедиться, что схема на head и без legacy-таблиц**

Run:
```bash
cd backend && UV_CACHE_DIR=/Users/adam977/repos/ai-tracker/.uv-cache uv run alembic current
/Applications/Postgres.app/Contents/Versions/latest/bin/psql "postgresql://adam977@localhost:5432/ai-tracker" -tAc \
  "select table_name from information_schema.tables where table_schema='public' order by 1"
```
Expected: `0002_drop_legacy_runs (head)`; в списке таблиц нет `runs`, `model_rows`, `search_rows`.

- [ ] **Step 5: Живой smoke-тест**

Перезапустить dev-серверы, чтобы они подняли новый код (это остановит текущие процессы на `:8000` и `:5173`): перезапустить `make backend` и `make frontend` как фоновые задачи. Затем:

```bash
for path in /api/projects /api/providers /api/config /api/search/settings /api/seo/settings; do
  printf '%s %s\n' "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000$path)" "$path"
done
for path in /api/runs /api/check /api/form /api/search/regions; do
  printf '%s %s\n' "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000$path)" "$path"
done
```
Expected: пять живых путей отвечают `200`; четыре снятых — `404`.

- [ ] **Step 6: Проверить интерфейс в браузере**

Открыть `http://127.0.0.1:5173/`: видны карточки проектов, открывается диалог «Настройки API» с вкладками подключений, поисковых систем и служебной LLM, ошибок в консоли нет.

- [ ] **Step 7: Убедиться в чистоте рабочего дерева**

Run: `git status --porcelain -uall`
Expected: пусто; все изменения закоммичены по задачам.
