<script lang="ts">
  import { tick } from 'svelte';
  import { markdownHtml, plainText } from '$lib/markdown';
  import type {
    SeoAnalysisSnapshot, SeoCategoryAggregates, SeoCompetitorAggregates, SeoMetric, SeoModelRow,
    SeoRowStatus, SeoRowsKind, SeoSearchRow
  } from '$lib/types';

  let {
    snapshot,
    rows = { model: [], search: [] },
    cursors = { model: null, search: null },
    connectionNames = {},
    loadingRows = null,
    error = '',
    onMore = (_kind: SeoRowsKind) => {}
  }: {
    snapshot: SeoAnalysisSnapshot;
    rows?: { model: SeoModelRow[]; search: SeoSearchRow[] };
    cursors?: { model: string | null; search: string | null };
    connectionNames?: Record<string, string>;
    loadingRows?: SeoRowsKind | null;
    error?: string;
    onMore?: (kind: SeoRowsKind) => void;
  } = $props();

  /** The three report categories, in the order the backend evaluates them. */
  const CATEGORY_LABELS: readonly { key: string; label: string }[] = [
    { key: 'commercial', label: 'Коммерческие' },
    { key: 'informational', label: 'Информационные' },
    { key: 'comparative', label: 'Сравнительные' }
  ];

  // A saved answer can be thousands of characters long. The table shows a short
  // preview, so one row never grows to the height of the whole answer; the full
  // text opens in a dialog on click and is rendered there as Markdown.
  const ANSWER_PREVIEW_CHARS = 160;

  let openAnswer = $state<{ query: string; provider: string; text: string } | null>(null);
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
      text: row.answer ?? ''
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
    cancelled: 'Отменено'
  };

  const ANALYSIS_STATUS_LABELS: Record<SeoAnalysisSnapshot['status'], string> = {
    running: 'Выполняется',
    completed: 'Завершён',
    failed: 'Ошибка',
    interrupted: 'Прерван',
    cancelled: 'Отменён'
  };

  const th = 'px-4 py-3 text-xs font-bold tracking-wide text-muted uppercase';
  const td = 'px-4 py-4 align-top';

  const siteSearch = $derived(snapshot.aggregates?.site?.search ?? null);
  const siteAi = $derived(snapshot.aggregates?.site?.ai ?? {});
  const competitors = $derived(snapshot.aggregates?.competitors ?? []);
  const categories = $derived(snapshot.aggregates?.categories ?? {});
  const services = $derived(snapshot.aggregates?.services ?? {});
  const counters = $derived(snapshot.counters);
  const connections = $derived(Object.keys(siteAi));

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
    return value === null || value === undefined ? '—' : value.toLocaleString('ru-RU', { maximumFractionDigits: 2 });
  }

  function counter(value: number | null | undefined): string {
    return typeof value === 'number' ? String(value) : '0';
  }

  function categoryGroup(key: string): SeoCategoryAggregates | null {
    return categories[key] ?? null;
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

  function mention(value: boolean | null): string {
    if (value === null) return '—';
    return value ? 'Да' : 'Нет';
  }

  function dateLabel(value: string | null): string {
    if (!value) return '—';
    return new Date(value).toLocaleString('ru-RU', {
      day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
      timeZone: 'Europe/Moscow'
    });
  }
</script>

<section class="mt-8 rounded-3xl border border-line bg-white px-6 py-7 shadow-sm sm:px-8" aria-labelledby="seo-report-title" data-seo-report>
  <div class="flex flex-wrap items-start justify-between gap-4">
    <div>
      <h2 id="seo-report-title" class="text-2xl font-bold tracking-tight">Отчёт SEO-анализа</h2>
      <p class="mt-2 text-sm leading-6 text-muted">
        Числа рассчитаны только по сохранённым строкам. Ошибка, прерывание и отмена не считаются
        отсутствием сайта или упоминания: такие строки исключены из знаменателя.
      </p>
    </div>
    <span class="rounded-full border border-line bg-canvas px-4 py-1.5 text-sm font-semibold text-ink" data-report-status>
      {ANALYSIS_STATUS_LABELS[snapshot.status]}
    </span>
  </div>

  <dl class="mt-6 grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4" aria-label="Параметры анализа">
    <div class="rounded-xl border border-line bg-canvas/40 px-4 py-3">
      <dt class="text-xs font-semibold text-muted">Сайт</dt>
      <dd class="mt-1 break-all font-medium text-ink"><a class="hover:text-accent" href={snapshot.input.url}>{snapshot.input.host}</a></dd>
    </div>
    <div class="rounded-xl border border-line bg-canvas/40 px-4 py-3">
      <dt class="text-xs font-semibold text-muted">Название компании</dt>
      <dd class="mt-1 font-medium text-ink">{snapshot.company_name || '—'}</dd>
    </div>
    <div class="rounded-xl border border-line bg-canvas/40 px-4 py-3">
      <dt class="text-xs font-semibold text-muted">Сфера бизнеса</dt>
      <dd class="mt-1 font-medium text-ink">{snapshot.input.sphere || '—'}</dd>
    </div>
    <div class="rounded-xl border border-line bg-canvas/40 px-4 py-3">
      <dt class="text-xs font-semibold text-muted">Создан</dt>
      <dd class="mt-1 font-medium text-ink">{dateLabel(snapshot.created_at)}</dd>
    </div>
  </dl>

  <div class="mt-4 rounded-xl border border-line bg-canvas/40 px-4 py-3 text-sm leading-6 text-ink" aria-label="Счётчики прогона">
    <p class="font-semibold">Строки прогона</p>
    <p class="mt-1 text-muted" data-report-counters>
      Запросов: {counter(counters?.queries)} · Яндекса: {counter(counters?.search_rows)}
      (ошибок {counter(counters?.search_errors)}) · моделей: {counter(counters?.model_rows)}
      (ошибок {counter(counters?.model_errors)})
    </p>
  </div>

  {#if error}
    <p role="alert" class="mt-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{error}</p>
  {/if}

  {#if snapshot.summary}
    <section class="mt-6 rounded-xl border border-line bg-accent-soft px-5 py-4" aria-labelledby="seo-summary-title">
      <h3 id="seo-summary-title" class="text-base font-semibold text-ink">Текстовое резюме</h3>
      <div class="prose prose-sm mt-2 max-w-none text-ink" data-report-summary>{@html markdownHtml(snapshot.summary ?? '')}</div>
    </section>
  {/if}

  {#if snapshot.conclusions}
    <section class="mt-6 rounded-xl border border-l-4 border-violet-200 bg-violet-50/70 px-5 py-4" aria-labelledby="seo-conclusions-title" data-report-conclusions>
      <h3 id="seo-conclusions-title" class="text-base font-semibold text-ink">Выводы и рекомендации</h3>
      <p class="mt-1 text-xs font-semibold tracking-wide text-violet-800 uppercase">
        Текст модели{snapshot.conclusions.model ? `: ${snapshot.conclusions.model}` : ''}
      </p>
      <div class="prose prose-sm mt-3 max-w-none text-ink" data-conclusions-summary>{@html markdownHtml(snapshot.conclusions.summary)}</div>
      {#if snapshot.conclusions.recommendations}
        <h4 class="mt-4 text-sm font-semibold text-ink">Рекомендации</h4>
        <div class="prose prose-sm mt-2 max-w-none text-ink" data-conclusions-recommendations>{@html markdownHtml(snapshot.conclusions.recommendations)}</div>
      {/if}
      <p class="mt-3 text-xs leading-5 text-muted">
        Это текст языковой модели, а не расчёт. Он не заменяет и не изменяет числа отчёта.
      </p>
    </section>
  {/if}

  <section class="mt-8" aria-labelledby="seo-site-title">
    <h3 id="seo-site-title" class="text-xl font-bold tracking-tight">Сайт в Яндексе</h3>
    <p class="mt-1 text-sm text-muted">Доля сгенерированных запросов, где сайт попал в первую десятку, и средняя позиция среди находок.</p>
    <div class="mt-4 overflow-x-auto rounded-2xl border border-line">
      <table class="w-full min-w-160 border-collapse text-left text-sm" aria-label="Сайт в Яндексе">
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
              <th scope="row" class="px-4 py-4 font-medium text-ink">{label}</th>
              <td class={td} data-metric={`site-${key}`}>{percent(siteSearch?.[key as 'overall'])}</td>
              <td class={`${td} text-muted`}>{fraction(siteSearch?.[key as 'overall'])}</td>
              <td class={`${td} text-muted`}>{metricPosition(siteSearch?.[key as 'overall'])}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>

  <section class="mt-8" aria-labelledby="seo-ai-title">
    <h3 id="seo-ai-title" class="text-xl font-bold tracking-tight">Упоминания в ответах ИИ</h3>
    <p class="mt-1 text-sm text-muted">
      Доля успешных ответов с буквальным упоминанием названия компании, её домена и хотя бы одного из них.
    </p>
    {#if connections.length === 0}
      <p class="mt-4 text-sm text-muted">Ответы моделей не сохранены.</p>
    {:else}
      {#each connections as connectionId (connectionId)}
        <div class="mt-4 overflow-x-auto rounded-2xl border border-line">
          <table class="w-full min-w-160 border-collapse text-left text-sm" aria-label={`Упоминания: ${connectionLabel(connectionId)}`}>
            <caption class="bg-canvas px-4 py-3 text-left text-sm font-semibold text-ink">{connectionLabel(connectionId)}</caption>
            <thead class="bg-canvas">
              <tr>
                <th scope="col" class={th}>Срез</th>
                <th scope="col" class={th}>Название</th>
                <th scope="col" class={th}>Домен</th>
                <th scope="col" class={th}>Название или домен</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line">
              {#each [['all', 'Все ответы'], ['branded', 'Брендовые запросы'], ['unbranded', 'Небрендовые запросы']] as [group, label] (group)}
                {@const block = group === 'all' ? siteAi[connectionId] : siteAi[connectionId]?.[group as 'branded']}
                <tr>
                  <th scope="row" class="px-4 py-4 font-medium text-ink">{label}</th>
                  <td class={td} data-metric={`ai-${connectionId}-${group}-name`}>{percent(block?.name, !snapshot.company_name)}</td>
                  <td class={td} data-metric={`ai-${connectionId}-${group}-host`}>{percent(block?.host)}</td>
                  <td class={td} data-metric={`ai-${connectionId}-${group}-combined`}>{percent(block?.combined, !snapshot.company_name)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/each}
    {/if}
  </section>

  <section class="mt-8" aria-labelledby="seo-competitors-title">
    <h3 id="seo-competitors-title" class="text-xl font-bold tracking-tight">Повторяющиеся кандидаты</h3>
    <p class="mt-1 text-sm text-muted">
      Это кандидаты в конкуренты: домены, встретившиеся минимум в двух успешных ключевых выдачах.
      Заголовок из выдачи — только evidence, метрики считаются по домену.
    </p>
    {#if competitors.length === 0}
      <p class="mt-4 text-sm text-muted">Повторяющихся кандидатов нет: не хватило успешных ключевых выдач.</p>
    {:else}
      {#each competitors as candidate (candidate.host)}
        <article class="mt-4 rounded-2xl border border-line px-5 py-5" data-candidate={candidate.host} aria-labelledby={`seo-candidate-${candidate.host}`}>
          <h4 id={`seo-candidate-${candidate.host}`} class="text-lg font-bold tracking-tight text-ink">{candidate.host}</h4>
          <dl class="mt-3 grid gap-3 text-sm sm:grid-cols-3">
            <div>
              <dt class="text-xs font-semibold text-muted">Появлений в ключевых выдачах</dt>
              <dd class="mt-1 font-medium text-ink" data-candidate-occurrences>{candidate.occurrences}</dd>
            </div>
            <div>
              <dt class="text-xs font-semibold text-muted">Средняя позиция в ключевых выдачах</dt>
              <dd class="mt-1 font-medium text-ink">{position(candidate.average_position)}</dd>
            </div>
            <div>
              <dt class="text-xs font-semibold text-muted">Исходные ключевые запросы</dt>
              <dd class="mt-1 font-medium text-ink">{seedLabels(candidate)}</dd>
            </div>
          </dl>
          <p class="mt-3 text-sm leading-6 text-muted">
            <span class="font-semibold text-ink">Заголовок как evidence:</span>
            {candidate.title || '—'}
          </p>

          <div class="mt-4 overflow-x-auto rounded-xl border border-line">
            <table class="w-full min-w-160 border-collapse text-left text-sm" aria-label={`Яндекс: ${candidate.host}`}>
              <thead class="bg-canvas">
                <tr>
                  <th scope="col" class={th}>Срез Яндекса</th>
                  <th scope="col" class={th}>Доля в топ-10</th>
                  <th scope="col" class={th}>Найдено</th>
                  <th scope="col" class={th}>Средняя позиция</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-line">
                {#each [['overall', 'Все запросы'], ['branded', 'Запросы с доменом'], ['unbranded', 'Запросы без домена']] as [key, label] (key)}
                  <tr>
                    <th scope="row" class="px-4 py-4 font-medium text-ink">{label}</th>
                    <td class={td} data-metric={`candidate-${candidate.host}-${key}`}>{percent(candidate.search?.[key as 'overall'])}</td>
                    <td class={`${td} text-muted`}>{fraction(candidate.search?.[key as 'overall'])}</td>
                    <td class={`${td} text-muted`}>{metricPosition(candidate.search?.[key as 'overall'])}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>

          <div class="mt-4 overflow-x-auto rounded-xl border border-line">
            <table class="w-full min-w-160 border-collapse text-left text-sm" aria-label={`ИИ: ${candidate.host}`}>
              <thead class="bg-canvas">
                <tr>
                  <th scope="col" class={th}>Подключение</th>
                  <th scope="col" class={th}>Доля ответов с доменом</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-line">
                {#if connections.length === 0}
                  <tr><td class={td} colspan="2">—</td></tr>
                {:else}
                  {#each connections as connectionId (connectionId)}
                    <tr>
                      <th scope="row" class="px-4 py-4 font-medium text-ink">{connectionLabel(connectionId)}</th>
                      <td class={td} data-metric={`candidate-${candidate.host}-ai-${connectionId}`}>{aiHostShare(candidate, connectionId)}</td>
                    </tr>
                  {/each}
                {/if}
              </tbody>
            </table>
          </div>
        </article>
      {/each}
    {/if}
  </section>

  {#if Object.keys(categories).length > 0}
    <section class="mt-8" aria-labelledby="seo-categories-title">
      <h3 id="seo-categories-title" class="text-xl font-bold tracking-tight">Разрезы по категориям</h3>
      <div class="mt-4 overflow-x-auto rounded-2xl border border-line">
        <table class="w-full min-w-160 border-collapse text-left text-sm" aria-label="Разрезы по категориям">
          <thead class="bg-canvas">
            <tr>
              <th scope="col" class={th}>Категория</th>
              <th scope="col" class={th}>Яндекс: доля в топ-10</th>
              <th scope="col" class={th}>Средняя позиция</th>
              {#each connections as connectionId (connectionId)}
                <th scope="col" class={th}>ИИ: {connectionLabel(connectionId)}</th>
              {/each}
            </tr>
          </thead>
          <tbody class="divide-y divide-line">
            {#each CATEGORY_LABELS as group (group.key)}
              {@const block = categoryGroup(group.key)}
              <tr>
                <th scope="row" class="px-4 py-4 font-medium text-ink">{group.label}</th>
                <td class={td} data-metric={`category-${group.key}`}>{percent(block?.search)}</td>
                <td class={`${td} text-muted`}>{metricPosition(block?.search)}</td>
                {#each connections as connectionId (connectionId)}
                  <td class={`${td} text-muted`}>{percent(block?.ai?.[connectionId], !snapshot.company_name)}</td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>
  {/if}

  {#if Object.keys(services).length > 0}
    <section class="mt-8" aria-labelledby="seo-services-title">
      <h3 id="seo-services-title" class="text-xl font-bold tracking-tight">Разрезы по услугам</h3>
      <div class="mt-4 overflow-x-auto rounded-2xl border border-line">
        <table class="w-full min-w-160 border-collapse text-left text-sm" aria-label="Разрезы по услугам">
          <thead class="bg-canvas">
            <tr>
              <th scope="col" class={th}>Услуга</th>
              <th scope="col" class={th}>Яндекс: доля в топ-10</th>
              <th scope="col" class={th}>Средняя позиция</th>
              {#each connections as connectionId (connectionId)}
                <th scope="col" class={th}>ИИ: {connectionLabel(connectionId)}</th>
              {/each}
            </tr>
          </thead>
          <tbody class="divide-y divide-line">
            {#each Object.entries(services) as [service, block] (service)}
              <tr>
                <th scope="row" class="px-4 py-4 font-medium text-ink">{service || 'Без услуги'}</th>
                <td class={td} data-metric={`service-${service || 'none'}`}>{percent(block.search)}</td>
                <td class={`${td} text-muted`}>{metricPosition(block.search)}</td>
                {#each connections as connectionId (connectionId)}
                  <td class={`${td} text-muted`}>{percent(block.ai?.[connectionId], !snapshot.company_name)}</td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>
  {/if}

  <section class="mt-8" aria-labelledby="seo-details-title">
    <h3 id="seo-details-title" class="text-xl font-bold tracking-tight">Детализация</h3>
    <p class="mt-1 text-sm text-muted">
      Сохранённые строки прогона: ошибки, прерванные и отменённые строки показаны как есть
      и не превращаются в «нет».
    </p>

    <div class="mt-4 overflow-x-auto rounded-2xl border border-line">
      <table class="w-full min-w-200 border-collapse text-left text-sm" aria-label="Проверки в Яндексе">
        <caption class="bg-canvas px-4 py-3 text-left text-sm font-semibold text-ink">Проверки в Яндексе</caption>
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
              <th scope="row" class="max-w-80 px-4 py-4 font-medium text-ink">{row.query ?? '—'}</th>
              <td class={`${td} text-muted`}>{row.category ?? '—'}</td>
              <td class={`${td} text-muted`}>{row.service ?? '—'}</td>
              <td class={td}>{rowStatus(row.status)}</td>
              <td class={`${td} text-muted`}>{row.site_position ?? '—'}</td>
              <td class={`${td} text-muted`}>
                {#if row.site_url}
                  <a class="break-all text-accent hover:underline" href={row.site_url} target="_blank" rel="noopener noreferrer">{row.site_url}</a>
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
        <div class="border-t border-line px-4 py-3">
          <button
            type="button"
            onclick={() => onMore('search')}
            disabled={loadingRows === 'search'}
            class="rounded-xl border border-line px-4 py-2 text-sm font-semibold hover:border-accent disabled:opacity-50"
          >
            {loadingRows === 'search' ? 'Загружаем…' : 'Показать ещё'}
          </button>
        </div>
      {/if}
    </div>

    <div class="mt-6 overflow-x-auto rounded-2xl border border-line">
      <table class="w-full min-w-225 border-collapse text-left text-sm" aria-label="Ответы моделей">
        <caption class="bg-canvas px-4 py-3 text-left text-sm font-semibold text-ink">Ответы моделей</caption>
        <thead class="bg-canvas">
          <tr>
            <th scope="col" class={th}>Запрос</th>
            <th scope="col" class={th}>Подключение</th>
            <th scope="col" class={th}>Статус</th>
            <th scope="col" class={th}>Название</th>
            <th scope="col" class={th}>Домен</th>
            <th scope="col" class={th}>Ответ</th>
            <th scope="col" class={th}>Ошибка</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line">
          {#each rows.model as row (`${row.connection_id}-${row.query_index}`)}
            <tr data-model-detail data-status={row.status}>
              <th scope="row" class="max-w-80 px-4 py-4 font-medium text-ink">{row.query ?? '—'}</th>
              <td class={`${td} text-muted`}>{row.provider_name || connectionLabel(row.connection_id)}</td>
              <td class={td}>{rowStatus(row.status)}</td>
              <td class={`${td} text-muted`}>{mention(row.name_mentioned)}</td>
              <td class={`${td} text-muted`}>{mention(row.host_mentioned)}</td>
              <td class={`${td} max-w-96`}>
                {#if row.answer}
                  <p class="whitespace-pre-wrap break-words" data-model-answer-preview>{answerPreview(row.answer)}</p>
                  {#if answerIsLong(row.answer)}
                    <button
                      type="button"
                      onclick={(event) => void showAnswer(row, event.currentTarget)}
                      class="mt-2 rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-ink hover:border-accent"
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
            <tr><td class={td} colspan="7">Сохранённых ответов моделей нет.</td></tr>
          {/each}
        </tbody>
      </table>
      {#if cursors.model}
        <div class="border-t border-line px-4 py-3">
          <button
            type="button"
            onclick={() => onMore('model')}
            disabled={loadingRows === 'model'}
            class="rounded-xl border border-line px-4 py-2 text-sm font-semibold hover:border-accent disabled:opacity-50"
          >
            {loadingRows === 'model' ? 'Загружаем…' : 'Показать ещё'}
          </button>
        </div>
      {/if}
    </div>
  </section>

  {#if openAnswer}
    <div class="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6">
      <div class="absolute inset-0 bg-black/70" data-answer-backdrop onclick={() => void closeAnswer()} aria-hidden="true"></div>
      <div
        class="relative flex max-h-full w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-line bg-white shadow-2xl"
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
        <div class="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div class="min-w-0">
            <h3 id="seo-answer-title" class="text-base font-bold text-ink">Ответ модели</h3>
            <p class="mt-1 text-xs leading-5 break-words text-muted" data-answer-caption>
              {openAnswer.provider}{openAnswer.query ? ` · ${openAnswer.query}` : ''}
            </p>
          </div>
          <button
            type="button"
            bind:this={answerClose}
            onclick={() => void closeAnswer()}
            class="inline-flex min-h-10 shrink-0 items-center rounded-xl border border-line px-4 py-2 text-sm font-semibold text-ink hover:border-accent"
            data-answer-close
          >
            Закрыть
          </button>
        </div>
        <div
          class="prose prose-sm min-h-0 max-w-none flex-1 overflow-y-auto px-5 py-4 text-ink"
          data-answer-full
        >{@html markdownHtml(openAnswer.text)}</div>
      </div>
    </div>
  {/if}
</section>
