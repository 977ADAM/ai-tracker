# DeepSeek Web Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сохранять ответы прямого API DeepSeek с веб-поиском и показывать отдельно упоминания бренда, найденные страницы и цитирование сайта.

**Architecture:** Отдельный SEO-адаптер возвращает структурированный результат; старые текстовые проверки используют прежний адаптер. SEO-сервис фиксирует параметры подключения, репозиторий сохраняет ответ и источники атомарно, домен вычисляет метрики, Svelte показывает их в существующем отчёте.

**Tech Stack:** Python 3.13+, FastAPI, httpx, SQLite, Svelte 5/SvelteKit 2, TypeScript, pytest, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-09-deepseek-web-search-design.md` (утверждена пользователем).

## Global Constraints

- Режимы: `text` и `deepseek_web`; существующие подключения по умолчанию `text`.
- Поиск только у прямого HTTPS-подключения `api.deepseek.com`, стандартный порт, пути `/chat/completions` и `/v1/chat/completions`.
- Поисковый endpoint: `https://api.deepseek.com/anthropic/v1/messages`; модель из выбранного подключения без замены.
- Инструмент `web_search_20250305`, `max_uses=1`, максимум ответа 4096 токенов, таймаут полного вызова 120 секунд.
- Не больше пяти ответов моделей и пяти внутренних поисковых вызовов DeepSeek на прогон; Яндекс считается отдельно.
- Миграция SQLite до версии 6; старые ответы не участвуют в знаменателе цитирования.
- Ключ остаётся в прежнем хранилище; не попадает в снимок, публичный API, ошибки или трассу.
- Никаких автоматических повторных платных вызовов или перехода на собственный поиск.
- Порядок цитирования не называется рейтингом источников. Метрики вычисляются по сохранённым строкам сервером.
- Не менять размер набора запросов, не добавлять расписание и тональность в этом этапе.

## Review Focus

- Настройка меняется во время прогона: снимок сохраняет прежний режим и модель (Task 4).
- Сохранённый ответ обновляется только по статусу: источники не стираются (Task 3).
- Поиск вернул пустой успешный результат: это не ошибка и не «нет данных» (Tasks 1, 5).
- Несколько страниц одного домена процитированы подряд: порядок доменов не завышается (Task 5).
- После перезапуска старый анализ без снимка остаётся текстовым, даже если настройка уже поисковая (Task 4).

## Карта файлов и интерфейсов

Новые небольшие модули:

- `backend/app/domain/seo_answer.py`: типы ответа, нормализация URL и источников.
- `backend/app/integrations/deepseek_web.py`: Messages запрос и разбор поискового ответа.
- `backend/app/integrations/seo_answer.py`: фабрика SEO-адаптеров и обёртка текстового провайдера.
- `frontend/src/lib/components/SeoAnswerDialog.svelte`: просмотр ответа и источников, выделенный из SeoReport.

Существующие модули настроек, SEO-сервиса, репозитория, схем и отчёта меняются по месту. Не перестраивать остальные слои репозитория.

Контракты нового доменного модуля:

```python
AnswerMode = Literal["text", "deepseek_web"]
SearchStatus = Literal["not_requested", "completed", "error"]
# Frozen dataclasses:
SearchResult(url: str, title: str | None)
Citation(url: str, title: str | None, cited_text: str | None,
         block_index: int, order: int)
SeoAnswer(text: str, answer_mode: AnswerMode, search_status: SearchStatus,
          search_results: tuple[SearchResult, ...], citations: tuple[Citation, ...],
          model: str, search_calls: int | None)
SeoConnectionSnapshot(connection_id: str, name: str, kind: str,
                      endpoint: str, model: str, answer_mode: AnswerMode,
                      thinking_disabled: bool)
normalize_source_url(value: object) -> str | None
normalize_sources(results: Sequence[SearchResult], citations: Sequence[Citation]) \
    -> tuple[tuple[SearchResult, ...], tuple[Citation, ...]]
```

