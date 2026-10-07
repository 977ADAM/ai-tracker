# ИИ-трекинг: технический контекст

Короткий технический обзор для разработчика: что это, из чего собрано, где что лежит.
Пользовательское описание, правила продукта и переменные окружения — в [README.md](README.md).

## 1. Назначение

Локальное приложение для SEO-анализа сайта и конкурентов: видимость в первой десятке выдачи
Яндекса и упоминания компании в ответах подключённых ИИ-моделей.

- **Основной сценарий — чат SEO-анализа**: диалог собирает параметры прогона (адрес сайта, сфера,
  три ключевых запроса, услуги), ассистент уточняет недостающее и показывает карточку предложения,
  а прогон стартует после подтверждения словом «да» и остаётся в чате вместе с отчётом. Прогоном
  управляет супервизор, работу выполняют пять специалистов; агенты действуют только через
  серверные инструменты.
- **Прежние сценарии остаются в API**: проверка упоминаний бренда (`POST /api/check`), прямой
  поиск в Яндексе (`/api/search`) и сохранённые прогоны (`/api/runs`, включая экспорт CSV).

## 2. Стек

| Часть | Технологии |
| --- | --- |
| Backend | Python ≥ 3.13, FastAPI, uvicorn, httpx, python-dotenv, keyring |
| Агентный рантайм | LangGraph + langchain-openai, чекпойнты в SQLite (`langgraph-checkpoint-sqlite`) |
| Хранилище | SQLite (`runs.sqlite3`), JSON-файлы метаданных, системный keyring |
| Frontend | SvelteKit 2 / Svelte 5, adapter-node, Tailwind 4, Vite 7, TypeScript 5 |
| Frontend-библиотеки | `marked` и `dompurify` — разметка ответов моделей с очисткой |
| Тесты | pytest и ruff в backend; Vitest и Testing Library в frontend; Playwright в QA |

## 3. Архитектура

Зависимости backend идут только вниз.

| Слой | Каталог | Ответственность |
| --- | --- | --- |
| API | `backend/app/api` | Роутеры FastAPI, pydantic-схемы, DI-контейнер, обработчики ошибок |
| Сервисы | `backend/app/service` | Сценарии: диалог чата, SEO-прогон и агенты, проверки, поиск, настройки, экспорт |
| Домен | `backend/app/domain` | Чистые правила и модели без I/O: валидация входа, диалог чата и его промпты, бюджеты, инструменты, отчёт |
| Инфраструктура | `backend/app/db`, `backend/app/integrations` | SQLite, JSON-настройки, keyring; адаптеры Яндекса, моделей и обхода сайта |

- Точка входа — [main.py](backend/app/main.py): приложение и контейнер собираются на импорте,
  `Settings.from_env()` читает окружение и корневой `.env`. Тесты подменяют `get_container`.
- Домен не знает про сеть и фреймворки: внешние действия выполняются инструментами
  ([seo_tools.py](backend/app/domain/seo_tools.py)), а адаптеры переводят любые сбои в
  фиксированные русские сообщения — тело ответа, URL и ключи наружу не уходят.
- Frontend работает как BFF: серверные роуты `frontend/src/routes/api/**/+server.ts` проксируют
  запросы в Python API через [python-api.ts](frontend/src/lib/server/python-api.ts), поэтому
  браузер обращается только к интерфейсу и CORS не нужен.

## 4. Ключевые потоки

- **Проверка упоминаний** (`POST /api/check`): выбранные подключения опрашиваются одними и теми
  же запросами; сбой одного подключения не стирает результаты остальных.
- **Чат-анализ** (`POST /api/seo/chats/{id}/messages`): одно сообщение — ровно один платный вызов
  служебной LLM; модель называет намерение и извлекает поля, а решение о запуске принимает
  сервер. Прогон стартует только из открытой карточки, параметры которой совпадают с черновиком,
  и после подтверждения словом «да».
- **SEO-прогон** (`POST /api/seo/analyses`, из чата или напрямую по API): шесть агентов —
  супервизор, сайт, конкуренты, запросы, проверки, отчёт (`AGENTS` в
  [seo.py](backend/app/domain/seo.py)). Супервизор передаёт
  управление специалистам; каждый внешний шаг проходит через инструмент, который проверяет
  аргументы, бюджет и зависимости данных, сохраняет результат и пишет шаг в трассу.
- **Отложенный поиск Яндекса**: задача только ставится (`submit`), результат опрашивается позже.
  Прогон идемпотентен: повторный вызов по тому же запросу возвращает сохранённый результат.
- **Отмена и возобновление**: отмена останавливает граф до следующего шага; состояние графа
  чекпойнтится в `seo-agents.sqlite3`, после перезапуска прогон продолжается из чекпойнта.

Бюджеты одного прогона ([site_fetch.py](backend/app/domain/site_fetch.py),
[seo_tools.py](backend/app/domain/seo_tools.py)):

