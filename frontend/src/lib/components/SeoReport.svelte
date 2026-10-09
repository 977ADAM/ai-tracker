<script lang="ts">
  import { tick } from 'svelte';
  import { markdownHtml, plainText } from '$lib/markdown';
  import { SEO_CATEGORY_LABELS } from '$lib/seo-categories';
  import type {
    SeoAnalysisSnapshot,
    SeoCompetitorAggregates,
    SeoMetric,
    SeoModelRow,
    SeoRowStatus,
    SeoRowsKind,
    SeoSearchRow,
  } from '$lib/types';

  let {
    snapshot,
    rows = { model: [], search: [] },
    cursors = { model: null, search: null },
    connectionNames = {},
    loadingRows = null,
    error = '',
    onMore = () => {},
  }: {
    snapshot: SeoAnalysisSnapshot;
    rows?: { model: SeoModelRow[]; search: SeoSearchRow[] };
    cursors?: { model: string | null; search: string | null };
    connectionNames?: Record<string, string>;
    loadingRows?: SeoRowsKind | null;
    error?: string;
    onMore?: (kind: SeoRowsKind) => void;
  } = $props();

  // A saved answer can be thousands of characters long. The table shows a short
  // preview, so one row never grows to the height of the whole answer; the full
  // text opens in a dialog on click and is rendered there as Markdown.
  const ANSWER_PREVIEW_CHARS = 160;

  let openAnswer = $state<{
    query: string;
    provider: string;
    text: string;
    citations: SeoModelRow['citations'];
  } | null>(null);
  let answerClose = $state<HTMLButtonElement | null>(null);
  let answerButton = $state<HTMLButtonElement | null>(null);

  /** Whether the answer is longer than its preview, so the dialog is offered. */
  function answerIsLong(text: string): boolean {
    return plainText(text).length > ANSWER_PREVIEW_CHARS;
  }

  function answerPreview(text: string): string {
    const plain = plainText(text);
    return answerIsLong(text) ? `${plain.slice(0, ANSWER_PREVIEW_CHARS).trimEnd()}…` : plain;
  }

  /** Open one answer; the focus moves into the dialog and comes back on close. */
  async function showAnswer(row: SeoModelRow, trigger: HTMLButtonElement): Promise<void> {
    openAnswer = {
      query: row.query ?? 'Ответ модели',
      provider: row.provider_name || connectionLabel(row.connection_id),
      text: row.answer ?? '',
      citations: row.citations ?? [],
    };
    answerButton = trigger;
    await tick();
    answerClose?.focus();
  }

  async function closeAnswer(): Promise<void> {
    openAnswer = null;
    await tick();
    answerButton?.focus();
  }

  const ROW_STATUS_LABELS: Record<SeoRowStatus, string> = {
    pending: 'Ожидает',
    submitting: 'Отправляем запрос',
    waiting: 'Яндекс считает',
    found: 'Найдено',
    absent: 'Не найдено',
    error: 'Ошибка',
    interrupted: 'Прервано',
    cancelled: 'Отменено',
  };

  const ANALYSIS_STATUS_LABELS: Record<SeoAnalysisSnapshot['status'], string> = {
    running: 'Выполняется',
    completed: 'Завершён',
    failed: 'Ошибка',
    interrupted: 'Прерван',
    cancelled: 'Отменён',
  };

  // One compact vocabulary for every table of the report: a dense row keeps the
  // whole report readable without a nested scroll area of its own.
  const th = 'px-3 py-1.5 text-[11px] font-semibold tracking-wide text-muted uppercase';
  const td = 'px-3 py-1.5 align-top';
  const rowHead = 'px-3 py-1.5 font-medium text-ink';
  const section = 'mt-4';
  const title = 'text-sm font-semibold text-ink';
  const table = 'w-full border-collapse text-left text-[13px]';

  const siteSearch = $derived(snapshot.aggregates?.site?.search ?? null);
  const siteAi = $derived(snapshot.aggregates?.site?.ai ?? {});
  const competitors = $derived(snapshot.aggregates?.competitors ?? []);
  const sources = $derived(snapshot.aggregates?.sources ?? []);
  const connections = $derived(Object.keys(siteAi));

  /**
   * The saved part of the poll: how many `query × connection` pairs the run has
   * an answer for. M is the planned number of pairs, N the saved model rows.
   */
  const modelCoverage = $derived.by(() => {
    const pairs = (snapshot.queries?.length ?? 0) * (snapshot.input.connection_ids?.length ?? 0);
    if (pairs === 0) return '—';
    return `${snapshot.counters?.model_rows ?? 0} из ${pairs}`;
  });

  function connectionLabel(connectionId: string): string {
    return connectionNames[connectionId] ?? connectionId;
  }

  /**
   * One share as a whole percent.
   *
   * `null` — an empty denominator, a missing metric, or a company name that was
   * never extracted — is rendered as «—» and never as «0 %».
   */
  function percent(metric: SeoMetric | null | undefined, unavailable = false): string {
    if (unavailable || metric === null || metric === undefined) return '—';
    if (metric.share === null || metric.share === undefined) return '—';
    return `${Math.round(metric.share * 100)} %`;
  }

  /** The denominator behind a share: «3 из 5». */
  function fraction(metric: SeoMetric | null | undefined): string {
    if (metric === null || metric === undefined) return '—';
    if (typeof metric.denominator !== 'number') return '—';
    return `${metric.successes ?? 0} из ${metric.denominator}`;
  }

  /** The mean top-ten position of a metric; «—» when nothing was found. */
  function metricPosition(metric: SeoMetric | null | undefined): string {
    if (metric === null || metric === undefined) return '—';
    return position(metric.average_position);
  }

  function position(value: number | null | undefined): string {
    return value === null || value === undefined
      ? '—'
      : value.toLocaleString('ru-RU', { maximumFractionDigits: 2 });
  }

  /** The candidate's seed queries as the user typed them; «№n» when the seed is gone. */
  function seedLabels(candidate: SeoCompetitorAggregates): string {
    if (candidate.seed_indexes.length === 0) return '—';
    return candidate.seed_indexes
      .map((index) => snapshot.input.seeds[index] ?? `№${index + 1}`)
      .join(', ');
  }

  function aiHostShare(candidate: SeoCompetitorAggregates, connectionId: string): string {
    return percent(candidate.ai?.[connectionId]?.host);
  }

  function rowStatus(status: SeoRowStatus): string {
    return ROW_STATUS_LABELS[status] ?? status;
  }

  function answerMode(mode: SeoModelRow['answer_mode']): string {
    return mode === 'deepseek_web' ? 'веб-поиск' : 'текст';
  }

  /** The cited sources of one answer; an answer without sources is «—», never «0». */
  function sourceCount(citations: SeoModelRow['citations']): string {
    const count = citations?.length ?? 0;
    return count === 0 ? '—' : String(count);
  }

  function categoryLabel(category: string | null): string {
    if (!category) return '—';
    return SEO_CATEGORY_LABELS[category] ?? category;
  }

  function mention(value: boolean | null): string {
    if (value === null) return '—';
    return value ? 'Да' : 'Нет';
  }

  function dateLabel(value: string | null): string {
    if (!value) return '—';
    return new Date(value).toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Europe/Moscow',
    });
  }
