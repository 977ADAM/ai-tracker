# AI Tracking Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Расширить прогон ИИ-трекинга до 10 поисковых запросов и 10 ответов моделей с четвёртым интентом, добавить детерминированную метрику позиции бренда в ответе и вывести источники (цитирование сайта и топ внешних доменов) в отчёт.

**Architecture:** Все новые метрики считаются на чтение из уже сохранённых строк в `domain/seo_report.py` — новых таблиц и миграций нет. Лимиты и категории живут в `domain/seo.py` и подставляются в промпты и описания инструментов. Фронтенд получает новые поля через строгие проекции BFF и рисует их в существующем компактном отчёте.

**Tech Stack:** Python ≥ 3.13, FastAPI, pydantic v2, pytest; SvelteKit 2 / Svelte 5, TypeScript, Vitest; Playwright в `qa`.

**Spec:** `docs/superpowers/specs/2026-10-09-ai-tracking-coverage-design.md`

## Global Constraints

- Лимиты прогона: `GENERATED_QUERY_LIMIT = 7`, `MIN_GENERATED_QUERIES = 2` (не меняется), `MAX_SEARCH_REQUESTS = 10`, `MAX_MODEL_ANSWERS = 10`. Остальные лимиты (5 страниц, 5 подключений, 15 передач, 20 ходов, 120 вызовов) не трогать.
- Хранения не меняем: `PRAGMA user_version` и таблицы остаются как есть, метрики считаются на чтение.
- Пользовательские тексты — русские; тело ответа провайдера, адрес и ключ никогда не попадают в ответы API и в текст ошибок.
- Схемы pydantic строгие: `ConfigDict(extra="forbid")`, `StrictStr` — как в `app/api/schemas/seo.py`.
- Домен не знает про сеть и фреймворки; новые метрики — чистые функции без I/O.
- Новые возможности не добавляют ни одного платного вызова: всё считается по сохранённым строкам.
- Отчёт остаётся компактным и без текста модели: никаких новых «резюме» и рекомендаций.
- Тесты backend запускаются только так: `cd backend && AI_TRACKER_CONFIG_DIR=$PWD/.pytest-config .venv/bin/pytest` (`uv run` в песочнице не пишет кэш, импорт `app.main` иначе трогает реальный `~/.config/ai-tracker`).
- Фронтенд: `npm run check`, `npm run lint`, `npm run format:check` должны быть зелёными; форматирование — Prettier, правила — ESLint.
- QA: `cd qa && QA_HEADLESS=1 .venv/bin/pytest` — требует поднятых `make backend` и `make frontend`.

## Review Focus

1. **Ответ без цитат (текстовый режим)** — строка не входит в знаменатель `citation` и не попадает в `sources`, в отчёте это «—», а не «0 %».
2. **Одноабзацный ответ без пустых строк** — позиция обязана быть `first`, а не `absent`.
3. **Свой хост в цитатах** — он учитывается в `citation` сайта, но исключается из топа `sources`.
4. **Нет кандидатов в прогоне** — `ahead` с пустым знаменателем даёт «—», не «0 %».
5. **Строка веб-поиска со статусом `error`** — не считается отсутствием цитирования, а выпадает из знаменателя.

---

### Task 1: Лимиты 10/10 и четвёртая категория

**Files:**
- Modify: `backend/app/domain/seo.py:30-42`
- Modify: `backend/app/domain/seo_prompts.py:126-145`
- Test: `backend/tests/test_domain_seo.py`, `backend/tests/test_domain_seo_tools.py`, `backend/tests/test_domain_seo_prompts.py`
- Modify: `README.md`, `tech.md`

**Interfaces:**
- Produces: `GENERATED_QUERY_LIMIT = 7`, `MAX_SEARCH_REQUESTS = 10`, `MAX_MODEL_ANSWERS = 10`, `QUERY_CATEGORIES = ("commercial", "informational", "comparative", "recommendation")`, `CATEGORY_LABELS["recommendation"] = "Рекомендовательные"`.

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_domain_seo_tools.py` (существующий `test_the_agreed_limits_are_the_ones_the_run_uses`):

```python
assert GENERATED_QUERY_LIMIT == 7
assert MIN_GENERATED_QUERIES == 2
assert MAX_SEARCH_REQUESTS == 10
assert MAX_MODEL_ANSWERS == 10
```

`backend/tests/test_domain_seo.py`:

```python
def test_the_four_query_categories_and_their_russian_labels_are_fixed():
    assert QUERY_CATEGORIES == ("commercial", "informational", "comparative", "recommendation")
    assert CATEGORY_LABELS["recommendation"] == "Рекомендовательные"