| Ресурс | Предел |
| --- | --- |
| Прочитанные страницы | 5 |
| Поисковые запросы Яндекса | 5: три ключевых и до двух сгенерированных |
| Ответы моделей | 5 на прогон, независимо от числа подключений |
| Передачи управления супервизора | 15 |
| Ходы модели на одного специалиста | 20 |
| Вызовы инструментов | 120 |
| Один вызов служебной LLM | 120 секунд |

Исчерпание бюджета завершает прогон с признаком «остановлен по лимиту»: готовые строки и отчёт
остаются доступными, новые платные вызовы не выполняются.

## 5. API

Все маршруты — под префиксом `/api`; OpenAPI и Swagger UI — на `/docs`
([router.py](backend/app/api/router.py), [openapi.py](backend/app/api/openapi.py)).

| Метод и путь | Назначение |
| --- | --- |
| `GET /api/config` | Все сохранённые настройки одним документом, без ключей |
| `GET /api/form` | Параметры прежней проверки: лимиты и поля нового подключения |
| `GET /api/providers` | Список подключений |
| `POST /api/providers` | Создать подключение или задать ключ встроенному |
| `PUT /api/providers/{id}` | Изменить подключение; пустой ключ сохраняет прежний |
| `DELETE /api/providers/{id}` | Удалить подключение или сбросить ключ |
| `GET`, `POST /api/providers/settings` | Группы подключений: провайдер с несколькими моделями |
| `PUT`, `DELETE /api/providers/settings/{group_id}` | Изменить или удалить группу |
| `POST /api/check` | Проверить упоминания бренда |
| `GET /api/search/regions` | Справочник регионов Яндекса |
| `POST /api/search` | Запустить поиск сайта в Яндексе (202, задача асинхронная) |
| `GET /api/search/{job_id}` | Состояние задачи поиска |
| `GET`, `PUT /api/search/settings` | Настройки поисковой системы |
| `DELETE /api/search/settings/credentials` | Сбросить учётные данные Яндекса |
| `POST /api/runs` | Запустить прогон проверки (202) |
| `GET /api/runs` | История прогонов постранично |
| `GET /api/runs/{run_id}` | Снимок прогона |
| `DELETE /api/runs/{run_id}` | Удалить завершённый прогон |
| `GET /api/runs/{run_id}/export.csv` | Экспорт прогона в CSV |
| `POST /api/seo/analyses` | Запустить SEO-анализ (202) |
| `GET /api/seo/analyses` | Прежние SEO-прогоны постранично (только API) |
| `GET /api/seo/analyses/{id}` | Снимок анализа, агенты и бюджет |
| `GET /api/seo/analyses/{id}/rows` | Детализация строк по курсору |
| `GET /api/seo/analyses/{id}/trace` | Трасса шагов агентов |
| `POST /api/seo/analyses/{id}/cancel` | Отменить прогон |
| `DELETE /api/seo/analyses/{id}` | Удалить завершённый анализ |
| `GET /api/seo/chats` | Список чатов, новые сверху, с признаком идущего прогона |
| `POST /api/seo/chats` | Создать пустой чат (201) |
| `GET /api/seo/chats/{id}` | Чат и страница ленты; курсор `before` читает более ранние сообщения |
| `DELETE /api/seo/chats/{id}` | Удалить чат и запущенные из него прогоны (204) |
| `POST /api/seo/chats/{id}/messages` | Отправить сообщение: вопрос, карточка предложения или платный прогон |
| `PUT /api/seo/chats/{id}/proposal` | Заменить подключения открытой карточки предложения |
| `GET`, `PUT /api/seo/settings` | Настройки служебной LLM |
| `DELETE /api/seo/settings/credentials` | Сбросить ключ служебной LLM |
| `POST /api/seo/settings/test` | Проверить LLM и поддержку вызова инструментов |

## 6. Данные и секреты

Каталог данных — `AI_TRACKER_CONFIG_DIR`, по умолчанию `~/.config/ai-tracker`
([config.py](backend/app/core/config.py)); в Docker это том `ai-tracker-data`, каталог `/data`.

| Файл | Содержимое |
| --- | --- |
| `providers.json` | Метаданные подключений: имя, адрес, модель; ключей нет |
| `runs.sqlite3` | Прогоны проверок (`user_version = 2`), SEO-таблицы (`user_version = 4`): анализы, страницы, кандидаты, запросы, строки поиска и моделей, агенты, шаги трассы, выводы; таблицы чата (`user_version = 5`): `seo_chats` и `seo_chat_messages` |
| `seo-agents.sqlite3` | Чекпойнты графа LangGraph: один файл, поток на ID анализа |
| `search-settings.json` | Настройки Яндекса: ID каталога и признак включения |
| `seo-settings.json` | Адрес и модель служебной LLM |
| Системный keyring | Ключи моделей (учётная запись — ID подключения), `yandex-search`, `seo-llm` |