</script>

<section
  class="mt-4 rounded-xl border border-line bg-white px-4 py-3.5 shadow-sm"
  aria-labelledby="seo-report-title"
  data-seo-report
>
  <div class="flex flex-wrap items-center justify-between gap-2">
    <h2 id="seo-report-title" class="text-base font-bold tracking-tight">Отчёт SEO-анализа</h2>
    <span
      class="rounded-full border border-line bg-canvas px-2.5 py-0.5 text-xs font-semibold text-ink"
      data-report-status
    >
      {ANALYSIS_STATUS_LABELS[snapshot.status]}
    </span>
  </div>

  <p class="mt-1 text-xs leading-5 text-muted" aria-label="Параметры анализа" data-report-params>
    <a class="break-all text-accent hover:underline" href={snapshot.input.url}
      >{snapshot.input.host}</a
    >
    · {snapshot.company_name || '—'}
    · {snapshot.input.sphere || '—'}
    · {dateLabel(snapshot.created_at)}
  </p>

  {#if error}
    <p
      role="alert"
      class="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"
    >
      {error}
    </p>
  {/if}

  <section class={section} aria-labelledby="seo-site-title">
    <h3 id="seo-site-title" class={title}>Сайт в Яндексе</h3>
    <div class="mt-2 overflow-x-auto rounded-lg border border-line">
      <table class={`${table} min-w-160`} aria-label="Сайт в Яндексе">
        <thead class="bg-canvas">
          <tr>
            <th scope="col" class={th}>Срез</th>
            <th scope="col" class={th}>Доля в топ-10</th>
            <th scope="col" class={th}>Найдено</th>
            <th scope="col" class={th}>Средняя позиция</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line">
          {#each [['overall', 'Все запросы'], ['branded', 'С названием компании'], ['unbranded', 'Без названия компании']] as [key, label] (key)}
            <tr>
              <th scope="row" class={rowHead}>{label}</th>
              <td class={td} data-metric={`site-${key}`}
                >{percent(siteSearch?.[key as 'overall'])}</td
              >
              <td class={`${td} text-muted`}>{fraction(siteSearch?.[key as 'overall'])}</td>
              <td class={`${td} text-muted`}>{metricPosition(siteSearch?.[key as 'overall'])}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>

  <section class={section} aria-labelledby="seo-ai-title">
    <h3 id="seo-ai-title" class={title}>Упоминания в ответах ИИ</h3>
    <p class="mt-1 text-xs text-muted">
      Опрос моделей: <span class="font-medium text-ink" data-model-coverage>{modelCoverage}</span
      >{#if modelCoverage !== '—'}
        пар{/if}
    </p>
    {#if connections.length === 0}
      <p class="mt-2 text-xs text-muted">Ответы моделей не сохранены.</p>
    {:else}
      {#each connections as connectionId (connectionId)}
        <div class="mt-2 overflow-x-auto rounded-lg border border-line">
          <table
            class={`${table} min-w-200`}
            aria-label={`Упоминания: ${connectionLabel(connectionId)}`}
          >
            <caption class="bg-canvas px-3 py-1.5 text-left text-xs font-semibold text-ink"
              >{connectionLabel(connectionId)}</caption
            >
            <thead class="bg-canvas">
              <tr>
                <th scope="col" class={th}>Срез</th>
                <th scope="col" class={th}>Название</th>
                <th scope="col" class={th}>Домен</th>
                <th scope="col" class={th}>Название или домен</th>
                <th scope="col" class={th}>В источниках</th>
                <th scope="col" class={th}>Позиция домена</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line">
              {#each [['all', 'Все ответы'], ['branded', 'Брендовые запросы'], ['unbranded', 'Небрендовые запросы']] as [group, label] (group)}
                {@const block =
                  group === 'all'
                    ? siteAi[connectionId]
                    : siteAi[connectionId]?.[group as 'branded']}
                <tr>
                  <th scope="row" class={rowHead}>{label}</th>
                  <td class={td} data-metric={`ai-${connectionId}-${group}-name`}
                    >{percent(block?.name, !snapshot.company_name)}</td
                  >
                  <td class={td} data-metric={`ai-${connectionId}-${group}-host`}
                    >{percent(block?.host)}</td
                  >
                  <td class={td} data-metric={`ai-${connectionId}-${group}-combined`}
                    >{percent(block?.combined, !snapshot.company_name)}</td
                  >
                  <td class={td} data-metric={`ai-${connectionId}-${group}-citation`}
                    >{percent(block?.citation)}</td
                  >
                  <td
                    class={`${td} text-muted`}
                    data-position={`ai-${connectionId}-${group}-citation`}
                    >{metricPosition(block?.citation)}</td
                  >
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/each}
    {/if}
  </section>

  <section class={section} aria-labelledby="seo-brand-position-title">
    <h3 id="seo-brand-position-title" class={title}>Позиция бренда</h3>
    <p class="mt-1 text-xs text-muted">
      Эвристика по абзацам ответа: где название компании или домен впервые встречаются в тексте.
    </p>
    <div class="mt-2 overflow-x-auto rounded-lg border border-line">
      <table class={`${table} min-w-200`} aria-label="Позиция бренда">
        <thead class="bg-canvas">
          <tr>
            <th scope="col" class={th}>Подключение</th>
            <th scope="col" class={th}>В первом абзаце</th>
            <th scope="col" class={th}>Во 2–3 абзацах</th>
            <th scope="col" class={th}>Ниже</th>
            <th scope="col" class={th}>Не назван</th>
            <th scope="col" class={th}>Раньше конкурентов</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line">
          {#each connections as connectionId (connectionId)}
            {@const brand = siteAi[connectionId]?.position ?? null}
            <tr>
              <th scope="row" class={rowHead}>{connectionLabel(connectionId)}</th>
              <td class={td} data-brand-position="first">{percent(brand?.first)}</td>
              <td class={td} data-brand-position="early">{percent(brand?.early)}</td>
              <td class={td} data-brand-position="late">{percent(brand?.late)}</td>
              <td class={td} data-brand-position="absent">{percent(brand?.absent)}</td>
              <td class={td} data-brand-position="ahead">{percent(brand?.ahead)}</td>
            </tr>
          {:else}
            <tr>
              <th scope="row" class={rowHead}>—</th>
              <td class={td} data-brand-position="first">—</td>
              <td class={td} data-brand-position="early">—</td>
              <td class={td} data-brand-position="late">—</td>
              <td class={td} data-brand-position="absent">—</td>
              <td class={td} data-brand-position="ahead">—</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>

  <section class={section} aria-labelledby="seo-sources-title">
    <h3 id="seo-sources-title" class={title}>Источники</h3>
    <p class="mt-1 text-xs text-muted">
      Домены, которые модели цитируют; источники есть только у подключений с веб-поиском.
    </p>
    {#if sources.length === 0}
      <p class="mt-2 text-xs text-muted" data-sources-empty>—</p>
    {:else}
      <div class="mt-2 overflow-x-auto rounded-lg border border-line">
        <table class={table} aria-label="Источники">
          <thead class="bg-canvas">
            <tr>
              <th scope="col" class={th}>Домен</th>
              <th scope="col" class={th}>Ответов</th>
              <th scope="col" class={th}>Цитат</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-line">
            {#each sources as source (source.domain)}
              <tr data-source-row>
                <th scope="row" class={rowHead} data-source-domain={source.domain}
                  >{source.domain}</th
                >
                <td class={`${td} text-muted`} data-source-answers>{source.answers}</td>
                <td class={`${td} text-muted`} data-source-citations>{source.citations}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>

  <section class={section} aria-labelledby="seo-competitors-title">
    <h3 id="seo-competitors-title" class={title}>Повторяющиеся кандидаты</h3>
    <p class="mt-1 text-xs text-muted">
      Домены минимум из двух успешных ключевых выдач; заголовок — только evidence.
    </p>
    {#if competitors.length === 0}
      <p class="mt-2 text-xs text-muted">
        Повторяющихся кандидатов нет: не хватило успешных ключевых выдач.
      </p>
    {:else}
      {#each competitors as candidate (candidate.host)}
        <article
          class="mt-2 rounded-lg border border-line px-3 py-2.5"
          data-candidate={candidate.host}
          aria-labelledby={`seo-candidate-${candidate.host}`}
        >
          <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h4 id={`seo-candidate-${candidate.host}`} class="text-sm font-semibold text-ink">
              {candidate.host}
            </h4>
            <p class="text-xs text-muted">
              Появлений: <span class="font-medium text-ink" data-candidate-occurrences
                >{candidate.occurrences}</span
              >
              · средняя позиция:
              <span class="font-medium text-ink">{position(candidate.average_position)}</span>
              · запросы: <span class="font-medium text-ink">{seedLabels(candidate)}</span>
            </p>
          </div>
          <p class="mt-1 text-xs leading-5 text-muted">
            <span class="font-medium text-ink">Заголовок как evidence:</span>
            {candidate.title || '—'}
          </p>

          <div class="mt-2 grid gap-2 lg:grid-cols-2">
            <div class="overflow-x-auto rounded-lg border border-line">
              <table class={table} aria-label={`Яндекс: ${candidate.host}`}>
                <thead class="bg-canvas">
                  <tr>
                    <th scope="col" class={th}>Срез Яндекса</th>
                    <th scope="col" class={th}>Топ-10</th>
                    <th scope="col" class={th}>Найдено</th>
                    <th scope="col" class={th}>Средняя позиция</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-line">
                  {#each [['overall', 'Все запросы'], ['branded', 'С доменом'], ['unbranded', 'Без домена']] as [key, label] (key)}
                    <tr>
                      <th scope="row" class={rowHead}>{label}</th>
                      <td class={td} data-metric={`candidate-${candidate.host}-${key}`}
                        >{percent(candidate.search?.[key as 'overall'])}</td
                      >
                      <td class={`${td} text-muted`}
                        >{fraction(candidate.search?.[key as 'overall'])}</td
                      >
                      <td class={`${td} text-muted`}
                        >{metricPosition(candidate.search?.[key as 'overall'])}</td
                      >
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>

            <div class="overflow-x-auto rounded-lg border border-line">
              <table class={table} aria-label={`ИИ: ${candidate.host}`}>
                <thead class="bg-canvas">
                  <tr>
                    <th scope="col" class={th}>Подключение</th>
                    <th scope="col" class={th}>Доля ответов с доменом</th>
                    <th scope="col" class={th}>В источниках</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-line">
                  {#if connections.length === 0}
                    <tr><td class={td} colspan="3">—</td></tr>
                  {:else}
                    {#each connections as connectionId (connectionId)}
                      <tr>
                        <th scope="row" class={rowHead}>{connectionLabel(connectionId)}</th>
                        <td
                          class={td}
                          data-metric={`candidate-${candidate.host}-ai-${connectionId}`}
                          >{aiHostShare(candidate, connectionId)}</td
                        >
                        <td
                          class={td}
                          data-metric={`candidate-${candidate.host}-citation-${connectionId}`}
                          >{percent(candidate.ai?.[connectionId]?.citation)}</td
                        >
                      </tr>
                    {/each}
                  {/if}
                </tbody>
              </table>
            </div>
          </div>
        </article>
      {/each}
    {/if}
  </section>

  <section class={section} aria-labelledby="seo-details-title">
    <h3 id="seo-details-title" class={title}>Детализация</h3>

    <div class="mt-2 overflow-x-auto rounded-lg border border-line">
      <table class={`${table} min-w-200`} aria-label="Проверки в Яндексе">
        <caption class="bg-canvas px-3 py-1.5 text-left text-xs font-semibold text-ink"
          >Проверки в Яндексе</caption
        >
        <thead class="bg-canvas">
          <tr>
            <th scope="col" class={th}>Запрос</th>
            <th scope="col" class={th}>Категория</th>
            <th scope="col" class={th}>Услуга</th>
            <th scope="col" class={th}>Статус</th>
            <th scope="col" class={th}>Позиция</th>
            <th scope="col" class={th}>Ссылка</th>
            <th scope="col" class={th}>Ошибка</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line">
          {#each rows.search as row (row.query_index)}
            <tr data-search-detail data-status={row.status}>
              <th scope="row" class={`${rowHead} max-w-80`}>{row.query ?? '—'}</th>
              <td class={`${td} text-muted`}>{categoryLabel(row.category)}</td>
              <td class={`${td} text-muted`}>{row.service ?? '—'}</td>
              <td class={td}>{rowStatus(row.status)}</td>
              <td class={`${td} text-muted`}>{row.site_position ?? '—'}</td>
              <td class={`${td} text-muted`}>
                {#if row.site_url}
                  <a
                    class="break-all text-accent hover:underline"
                    href={row.site_url}
                    target="_blank"
                    rel="noopener noreferrer">{row.site_url}</a
                  >
                {:else}
                  —
                {/if}
              </td>
              <td class={`${td} text-rose-700`}>{row.error ?? '—'}</td>
            </tr>
          {:else}
            <tr><td class={td} colspan="7">Сохранённых строк Яндекса нет.</td></tr>
          {/each}
        </tbody>
      </table>
      {#if cursors.search}
        <div class="border-t border-line px-3 py-1.5">
          <button
            type="button"
            onclick={() => onMore('search')}
            disabled={loadingRows === 'search'}
            class="rounded-lg border border-line px-3 py-1 text-xs font-semibold hover:border-accent disabled:opacity-50"
          >
            {loadingRows === 'search' ? 'Загружаем…' : 'Показать ещё'}
          </button>
        </div>
      {/if}
    </div>

    <div class="mt-2 overflow-x-auto rounded-lg border border-line">
      <table class={`${table} min-w-250`} aria-label="Ответы моделей">
        <caption class="bg-canvas px-3 py-1.5 text-left text-xs font-semibold text-ink"
          >Ответы моделей</caption
        >
        <thead class="bg-canvas">
          <tr>
            <th scope="col" class={th}>Запрос</th>
            <th scope="col" class={th}>Подключение</th>
            <th scope="col" class={th}>Статус</th>
            <th scope="col" class={th}>Режим</th>
            <th scope="col" class={th}>Источников</th>
            <th scope="col" class={th}>Название</th>
            <th scope="col" class={th}>Домен</th>
            <th scope="col" class={th}>Ответ</th>
            <th scope="col" class={th}>Ошибка</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line">
          {#each rows.model as row (`${row.connection_id}-${row.query_index}`)}
            <tr data-model-detail data-status={row.status}>
              <th scope="row" class={`${rowHead} max-w-80`}>{row.query ?? '—'}</th>
              <td class={`${td} text-muted`}
                >{row.provider_name || connectionLabel(row.connection_id)}</td
              >
              <td class={td}>{rowStatus(row.status)}</td>
              <td class={`${td} text-muted`} data-answer-mode>{answerMode(row.answer_mode)}</td>
              <td class={`${td} text-muted`} data-answer-sources-count
                >{sourceCount(row.citations)}</td
              >
              <td class={`${td} text-muted`}>{mention(row.name_mentioned)}</td>
              <td class={`${td} text-muted`}>{mention(row.host_mentioned)}</td>
              <td class={`${td} max-w-96`}>
                {#if row.answer}
                  <p class="break-words whitespace-pre-wrap" data-model-answer-preview>
                    {answerPreview(row.answer)}
                  </p>
                  {#if answerIsLong(row.answer)}
                    <button
                      type="button"
                      onclick={(event) => void showAnswer(row, event.currentTarget)}
                      class="mt-1.5 rounded-lg border border-line px-2.5 py-1 text-xs font-semibold text-ink hover:border-accent"
                      data-answer-open
                    >
                      Читать полностью
                    </button>
                  {/if}
                {:else}
                  —
                {/if}
              </td>
              <td class={`${td} text-rose-700`}>{row.error ?? '—'}</td>
            </tr>
          {:else}
            <tr><td class={td} colspan="9">Сохранённых ответов моделей нет.</td></tr>
          {/each}
        </tbody>
      </table>
      {#if cursors.model}
        <div class="border-t border-line px-3 py-1.5">
          <button
            type="button"
            onclick={() => onMore('model')}
            disabled={loadingRows === 'model'}
            class="rounded-lg border border-line px-3 py-1 text-xs font-semibold hover:border-accent disabled:opacity-50"
          >
            {loadingRows === 'model' ? 'Загружаем…' : 'Показать ещё'}
          </button>
        </div>
      {/if}
    </div>
  </section>

  {#if openAnswer}
    <div class="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6">
      <div
        class="absolute inset-0 bg-black/70"
        data-answer-backdrop
        onclick={() => void closeAnswer()}
        aria-hidden="true"
      ></div>
      <div
        class="relative flex max-h-full w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-line bg-white shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="seo-answer-title"
        tabindex="-1"
        data-answer-dialog
        onkeydown={(event) => {
          if (event.key === 'Escape') {
            event.stopPropagation();
            void closeAnswer();
          }
        }}
      >
        <div
          class="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5"
        >
          <div class="min-w-0">
            <h3 id="seo-answer-title" class="text-sm font-bold text-ink">Ответ модели</h3>
            <p class="mt-0.5 text-xs break-words text-muted" data-answer-caption>
              {openAnswer.provider}{openAnswer.query ? ` · ${openAnswer.query}` : ''}
            </p>
          </div>
          <button
            type="button"
            bind:this={answerClose}
            onclick={() => void closeAnswer()}
            class="inline-flex shrink-0 items-center rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-ink hover:border-accent"
            data-answer-close
          >
            Закрыть
          </button>
        </div>
        <div
          class="prose prose-sm min-h-0 max-w-none flex-1 overflow-y-auto px-4 py-3 text-ink"
          data-answer-full
        >
          {@html markdownHtml(openAnswer.text)}
          {#if openAnswer.citations.length > 0}
            <div class="not-prose mt-4 border-t border-line pt-3" data-answer-sources>
              <h4 class="text-[11px] font-semibold tracking-wide text-muted uppercase">
                Источники ответа
              </h4>
              <ul class="mt-1.5 space-y-1 text-xs" data-answer-sources-list>
                <!-- One answer can cite the same URL twice (refs accumulate across text
                     blocks), so the key is the position: the list mirrors the row's
                     citation count and no source is dropped. -->
                {#each openAnswer.citations as citation, index (index)}
                  <li>
                    <a
                      class="break-all text-accent hover:underline"
                      href={citation.url}
                      target="_blank"
                      rel="noopener noreferrer">{citation.title || citation.url}</a
                    >
                  </li>
                {/each}
              </ul>
            </div>
          {/if}
        </div>
      </div>
    </div>
  {/if}
</section>