```

`backend/tests/test_domain_seo_prompts.py`:

```python
def test_the_query_agent_asks_for_every_category_up_to_the_new_limit():
    system, _user = query_agent_prompt(seo_input())
    assert "recommendation" in system
    assert str(GENERATED_QUERY_LIMIT) in system
```

- [ ] **Step 2: Запустить и убедиться, что тесты падают**

Run: `cd backend && AI_TRACKER_CONFIG_DIR=$PWD/.pytest-config .venv/bin/pytest -q tests/test_domain_seo.py tests/test_domain_seo_tools.py tests/test_domain_seo_prompts.py`
Expected: FAIL — `assert 2 == 7`, отсутствует `recommendation`.

- [ ] **Step 3: Реализовать константы и промпт**

В `backend/app/domain/seo.py`: заменить комментарий «два сгенерированных запроса… пять ответов» на «семь сгенерированных на трёх ключевых (10 поисков) и десять ответов моделей», поднять `GENERATED_QUERY_LIMIT` до 7, добавить `recommendation` в `QUERY_CATEGORIES` и его лейбл в `CATEGORY_LABELS`.

В `backend/app/domain/seo_prompts.py` в `query_agent_prompt` добавить требование покрыть все категории, если валидных запросов хватает: `"Стремись дать хотя бы один запрос каждой категории."`

- [ ] **Step 4: Запустить тесты и весь backend-набор**

Run: `cd backend && AI_TRACKER_CONFIG_DIR=$PWD/.pytest-config .venv/bin/pytest -q`
Expected: PASS, 0 падений.

- [ ] **Step 5: Обновить документацию**

`README.md`: заменить «не больше 5 поисковых запросов в Яндекс (3 ключевых + до 2 сгенерированных) и не больше 5 запросов к моделям» на 10 и 10, обновить таблицу бюджетов, строку про «не больше 2 уникальных запросов» и упоминание трёх категорий. `tech.md`: те же числа в таблице бюджетов и в разделе про SEO-прогон.

- [ ] **Step 6: Коммит**

```bash
git add backend/app/domain/seo.py backend/app/domain/seo_prompts.py backend/tests/test_domain_seo.py backend/tests/test_domain_seo_tools.py backend/tests/test_domain_seo_prompts.py README.md tech.md
git commit -m "Raise the run to ten searches and ten model answers with a fourth intent"
```

---

### Task 2: Позиция бренда в агрегатах отчёта

**Files:**
- Modify: `backend/app/domain/seo_report.py` (новые `_paragraphs`, `_paragraph_mentions`, `_first_mention_paragraph`, `_brand_position`; вызов в `_site_ai_block`)
- Modify: `backend/app/api/schemas/seo.py` (`SeoBrandPositionResponse`, поле `position` в `SeoSiteAiMetricsResponse`)
- Test: `backend/tests/test_domain_seo_report.py`, `backend/tests/test_api_seo.py`

**Interfaces:**
- Consumes: `Metric`, `_metric(denominator, successes, positions=())`, `_answered(row)`, `normalize_text`, `mentions_host` — всё уже есть в `backend/app/domain/seo_report.py`.
- Produces: `_brand_position(rows: Sequence[ModelRowValue], connection_id: str, company_name: str, host: str, candidate_hosts: Sequence[str]) -> dict[str, Metric]`; агрегат `site.ai[<connection_id>].position = {"first", "early", "late", "absent", "ahead"}`.

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_domain_seo_report.py`:

```python
def test_the_brand_position_counts_the_paragraph_of_the_first_mention():
    report = build_report(
        data, "Ромашка", data.services, (), queries,
        (), (model_row("conn-1", 0, "Первый абзац про Ромашку.\n\nВторой."),
             model_row("conn-1", 1, "Раз.\n\nДва.\n\nТри.\n\nРомашка тут."),
             model_row("conn-1", 2, "Ничего про бренд.")),
    )
    position = report["site"]["ai"]["conn-1"]["position"]
    assert position["first"]["successes"] == 1
    assert position["late"]["successes"] == 1
    assert position["absent"]["successes"] == 1
    assert position["first"]["denominator"] == 3

def test_a_single_paragraph_answer_is_the_first_paragraph():
    report = build_report(data, "Ромашка", data.services, (), queries, (),
                          (model_row("conn-1", 0, "Ромашка упомянута сразу."),))
    assert report["site"]["ai"]["conn-1"]["position"]["first"]["successes"] == 1

def test_the_brand_is_ahead_when_no_candidate_is_mentioned_earlier():
    # candidate host: rival.ru; the brand in paragraph 1, the candidate in paragraph 2
    ...  # assert position["ahead"]["denominator"] == 1 and ["successes"] == 1

def test_the_ahead_metric_has_an_empty_denominator_without_candidates():
    ...  # assert position["ahead"]["denominator"] == 0 and share is None
```

- [ ] **Step 2: Запустить и убедиться, что тесты падают**

Run: `cd backend && AI_TRACKER_CONFIG_DIR=$PWD/.pytest-config .venv/bin/pytest -q tests/test_domain_seo_report.py`
Expected: FAIL — `KeyError: 'position'`.

- [ ] **Step 3: Реализовать метрику**

`_paragraphs(text) -> tuple[str, ...]`: `re.split(r"\n\s*\n", text)`, без пустых строк. `_paragraph_mentions(paragraph, company_name, host) -> bool`: непустое нормализованное имя компании содержится в нормализованном абзаце **или** `mentions_host(paragraph, host)`. `_first_mention_paragraph(...) -> int | None` — номер абзаца с 1.

`_brand_position` считает по строкам одного подключения со статусом `found` и непустым ответом (`_answered`): `first` = абзац 1, `early` = 2–3, `late` = 4+, `absent` = упоминания нет; у всех четырёх один знаменатель — число таких строк. `ahead`: знаменатель — строки, где упомянут хотя бы один хост-кандидат; успех — бренд упомянут и его абзац строго раньше абзаца каждого упомянутого кандидата (упоминание в том же абзаце успехом не считается).

В `_site_ai_block` добавить `"position": _brand_position(rows, connection_id, company_name, host, candidate_hosts)`; `company_name` и список хостов кандидатов прокинуть параметрами от `build_report`. `position` не дублируется в `branded`/`unbranded`.

- [ ] **Step 4: Схема API**

`SeoBrandPositionResponse` с пятью полями `SeoMetricResponse`; в `SeoSiteAiMetricsResponse` добавить `position: SeoBrandPositionResponse | None = None` (у брендовых и небрендовых срезов остаётся `None`).

- [ ] **Step 5: Запустить тесты домена и API**

Run: `cd backend && AI_TRACKER_CONFIG_DIR=$PWD/.pytest-config .venv/bin/pytest -q tests/test_domain_seo_report.py tests/test_api_seo.py`
Expected: PASS.

- [ ] **Step 6: Коммит**

```bash
git add backend/app/domain/seo_report.py backend/app/api/schemas/seo.py backend/tests/test_domain_seo_report.py backend/tests/test_api_seo.py
git commit -m "Measure where in the answer the brand is named"
```

---

### Task 3: Источники — агрегат `sources`

**Files:**
- Modify: `backend/app/domain/seo_report.py` (`_source_counts`, ключ `sources` в `build_report`)
- Modify: `backend/app/api/schemas/seo.py` (`SeoSourceCountResponse`, поле `sources` в `SeoAggregatesResponse`)
- Test: `backend/tests/test_domain_seo_report.py`, `backend/tests/test_api_seo.py`

**Interfaces:**
- Consumes: `ModelRowValue.seo_answer.citations`/`search_status`, `normalize_source_url`, `canonical_host`, `same_site_host`.
- Produces: `_source_counts(models: Sequence[ModelRowValue], host: str) -> list[dict]`; агрегат `sources: [{"domain": str, "answers": int, "citations": int}]`, топ-20.

- [ ] **Step 1: Написать падающие тесты**

