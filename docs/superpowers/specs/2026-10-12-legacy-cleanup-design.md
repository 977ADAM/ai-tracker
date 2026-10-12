# Чистка legacy-инвентаря перед деплоем

Дата: 2026-10-12. Статус: дизайн согласован, ожидает ревью спецификации.

## Цель

Подготовить приложение к деплою, убрав из репозитория всю поверхность, которая
существует только ради совместимости с прежними сценариями (проверка упоминаний,
сохранённые прогоны, прямой поиск Яндекса, старый `/api/form`). На этом этапе
обратная совместимость не требуется: снятые сценарии не используются интерфейсом,
их таблицы пусты, а документация описывает их как наследие.

## Согласованные решения

- **Объём чистки** — базовый: мёртвый API, его сервисы, репозитории и схемы, мёртвые
  компоненты интерфейса, снятие legacy-таблиц новой миграцией.
- **Вне чистки** — переустройство слоя совместимости с SQLite в `core/database.py`:
  трансляция `?` → `%s`, игнорируемые `begin`/`commit`/`pragma`, позиционный доступ
  `Row`, `executescript` и `table_columns` остаются на месте, даже если часть из них
  уже без потребителей. Переименование `seo_*` в имена служебной LLM тоже отложено.
  При этом хелперы, которые теряют последнего потребителя именно из-за этой чистки
  (`require_project`, `Connection.executemany`), удаляются — см. «Хирургия».
- **«Серая зона»** — `/api/form` и `/api/search/regions` тоже удаляются как мёртвые.
- **Архив** — `docs/superpowers/{specs,plans}` не трогаем: это история итераций.
- **Объём подготовки к деплою** — только чистка плюс синхронизация документации и QA.
  Healthcheck, переменные окружения, инструкция развёртывания и проверка сборки
  образов в этот заход не входят.

## Доказательства, на которых построен дизайн

- Таблицы `runs`, `model_rows`, `search_rows` содержат 0 строк; данные есть только в
  `projects` (2 строки) и `project_measurements` (1 строка).
- Компоненты `RunHistory`, `RunResults`, `RunSummaryTable`, `SearchReport` не
  импортируются ни одним маршрутом или компонентом — только собственными тестами.
- `loadPageData()` тянет `/api/form` и `/api/search/regions` на каждой загрузке
  страницы, но `FormConfig` и `SearchRegion` встречаются только в `types.ts` и
  `python-api.ts`; список регионов в форме и мастере задан локальным массивом.
- `domain/report.py` используется только `service/checks.py`; `domain/requests.py` —
  только `service/checks.py` и `domain/runs.py`; `RunNotFound` и `RunConflict`
  используются замером и остаются.
- `core/database.require_project` вызывается только из `db/runs.py`;
  `Connection.executemany` — тоже только оттуда.
- Задача Яндекса в замере работает напрямую через `gateway.submit/result`
  ([measurement_worker.py](../../../backend/app/service/measurement_worker.py)), а не
  через очередь задач `SearchService`.

## Что удаляется

### HTTP API

| Маршрут | Причина |
| --- | --- |
| `POST /api/check` | Прежняя проверка упоминаний; интерфейс её не использует |
| `GET`, `POST /api/runs`, `GET`, `DELETE /api/runs/{id}`, `GET /api/runs/{id}/export.csv` | Сохранённые прогоны прежней формы |
| `POST /api/search`, `GET /api/search/{job_id}` | Прямой поиск Яндекса в памяти процесса |
| `GET /api/search/regions` | Справочник не читается интерфейсом |
| `GET /api/form` | Параметры прежней проверки не читаются интерфейсом |

### Файлы backend

- `app/api/routers/{checks,runs,search,form}.py`
- `app/api/schemas/{checks,runs,search,form}.py`
- `app/service/{checks,runs,run_export,form}.py`
- `app/db/runs.py`
- `app/domain/{runs,report,requests}.py`

### Файлы frontend

- Компоненты и их тесты: `RunHistory.svelte` + `.test.ts`, `RunResults.svelte`,
  `RunSummaryTable.svelte` + `.test.ts`, `SearchReport.svelte` + `.test.ts`