`SeoAnswerProvider` имеет `answer(prompt: str) -> SeoAnswer` и `close() -> None`.
`SeoAnswerFactory` принимает снимок и ключ, возвращает этот провайдер.
Старый `AnswerProvider.answer(prompt) -> str` не меняется.

### Task 1: Домен ответа и адаптер встроенного поиска

**Files:** создать доменный модуль и DeepSeek-адаптер из карты файлов; тесты `backend/tests/test_domain_seo_answer.py`, `backend/tests/test_integrations_deepseek_web.py`.

**Consumes:** официальный формат Messages, существующие правила URL проекта и `ProviderError`.
**Produces:** типы выше; `DeepSeekWebClient(api_key: str, model: str, *, transport: httpx.AsyncBaseTransport | None = None)` реализует `SeoAnswerProvider`. Синхронный метод запускает асинхронный HTTP-вызов в worker thread; общий таймаут охватывает всё выполнение.

- [x] Написать `test_request_uses_native_search_and_selected_model`: MockTransport проверяет фиксированный endpoint, авторизацию, `anthropic-version=2023-06-01`, выбранную модель, `max_tokens=4096` и `max_uses=1`.
- [x] Добавить `test_maps_text_results_and_citations`: два текстовых блока сохраняются по порядку; поисковые страницы и цитаты не смешиваются, повтор цитаты остаётся в citations. `test_empty_successful_search` ожидает completed и пустые списки; `test_completed_search_without_citations` — completed и ноль цитат.
- [x] Добавить тесты отсутствующего блока поиска, tool error, пустого/неправильного ответа, `pause_turn`, `max_tokens` stop reason, таймаута, 401/403/429/500 и перенаправления. Все дают безопасный ProviderError без текста upstream и без повторного HTTP-запроса.
- [x] Добавить URL-тесты: credentials, javascript/data, localhost, приватные IP и недопустимый хост исключаются по существующим правилам без DNS-запроса; fragment удаляется, query остаётся. Не считать домен из текста структурированной цитатой.
- [x] Выполнить `cd backend && uv run pytest tests/test_domain_seo_answer.py tests/test_integrations_deepseek_web.py`; подтвердить падение на ещё отсутствующем модуле.
- [x] Реализовать типы, нормализацию и клиент. Ограничить полный вызов 120 секундами, запретить redirects; ошибки не содержат ключ. Число поисковых вызовов брать из структурированных данных при наличии, неизвестное оставлять None.
- [x] Повторить команду; все тесты должны пройти. Сохранить отдельным коммитом `feat: add DeepSeek native search answer adapter`.

### Task 2: Проверка реального API до интеграции

**Files:** итог проверки в разделе validation этого плана; не добавлять секреты или сырые ответы в git.

**Consumes:** `DeepSeekWebClient` и существующее прямое подключение, читаемое серверным ConnectionRepository.
**Produces:** подтверждённые модель, выполнение поиска, схема блоков и возможность получать законченный текстовый ответ.

- [ ] Найти прямые подключения через существующий репозиторий. Если их несколько с разными моделями, уточнить выбранную модель; не подменять её автоматически.
- [ ] Сделать ровно один короткий контрольный запрос через новый адаптер с ключом из прежнего хранилища. Не запускать SEO-прогон и не менять настройки пользователя ради пробы.
- [ ] Проверить завершённый ответ и completed search; записать только модель, дату, успешность и количество источников/цитат. Ноль цитат допустим.
- [ ] Если API отказывает или отличается от схемы: зафиксировать причину безопасным текстом и пересмотреть адаптер/спецификацию. Не продолжать интеграцию с неподтверждённой поддержкой и не делать повторную платную пробу молча.
- [ ] Сохранить результат проверки отдельным документальным коммитом; если доступ к ключу недоступен, явно обозначить блокировку и не заявлять живую проверку успешной.