- Таблицы чата создаёт [db/chat.py](backend/app/db/chat.py) — последний владелец общего файла: он
  заводит `seo_chats` и `seo_chat_messages` и поднимает `user_version` до 5, а файл более новой
  версии не трогает. Черновик диалога и payload сообщений лежат в этих таблицах как JSON.
- Ключи не попадают ни в `providers.json`, ни в ответы API, ни в текст ошибок: публичный ответ
  содержит только признак «ключ задан». В контейнере системного хранилища нет, поэтому образ
  backend ставит файловый бэкенд `keyrings.alt` и держит ключи в томе.
- Окружение — запасной источник (`DEEPSEEK_API_KEY`, `YANDEX_SEARCH_API_KEY`,
  `YANDEX_SEARCH_FOLDER_ID`, `SEO_LLM_ENDPOINT`, `SEO_LLM_MODEL`, `SEO_LLM_API_KEY`); значение,
  сохранённое в интерфейсе, сильнее окружения.
- Хост-гард `AI_TRACKER_ALLOWED_HOSTS` включается через `TrustedHostMiddleware`: по умолчанию
  API доступен только с локальной машины.

## 7. Запуск и проверки

| Команда | Что делает |
| --- | --- |
| `make install` | `uv sync` в backend и `npm ci` в frontend |
| `make backend` | Python API на `127.0.0.1:8000` |
| `make frontend` | SvelteKit dev-сервер на `127.0.0.1:5173` |
| `make check` | `svelte-check` по TypeScript и Svelte |
| `make build`, `make frontend-prod` | Сборка интерфейса и запуск собранного |
| `make ruff` | `ruff check --fix` в backend |
| `make docker-up`, `make docker-down`, `make docker-logs` | Стек в Docker Compose |

- Docker: две службы — backend на `127.0.0.1:8000` и интерфейс на `127.0.0.1:3001` с base path
  `/clustering/tracker` ([docker-compose.yml](docker-compose.yml),
  [svelte.config.js](frontend/svelte.config.js)); публичный origin задаётся `AI_TRACKER_ORIGIN`.
- Backend-тесты: `cd backend && uv run pytest` — модули в [backend/tests](backend/tests) по слоям
  (api, db, domain, integrations, service) на фейках, без внешних вызовов.
- Frontend-тесты: `cd frontend && npx vitest run` — тесты лежат рядом с кодом (`*.test.ts`);
  отдельного скрипта `test` в `package.json` нет.
- Сквозные проверки: [qa](qa/README.md) — Playwright в настоящем браузере; требует поднятых
  `make backend` и `make frontend`, платные API не вызывает и подменяет ответы через `page.route`.

## 8. Карта репозитория

| Путь | Что там |
| --- | --- |
| [backend/app/api](backend/app/api) | Роутеры, схемы, DI, обработчики ошибок, OpenAPI |
| [backend/app/api/routers/seo_chats.py](backend/app/api/routers/seo_chats.py) | Шесть маршрутов чатов: список, создание, чтение с курсором, удаление, сообщение, карточка предложения |
| [backend/app/service](backend/app/service) | Сценарии: диалог чата, SEO-прогон и агенты, проверки, поиск, настройки, экспорт |
| [backend/app/service/chat.py](backend/app/service/chat.py) | Один ход диалога: один платный вызов и серверное решение о запуске |
| [backend/app/domain](backend/app/domain) | Правила и модели: валидация, лимиты, инструменты, отчёт, промпты |
| [backend/app/domain/chat.py](backend/app/domain/chat.py) | Правила диалога: черновик, недостающие поля, предложение, право на запуск |
| [backend/app/domain/chat_prompts.py](backend/app/domain/chat_prompts.py) | Промпт чата, разметка недоверенного ввода, фиксированные фразы |
| [backend/app/db](backend/app/db) | Репозитории SQLite, JSON-настройки, keyring |
| [backend/app/db/chat.py](backend/app/db/chat.py) | Таблицы `seo_chats` и `seo_chat_messages`, миграция `user_version = 5` |
| [backend/app/integrations](backend/app/integrations) | Адаптеры: OpenAI-совместимый чат, служебная LLM, Яндекс, обход сайта |
| [backend/tests](backend/tests) | Модульные и API-тесты pytest |
| [frontend/src/routes](frontend/src/routes) | Страницы и BFF-роуты `api/**/+server.ts` |
| [frontend/src/lib](frontend/src/lib) | Компоненты Svelte, типы, клиентская валидация, серверный прокси |
| [frontend/src/lib/components](frontend/src/lib/components) | Компоненты чата: `ChatSidebar`, `ChatFeed`, `ChatMessage`, `ChatProposal`, `ChatRun`, `ChatComposer` |
| [qa](qa) | Сквозные проверки Playwright и page objects |
| [docs/superpowers](docs/superpowers) | Спеки и планы прошлых итераций |
| [README.md](README.md) | Пользовательское описание, правила и переменные окружения |