- `src/lib/search-form.ts` и `src/lib/search-form.test.ts`
- BFF-маршруты: `src/routes/api/check/`, `src/routes/api/form/`,
  `src/routes/api/runs/**`, `src/routes/api/search/+server.ts`,
  `src/routes/api/search/[id]/`, `src/routes/api/search/regions/`

### Тесты backend

Удаляются целиком: `test_api_checks.py`, `test_api_runs.py`, `test_api_search.py`,
`test_db_runs.py`, `test_domain_runs.py`, `test_domain_report.py`,
`test_run_export.py`, `test_service_checks.py`, `test_service_runs.py`.

## Хирургия в живых модулях

Эти файлы остаются, но теряют только те части, у которых не остаётся потребителей.

| Файл | Что уходит |
| --- | --- |
| `app/api/router.py` | Четыре `include_router` |
| `app/api/schemas/__init__.py` | Импорты и имена в `__all__` для checks, runs, search, form |
| `app/api/deps/container.py` | Поля `checks`, `runs`, `form`; создание `RunRepository`, `CheckService`, `RunService`, `FormService` |
| `app/api/deps/dependencies.py` | `get_check_service`, `get_run_service`, `get_form_service`, `get_search_service` и их `*Dep`-алиасы |
| `app/api/deps/__init__.py` | Реэкспорты удалённых зависимостей |
| `app/api/errors.py` | Отображения `SearchJobNotFound` и `ChatNotFound` |
| `app/core/errors.py` | `SearchJobNotFound`, `ChatNotFound` |
| `app/main.py` | `await container.runs.close()` в `lifespan` |
| `app/service/search.py` | Очередь задач: реестр заданий, ограничитель частоты, TTL и очистка, `start`, `snapshot`, `abort`, `_run`, `_run_pair`, модели задания и его статусов. Остаются `configure`, `gateway`, `enabled`, `close` — их использует `service/search_settings.py` |
| `app/domain/search.py` | Нормализация запроса поиска и словарь статусов задания; остаются протокол `SearchGateway`, `KNOWN_REGION_IDS`, `ALLOWED_SCHEMES`, `SearchDocument`, `first_matching_result`, `result_url_host` |
| `app/domain/matching.py` | `mentions_brand` — матчер прежнего `/api/check` |
| `app/domain/models.py` | `CheckInput`, `CheckReport`, `CheckSummary`, `PromptResult`, `ProviderCheck`, константы `RESULT_*`; остаётся `Connection` |
| `app/domain/__init__.py` | Реэкспорты удалённых моделей проверки |
| `app/core/database.py` | `require_project` и `Connection.executemany` — единственным потребителем обоих был `db/runs.py`; вводная документация модуля приводится в соответствие |
| `app/domain/limits.py` | `LIMITS` (единственные потребители — `service/form.py` и удаляемая часть `domain/search.py`) и `MAX_PROMPTS_TEXT_LENGTH` (единственные потребители — `domain/requests.py` и удаляемая часть `domain/search.py`). Константы `MAX_API_KEY_LENGTH`, `MAX_NAME_LENGTH`, `MAX_MODEL_LENGTH`, `MAX_ENDPOINT_LENGTH` остаются: их используют `connections.py`, `provider_groups.py`, `seo_settings.py`, `endpoints.py`. Документация модуля перестаёт говорить о лимитах для браузера |

Слой совместимости с SQLite (`_translate`, `_IGNORED_PREFIXES`, `_split_script`,
`executescript`, `table_columns`, позиционный доступ `Row`) не трогаем: это
отложенный объём. Если после чистки `table_columns` и `executescript` окажутся без
потребителей, они остаются на месте осознанно и переезжают в отложенный заход.

### Frontend: правки живых файлов