### Task 3: Режим подключения и долговечное хранение

**Files:** `backend/app/domain/{models,provider_groups,connections}.py`, `backend/app/db/{connections,seo,chat,runs}.py`, `backend/app/api/schemas/{providers,provider_settings}.py`; тесты домена групп, DB connections/SEO/chat/runs и API providers/config.

**Consumes:** `AnswerMode`, `SeoAnswer`, `SeoConnectionSnapshot` из Task 1.
**Produces:** `Connection.answer_mode`, `ProviderGroup.answer_mode`; `SeoRepository.create_analysis(input, estimate, *, connection_snapshots: Sequence[SeoConnectionSnapshot] = ()) -> str`; дополнительный параметр `seo_answer: SeoAnswer | None = None` у save_model_row; `connection_snapshots(analysis_id: str) -> tuple[SeoConnectionSnapshot, ...]`.

- [ ] Написать тесты режима: старые метаданные дают text, deepseek_web проходит сохранение/чтение и проекцию модели; неизвестный режим, другой хост, нестандартный порт или путь отклоняются. Пустой ключ сохраняет прежний; публичная конфигурация не содержит ключей.
- [ ] Написать `test_migration_v5_preserves_old_answers`: version=6 после общей инициализации; старые ответы читаются как text/not_requested; повторная инициализация идемпотентна; более новая версия файла не изменяется.
- [ ] Написать `test_answer_sources_round_trip_atomically` и `test_status_only_update_preserves_sources`: списки, модель и статус поиска возвращаются через rows_page; status-only upsert сохраняет прежние данные; удаление анализа удаляет новые данные. Некорректный JSON не принимается молча за успешные источники.
- [ ] Запустить соответствующие pytest-файлы и убедиться в падении новых проверок.
- [ ] Реализовать режим и аддитивную миграцию. Использовать одну JSON-колонку `seo_answer` в seo_model_rows и `connection_snapshots` в seo_analyses. Существующий answer остаётся для совместимости, обе записи атомарны. Все владельцы общего SQLite-файла допускают версию 6; SEO-репозиторий выполняет миграцию.
- [ ] Повторить целевые тесты; сохранить `feat: persist SEO answer sources and connection modes`.

### Task 4: Подключение поиска к SEO-прогону и бюджет

**Files:** новый `backend/app/integrations/seo_answer.py`; `backend/app/service/{seo,seo_tools,chat}.py`, `backend/app/domain/seo_tools.py`, `backend/app/api/deps/container.py`; тесты factory/service SEO/tools/chat.

**Consumes:** доменные типы Task 1, сохранение и снимки Task 3.
**Produces:** `build_seo_answer_provider(snapshot: SeoConnectionSnapshot, key: str, settings: Settings) -> SeoAnswerProvider`; оценка `deepseek_search_upper: int`; результаты сохраняются существующим путём модельных строк.

- [ ] Написать тесты фабрики: text оборачивает существующий провайдер, deepseek_web выбирает новый клиент. Старые checks/runs и служебная LLM не используют поиск.
- [ ] Написать `test_run_freezes_connection_mode_and_model` и `test_legacy_resume_stays_text`: текущая правка настроек не влияет на прогон; восстановление старого анализа без снимка использует text. Ключ запрашивается по сохранённому connection_id, не записывается в снимок.
- [ ] Добавить тесты: одна сохранённая пара не оплачивается повторно, максимум пять ответов, ошибка поиска не считается absent и не ломает другую модель, отмена не отправляет новые вызовы.
- [ ] Проверить оценки: deepseek_search_upper=0 для text, 5 при хотя бы одном deepseek_web (консервативный предел), запросы Яндекса отдельно. Изменение чипов пересчитывает оценку; stale proposal не обходит текущие серверные правила запуска.
- [ ] Запустить целевые pytest и подтвердить новые падения.
- [ ] Реализовать отдельную SEO-фабрику, не меняя фабрику текстовых проверок. Внедрить её через контейнер; обновить тестовые фейки. Снимок создавать до платных вызовов; передавать в runner и читать при возобновлении. Источники и упоминания сохранять одной операцией.
- [ ] Повторить проверки; сохранить `feat: run SEO checks with native DeepSeek search`.