```python
def test_sources_rank_external_domains_and_skip_the_own_host():
    report = build_report(...)  # two answered rows with completed web search and citations
    assert report["sources"][0] == {"domain": "habr.com", "answers": 2, "citations": 3}
    assert all(item["domain"] != "example.ru" for item in report["sources"])

def test_a_row_without_completed_web_search_never_reaches_sources():
    # search_status="error" and "not_requested" add nothing
    assert report["sources"] == []
```

- [ ] **Step 2: Запустить и убедиться, что тесты падают**

Run: `cd backend && AI_TRACKER_CONFIG_DIR=$PWD/.pytest-config .venv/bin/pytest -q tests/test_domain_seo_report.py`
Expected: FAIL — `KeyError: 'sources'`.

- [ ] **Step 3: Реализовать `_source_counts`**

По строкам с `seo_answer is not None` и `search_status == "completed"`: нормализовать каждый `citation.url` (`normalize_source_url`), взять `canonical_host`, пропустить домены, совпадающие с хостом пользователя (`same_site_host`), посчитать на домен число ответов (`answers`) и цитирований (`citations`), вернуть топ-20 с сортировкой `(-answers, -citations, domain)`.

- [ ] **Step 4: Схема API**

`SeoSourceCountResponse {domain: StrictStr, answers: int, citations: int}`; в `SeoAggregatesResponse` добавить `sources: list[SeoSourceCountResponse]`.

- [ ] **Step 5: Запустить тесты домена и API**

Run: `cd backend && AI_TRACKER_CONFIG_DIR=$PWD/.pytest-config .venv/bin/pytest -q tests/test_domain_seo_report.py tests/test_api_seo.py`
Expected: PASS.

- [ ] **Step 6: Коммит**

```bash
git add backend/app/domain/seo_report.py backend/app/api/schemas/seo.py backend/tests/test_domain_seo_report.py backend/tests/test_api_seo.py
git commit -m "Rank the external domains the models cite"
```

---

### Task 4: Фронтенд — типы, проекции и лейблы категорий

**Files:**
- Create: `frontend/src/lib/seo-categories.ts`
- Modify: `frontend/src/lib/types.ts`, `frontend/src/lib/server/python-api.ts`
- Test: `frontend/src/lib/server/python-api.test.ts` и фикстуры снапшота в `src/lib/seo-form.test.ts`, `src/lib/components/{ChatFeed,ChatRun,SeoAgentPanel,SeoRunProgress,SeoReport}.test.ts`, `src/routes/page.test.ts`

**Interfaces:**
- Produces: `SeoMetric.citation: SeoMetric | null`, `SeoSiteAiMetrics.position: SeoBrandPosition | null`, `SeoBrandPosition = {first, early, late, absent, ahead: SeoMetric}`, `SeoSourceCount = {domain: string; answers: number; citations: number}`, `SeoCitation = {url: string; title: string | null}`, `SeoModelRow += answer_mode | search_status | citations | model | search_calls`, `SeoAggregates.sources: SeoSourceCount[]`, `SEO_CATEGORY_LABELS: Record<string, string>`.

- [ ] **Step 1: Написать падающие тесты проекций**

`frontend/src/lib/server/python-api.test.ts`:

```ts
it('projects the citation, position and sources of a snapshot', () => {
  const projected = publicSeoSnapshot(seoSnapshot);
  expect(projected.aggregates.site.ai.p1.citation?.share).toBe(0.5);
  expect(projected.aggregates.site.ai.p1.position?.first.successes).toBe(1);
  expect(projected.aggregates.sources[0]).toEqual({ domain: 'habr.com', answers: 2, citations: 3 });
});

it('projects the answer mode and the citations of a model row', () => {
  const page = publicSeoRows(
    { items: [{ ...modelRow, answer_mode: 'deepseek_web', search_status: 'completed',
      citations: [{ url: 'https://habr.com/a', title: 'A' }] }], next_cursor: null },
    'model',
  );
  const row = page.items[0] as SeoModelRow;
  expect(row.answer_mode).toBe('deepseek_web');
  expect(row.search_status).toBe('completed');
  expect(row.citations[0].url).toBe('https://habr.com/a');
});
```

- [ ] **Step 2: Запустить и убедиться, что тест падает**