- `src/lib/types.ts`: из объединения `ApiPath` уходят `/api/check`, `/api/form`,
  `/api/search`, `/api/search/regions`, `/api/runs`, `/api/runs?cursor=…`,
  `/api/runs/${string}`, `/api/search/${string}`; удаляются типы `FormConfig`,
  `SearchRegion`, `SearchCreated`, `SearchSnapshot`, `RunCreated`, `RunHistoryItem`,
  `RunHistoryPage`, `RunModelRow`, `RunSearchRow`, `RunSnapshot`, `RunStatus`,
  `SearchJobStatus`, `SearchRowStatus` и `SearchRow` **из `types.ts`**. Одноимённый
  `SearchRow` в `src/lib/project-types.ts` описывает живой разрез замера по поисковым
  строкам и остаётся вместе с `RowsPage`.
- `src/lib/server/python-api.ts`: удаляются `runPath`, `runExportPath`, `runListPath`,
  `searchPath`, `publicRunCreated`, `publicRunSnapshot`, `publicRunList`,
  `publicCheck`, `publicSearchCreated`, `publicSearchSnapshot`, `publicSearchRegions`,
  `publicForm`, `proxyCsv`, `loadSearchRegions`, поля `form` и `searchRegions` (вместе
  с `searchRegionError`) из `loadPageData`, ветки `validPath`, ветка `apiTimeoutMs`
  для `/api/check`, константы CSV-выгрузки. Остаются `providers`,
  `settingsProviders`, `searchSettings`, `searchSettingsError`, `seoSettings`,
  `seoSettingsError`, `loadError`: `providers` читают страницы проекта,
  `settingsProviders` — `SettingsPanel`, настройки — `+layout.svelte`.
- `src/lib/server/python-api.test.ts`: удаляются кейсы удалённых путей и проекций,
  остальные сохраняются.

## Миграция схемы

Новая ревизия `0002_drop_legacy_runs` (вниз от `0001_projects_root`):

1. Предохранитель: если в `runs` есть строки, миграция падает с сообщением, что
   legacy-данные требуют решения оператора. Так молчаливой потери данных не будет.
2. `DROP TABLE search_rows`, `DROP TABLE model_rows`, `DROP TABLE runs` — в порядке
   зависимостей.
3. `downgrade()` воссоздаёт три таблицы в исходном виде (пустыми), повторяя DDL из
   `0001_projects_root`. Обратимость по структуре сохраняется; данные не
   возвращаются — это следствие отказа от совместимости.

Проверка: `alembic upgrade head` с чистой схемы и с текущего состояния,
затем `alembic downgrade -1` и снова `upgrade head`.

## Порядок исполнения

Работаем напрямую в `main`, без worktree, минимальный регрессионный тест перед
кодом, отдельный коммит на шаг. Шаги идут по потребителям, схема — последней, чтобы
каждый шаг заканчивался зелёными тестами.

1. **Frontend-потребители.** Удаляются BFF-маршруты, компоненты, типы, функции
   `python-api.ts` и соответствующие тесты. Backend пока продолжает отдавать
   маршруты — это безопасно. Проверка: `npx vitest run`, `npm run check`,
   `npm run build`.
2. **API backend.** Удаляются роутеры, схемы, зависимости, поля контейнера,
   отображения ошибок, вызов `runs.close()` в `lifespan`. Проверка: `pytest`.
3. **Сервисы, домен, БД.** Срезается `service/search.py`, чистятся
   `domain/search.py`, `domain/models.py`, `domain/__init__.py`, `domain/matching.py`,
   `core/database.py`, `domain/limits.py`. Проверка: `pytest`.
4. **Миграция.** Ревизия `0002` и проверка upgrade/downgrade в обе стороны.
5. **Документация.** Синхронизация четырёх файлов и `qa/README.md`.
6. **Финальная проверка.** Полный набор команд, поиск осиротевших ссылок, живой
   smoke-тест сохранённых эндпоинтов.

## Тесты

- Удаляются: девять файлов backend (см. выше), четыре файла frontend
  (`RunHistory.test.ts`, `RunSummaryTable.test.ts`, `SearchReport.test.ts`,
  `search-form.test.ts`) плюс кейсы в `python-api.test.ts`.
- Правятся: `tests/test_main.py` — мок контейнера в тесте `lifespan` теряет `runs`,
  проверка `GET /api/form` → 200 переносится на живой маршрут, тесты обработки ошибок
  с `POST /api/check` переводятся на живой ресурс (например,
  `POST /api/providers/settings`) с той же проверкой формы ответа;
  `tests/test_api_deps.py` и `tests/test_api_schemas.py` — списки сервисов и схем;
  `tests/test_service_search.py` — остаются тесты живых методов, тесты очереди
  удаляются.