### Task 5: Метрики и публичные контракты

**Files:** `backend/app/domain/{seo,seo_report,seo_prompts}.py`, `backend/app/db/seo.py`, `backend/app/api/schemas/{seo,seo_chat}.py`; `backend/tests/test_domain_seo_report.py`, API SEO/chat и schemas tests.

**Consumes:** сохранённые SeoAnswer из Tasks 3–4.
**Produces:** `citation: Metric` в AI-метриках сайта, разрезах и конкурентах; дополнительные поля модельной строки `answer_mode`, `search_status`, `search_results`, `citations`, `model`, `search_calls`; оценка deepseek_search_upper в API.

- [ ] Добавить расчётный тест с тремя completed ответами: два цитируют сайт, один нет; citation.share=0.6667. Строка с error и старая text-строка не входят в denominator.
- [ ] Добавить `test_citation_position_counts_unique_domains`: порядок A/page1, A/page2, site/page1 даёт сайту место 2. Повтор домена не увеличивает позицию. Среднее считается только по ответам с цитированием, без нахождений равно None.
- [ ] Проверить цитирование поддомена, упоминание без цитаты, цитату без названия, завершённый пустой поиск (denominator=1, share=0), старые данные (denominator=0, share=None), конкурентов и все разрезы.
- [ ] Добавить API-тесты новых полей, отсутствия секретов и сохранения прежних полей; snapshot не отдаёт полные ответы/списки ссылок, rows отдаёт. Повреждённый источник не даёт ложный успех.
- [ ] Запустить эти pytest-файлы, подтвердить новые падения.
- [ ] Расширить ModelRowValue ссылкой на SeoAnswer, расчёт по сохранённым строкам, API-проекции и промпт агента отчёта. Не считать поисковые результаты цитатами. average_position у citation обозначает порядок первого цитируемого домена.
- [ ] Повторить проверки; сохранить `feat: report site citation shares separately from mentions`.

### Task 6: Настройки и предложение запуска

**Files:** `frontend/src/lib/types.ts`, `frontend/src/lib/seo-form.ts`, `frontend/src/lib/components/{SettingsPanel,ChatProposal}.svelte`; соответствующие .test.ts, seo-form.test.ts и ConfigPanel.test.ts.

**Consumes:** публичные режимы и оценка Task 5.
**Produces:** выбор режима группы и отображение режима/бюджета в предложении.

- [ ] Написать тест сохранения answer_mode в SettingsPanel и восстановления выбора при открытии; обычное подключение показывает text. Для постороннего endpoint нельзя выбрать deepseek_web; серверная ошибка показывается пользователю.
- [ ] Добавить тесты ChatProposal: поисковая модель имеет отметку, бюджет DeepSeek отдельный от Яндекса, смена чипов обновляет его; старые ответы API без нового поля отображаются с нулевой поисковой оценкой.
- [ ] Выполнить `cd frontend && npx vitest run src/lib/components/SettingsLayout.test.ts src/lib/components/ChatProposal.test.ts src/lib/seo-form.test.ts src/lib/components/ConfigPanel.test.ts`; подтвердить новые падения.
- [ ] Реализовать переключатель с понятными подписями и обновить типы. Серверная оценка — источник для предложения; estimateUpper получает дополнительный параметр числа поисковых подключений со значением 0 по умолчанию.
- [ ] Повторить тесты и `npm run check`; сохранить `feat: configure and show DeepSeek search mode`.

### Task 7: Отчёт и просмотр источников