Run: `cd frontend && npx vitest run src/lib/server/python-api.test.ts`
Expected: FAIL — `citation`/`position`/`sources` отсутствуют в проекции.

- [ ] **Step 3: Реализовать типы и проекции**

`types.ts`: добавить `SeoBrandPosition`, `SeoSourceCount`, `SeoCitation`, расширить `SeoSiteAiMetrics` (`citation`, `position`), `SeoModelRow`, `SeoAggregates`. `python-api.ts`: `seoSiteAiMetrics` читает `citation` и `position` (nullable), `seoAggregates` — массив `sources` (обязательный, как `competitors`), `seoModelRow` — `answer_mode`/`search_status` через `oneOf`, `citations` — новый `seoCitation` (массив проверяется `Array.isArray`, элемент через `record`), `model`/`search_calls` как `optionalString`/`optionalInteger`. `seo-categories.ts`: словарь ключей из `QUERY_CATEGORIES` в русские лейблы.

- [ ] **Step 4: Обновить фикстуры снапшотов**

Во всех перечисленных тестах в объект `aggregates` добавить `sources: []`, а в блоках `site.ai` — `citation: null, position: null`, чтобы типы сходились; прогонять по мере правок.

- [ ] **Step 5: Запустить фронтенд-проверки**

Run: `cd frontend && npx vitest run && npm run check && npm run lint && npm run format:check`
Expected: тесты PASS, `svelte-check` 0 ошибок, линт и формат чисто.

- [ ] **Step 6: Коммит**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/server/python-api.ts frontend/src/lib/seo-categories.ts frontend/src/lib/server/python-api.test.ts frontend/src/lib/seo-form.test.ts frontend/src/lib/components frontend/src/routes/page.test.ts
git commit -m "Carry citations, brand position and sources into the frontend types"
```

---

### Task 5: Отчёт — источники, позиция бренда, покрытие и режим ответа

**Files:**
- Modify: `frontend/src/lib/components/SeoReport.svelte`
- Test: `frontend/src/lib/components/SeoReport.test.ts`

**Interfaces:**
- Consumes: всё из Task 4.
- Produces (селекторы для тестов и QA): `data-metric="ai-<conn>-<group>-citation"`, `data-position="ai-<conn>-<group>-citation"`, `data-metric="candidate-<host>-citation-<conn>"`, `data-brand-position="first|early|late|absent|ahead"`, `data-source-row` с `data-source-domain`/`data-source-answers`/`data-source-citations`, `data-model-coverage`, `data-answer-mode`, `data-answer-sources-count`, `data-answer-sources-list`.

- [ ] **Step 1: Написать падающие тесты**

```ts
it('shows how often the domain is cited and where it stands among the sources', () => {
  render(SeoReport, { props: { snapshot: snapshot() } });
  expect(content('[data-metric="ai-model-1-all-citation"]')).toBe('50 %');
  expect(content('[data-position="ai-model-1-all-citation"]')).toBe('2');
});

it('shows the brand position and skips it when there is no data', () => {
  render(SeoReport, { props: { snapshot: snapshot() } });
  expect(content('[data-brand-position="first"]')).toBe('30 %');
  const empty = document.querySelector('[data-brand-position="ahead"]');
  expect(empty?.textContent).toBe('—');
});

it('lists the top cited domains and the model coverage', () => {
  render(SeoReport, { props: { snapshot: snapshot() } });
  expect(document.querySelector('[data-source-domain]')?.textContent).toBe('habr.com');
  expect(content('[data-model-coverage]')).toBe('7 из 7');
});