- Остаются гарантией поведения: замеры и проекты, конкурентность и блокировки,
  настройки подключений, поиска и служебной LLM, генерация, деплой-окружение,
  весь набор frontend кроме удалённых файлов, изолированный QA-сценарий
  `qa/tests/test_projects.py`.

## Документация

- `README.md`: удаляются разделы «Как проверяется выдача (совместимость)» и
  «Ограничения отложенного режима (совместимость)»; из разделов о проектах и ключах
  убираются оговорки про сохранённые API и прогоны.
- `tech.md`: из §5 убирается таблица совместимости, из §1 — пункт про отдельные API,
  из списка маршрутов и §7 — упоминания прогонов и поиска; карта репозитория
  приводится в соответствие.
- `backend/README.md`: убираются описания `/api/check`, `/api/runs`, `/api/search`,
  `/api/form` и связанных слоёв.
- `frontend/README.md`: убирается абзац про исторические компоненты, пересчитывается
  число тестовых файлов, обновляется перечень BFF-маршрутов и правил.
- `qa/README.md`: убираются упоминания удалённых наборов; сценарий
  `tests/test_add_provider.py` и проверка отсутствия `/settings` сохраняются.
- `docs/superpowers/{specs,plans}` не изменяются.

## Проверка и критерии приёмки

1. `make check` — без ошибок типов, форматирования и линта.
2. `cd backend && UV_CACHE_DIR=<repo>/.uv-cache uv run pytest` — зелёный.
3. `cd frontend && npx vitest run` — зелёный.
4. `cd frontend && npm run build` — сборка проходит.
5. `alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head` — все три
   команды завершаются успешно; после `upgrade head` таблиц `runs`, `model_rows`,
   `search_rows` в схеме нет.
6. Поиск по репозиторию не находит ссылок на `/api/runs`, `/api/check`,
   `/api/form`, `/api/search/regions`, `RunHistory`, `RunSummaryTable`, `RunResults`,
   `SearchReport`, `publicCheck`, `publicRunList`, `mentions_brand`,
   `CheckService`, `RunService`, `FormService`, `ChatNotFound`, `SearchJobNotFound`.
7. Сохранённые ресурсы отвечают: `GET /api/projects`, `GET /api/providers`,
   `GET /api/config`, `GET /api/search/settings`, `GET /api/seo/settings` — 200;
   интерфейс открывается и показывает карточки проектов и диалог настроек.
8. Из QA-сценария `test_add_provider.py` проверка отсутствия `/settings` остаётся
   зелёной.

## Риски

| Риск | Мера |
| --- | --- |
| `service/search.py` срезан слишком глубоко и ломает настройки Яндекса | Живой контракт — только `configure`, `gateway`, `enabled`, `close`; он закреплён тестами `test_service_search_settings.py` и `test_search_settings.py`, которые сохраняются |
| Удаление полей `loadPageData` меняет форму данных layout | Потребители проверены: `+layout.svelte` читает только настройки, страницы проекта — `providers`, `SettingsPanel` — `settingsProviders` |
| Миграция теряет legacy-данные на другом инстансе | Предохранитель падает при непустой `runs`; локально таблицы пусты |
| Большой `python-api.test.ts` теряет покрытие живых путей | Удаляются только кейсы снятых путей; затронутые живые кейсы сохраняются и проверяются прогоном |
| Осиротевшие ссылки в документации и QA | Отдельный шаг синхронизации документов плюс поиск по репозиторию в критериях приёмки |

## Вне объёма

- Healthcheck, переменные окружения, секреты и инструкция развёртывания.
- Сборка и проверка Docker-образов.
- Снятие слоя совместимости с SQLite и переименование `seo_*` в имена служебной LLM.
- История в `docs/superpowers`.
- Удаление JSON-настроек и файлов `runs.sqlite3`/`seo-agents.sqlite3` из
  `~/.config/ai-tracker`: это данные вне репозитория, приложение их не читает.