**Files:** новый SeoAnswerDialog.svelte и SeoAnswerDialog.test.ts; `frontend/src/lib/components/SeoReport.svelte`, SeoReport.test.ts; `qa/pages/{seo,fake_api}.py`, `qa/tests/test_seo.py`.

**Consumes:** API-модельная строка и citation-метрики Task 5.
**Produces:** отдельные показатели цитирования и доступные источники в окне ответа.

- [ ] Написать компонентные тесты: короткий ответ с источниками открывается; полный текст, цитаты и свёрнутые результаты поиска показаны отдельно; повторные цитаты имеют привязку к блокам. Нет выдуманных смещений в тексте.
- [ ] Проверить ссылки HTTP(S), rel="noopener noreferrer", очистку Markdown, Escape, ловушку фокуса и возврат фокуса. Старый ответ читается без новых данных, citation=None показывает «—»/«Нет данных о цитировании».
- [ ] Добавить E2E-сценарий на fake API: предложение → поиск → сохранённый отчёт → окно источников → повторное открытие чата с теми же источниками. Не обращаться к платным API.
- [ ] Запустить `cd frontend && npx vitest run src/lib/components/SeoReport.test.ts src/lib/components/SeoAnswerDialog.test.ts` и подтвердить падения новых тестов.
- [ ] Выделить окно из SeoReport в SeoAnswerDialog с props `row: SeoModelRow`, `onClose: () => void`; отчёт владеет выбором строки и возвратом фокуса, окно — внутренним фокусом и показом блоков. Добавить метрики сайта, конкурентов и разрезов.
- [ ] Повторить компонентные тесты, `npm run check`, целевые QA-тесты по qa/README.md; сохранить `feat: display DeepSeek citations in SEO reports`.

### Task 8: Итоговая проверка и документация

**Files:** `README.md`, `tech.md`, этот план (галочки и результаты validation).

**Consumes:** завершённые Tasks 1–7 и результат контрольного запроса Task 2.
**Produces:** проверяемый законченный первый этап без обещаний совпадения с потребительским чатом.

- [ ] Обновить документацию: включение режима, совместимость модели, упоминание/цитирование, порядок доменов, старые ответы, бюджет внутренних поисков и измеряемый API-сценарий.
- [ ] Выполнить `cd backend && uv run pytest` и `uv run ruff check .`; все проверки проходят.
- [ ] Выполнить `cd frontend && npx vitest run`, `npm run check`, `npm run build`; все проверки проходят. Запустить браузерный сценарий из Task 7 в установленном QA-окружении.
- [ ] Проверить diff и отсутствие секретов в новых данных/логах; отдельно сверить восстановление прогонов и прежние проверки бренда. Не повторять живой платный вызов без причины.
- [ ] Зафиксировать результаты, лимиты и любые реальные блокировки. Поддержку API считать подтверждённой только при успешной Task 2.
- [ ] Сохранить документальные изменения отдельным коммитом и передать результат на итоговое ревью выбранным пользователем способом.

## Validation

2026-10-09: адаптер и доменные типы реализованы; 41 новая проверка проходит.
Работа ведётся без worktree, по просьбе пользователя, в ветке `codex/deepseek-web-search`.

Контрольный вызов поиска через сохранённое прямое подключение `deepseek-flash`
получил отказ авторизации. Бесплатный `GET /models` с тем же ключом также вернул
HTTP 401. Ключ и тела ошибок не выводились. Поддержка поиска не подтверждена;
Tasks 3–8 ожидают исправления подключения и успешной проверки Task 2.

Полный backend-набор: 1205 passed in 7.63s. Ruff для новых модулей и тестов: All checks passed.

Повторная проверка после обновления ключа: HTTP 200; deepseek-flash; completed; 1 search call, 10 pages, 0 structured citations. Исправлена обработка tool errors внутри списка результатов; инструкция ограничивает поиск одним вызовом.