it('shows the answer mode and the number of sources in the detail row', () => {
  render(SeoReport, { props: { snapshot: snapshot(), rows: { model: [modelRow], search: [] } } });
  expect(content('[data-answer-mode]')).toBe('веб-поиск');
  expect(content('[data-answer-sources-count]')).toBe('2');
});
```

- [ ] **Step 2: Запустить и убедиться, что тесты падают**

Run: `cd frontend && npx vitest run src/lib/components/SeoReport.test.ts`
Expected: FAIL — новых селекторов нет.

- [ ] **Step 3: Реализовать секции отчёта**

В таблице «Упоминания в ответах ИИ» добавить колонки «В источниках» (`percent(block.citation)`) и «Позиция домена» (`metricPosition(block.citation)`); в блоке кандидата — колонку «В источниках» из `candidate.ai[conn].citation`. Добавить компактные секции «Позиция бренда» (доли `first` и `ahead`, распределение `first/early/late/absent`, подпись «эвристика по абзацам ответа») и «Источники» (топ доменов, подпись про веб-поиск), строку покрытия «Опрос моделей: N из M пар» (M = сохранённые сгенерированные запросы × подключения, N = строки моделей). В детализации — режим ответа и число источников; в диалоге «Читать полностью» — список ссылок-источников. Пустые значения — «—».

- [ ] **Step 4: Запустить фронтенд-проверки**

Run: `cd frontend && npx vitest run && npm run check && npm run lint && npm run format:check`
Expected: PASS, 0 ошибок.

- [ ] **Step 5: Коммит**

```bash
git add frontend/src/lib/components/SeoReport.svelte frontend/src/lib/components/SeoReport.test.ts
git commit -m "Show sources and brand position in the report"
```

---

### Task 6: QA — фейк, локаторы и сквозной сценарий

**Files:**
- Modify: `qa/pages/fake_api.py`, `qa/pages/seo.py`, `qa/tests/test_search.py`, `qa/README.md`

**Interfaces:**
- Consumes: селекторы из Task 5.
- Produces: `SeoChatPage.brand_position(key)`, `SeoChatPage.source_domain(domain)`, `SeoChatPage.model_coverage`; в фейке — `citation`, `position`, `sources` и поля строки модели (`answer_mode`, `search_status`, `citations`).

- [ ] **Step 1: Расширить фейк и page object**

В `completed_snapshot`/`agent_snapshot` добавить `citation` и `position` в блоки `site.ai`, ключ `sources` с двумя доменами и в строку модели — `answer_mode: "deepseek_web"`, `search_status: "completed"`, `citations: [{url, title}]`. В `SeoChatPage` добавить локаторы по новым `data-*`.

- [ ] **Step 2: Написать падающую проверку**

`qa/tests/test_search.py`, в сценарий агентного прогона:

```python
expect(chat.source_domain("habr.com")).to_contain_text("2")
expect(chat.brand_position("first")).to_have_text("30 %")
expect(chat.model_coverage).to_contain_text("из")
expect(chat.metric_text("ai-qa-run-connection-all-citation")).toBe("50 %")
```

- [ ] **Step 3: Запустить QA и убедиться, что проверка падает**

Run: `cd qa && QA_HEADLESS=1 .venv/bin/pytest -q tests/test_search.py`
Expected: FAIL — локаторы не находят элементы.

- [ ] **Step 4: Довести сценарий до зелёного**

Run: `cd qa && QA_HEADLESS=1 .venv/bin/pytest -q`
Expected: PASS, все проверки.

- [ ] **Step 5: Обновить `qa/README.md`**

Добавить в таблицу «Что покрыто» строки про источники, позицию бренда и покрытие опроса; в список якорей — новые `data-*`.

- [ ] **Step 6: Коммит**

```bash
git add qa/pages/fake_api.py qa/pages/seo.py qa/tests/test_search.py qa/README.md
git commit -m "Check the sources and the brand position end to end"
```

---

## Self-Review

- **Покрытие спеки**: лимиты и категория — Task 1; позиция бренда — Task 2; источники (`citation` + `sources`) — Task 3; типы и проекции — Task 4; секции отчёта, покрытие и режим ответа — Task 5; QA и документация — Task 6; README/tech.md — Task 1, `qa/README.md` — Task 6.
- **Review Focus**: (1) текстовый режим — тесты Task 3 (`test_a_row_without_completed_web_search_never_reaches_sources`) и Task 5 («—» вместо 0); (2) один абзац — тест Task 2; (3) свой хост — тест Task 3; (4) нет кандидатов — тест Task 2; (5) `search_status == "error"` — тот же тест Task 3.
- **Согласованность имён**: `_brand_position`, `_source_counts`, `position`, `sources`, `citation`, `SeoBrandPositionResponse`, `SeoSourceCountResponse`, `SEO_CATEGORY_LABELS` используются одинаково во всех задачах.
- **Пропорция**: план описывает решения и проверки, а не тела функций.
