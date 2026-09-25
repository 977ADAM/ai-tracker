<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import { marked } from 'marked';
  import DOMPurify from 'dompurify';
  import SearchReport from '$lib/components/SearchReport.svelte';
  import { MAX_REGIONS, requestCount, requestCountLabel, validateRun } from '$lib/search-form';
  import type { CheckResponse, FormConfig, PublicProvider, SearchCreated, SearchRegion, SearchSnapshot } from '$lib/types';

  type Data = {
    providers: PublicProvider[];
    form?: FormConfig | null;
    loadError: string;
    searchRegions?: SearchRegion[];
    searchRegionError?: string;
  };
  let { data }: { data: Data } = $props();

  // Yandex answers a deferred search in minutes or hours, so the page polls the
  // local status route while it stays open and forgets the job on reload.
  const POLL_INTERVAL_MS = 30_000;
  const EMPTY_SNAPSHOT_ERROR = 'Не удалось получить состояние поиска';

  let selected = $state<string[]>(untrack(() => data.form?.default_provider_ids ?? []));
  let brand = $state('');
  let domain = $state('');
  let promptsText = $state('');
  let regionRows = $state<(number | '')[]>([]);
  let loading = $state(false);
  let error = $state(untrack(() => data.loadError));
  let report = $state<CheckResponse | null>(null);
  let searchStarted = $state(false);
  let searchRunning = $state(false);
  let searchSnapshot = $state<SearchSnapshot | null>(null);
  let searchError = $state('');
  let pollTimer: ReturnType<typeof setTimeout> | undefined;
  let searchToken = 0;

  const catalog = $derived(data.searchRegions ?? []);
  const chosenRegions = $derived(regionRows.filter((value): value is number => typeof value === 'number'));
  const yandexRequests = $derived(requestCount(promptsText, chosenRegions));

  function toggleProvider(id: string) {
    selected = selected.includes(id) ? selected.filter((value) => value !== id) : [...selected, id];
  }

  function addRegion() {
    if (regionRows.length < MAX_REGIONS) regionRows = [...regionRows, ''];
  }

  function removeRegion(index: number) {
    regionRows = regionRows.filter((_, position) => position !== index);
  }

  function regionTaken(id: number, index: number): boolean {
    return regionRows.some((value, position) => position !== index && value === id);
  }

  function stopSearchPolling() {
    if (pollTimer !== undefined) clearTimeout(pollTimer);
    pollTimer = undefined;
  }

  async function runModelCheck() {
    loading = true;
    error = '';
    report = null;
    try {
      const response = await fetch('/api/check', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ brand, domain, prompts_text: promptsText, provider_ids: selected })
      });
      const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : 'Не удалось выполнить проверку');
      report = value as CheckResponse;
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Не удалось выполнить проверку';
    } finally {
      loading = false;
    }
  }

  async function readSearchStatus(id: string, token: number) {
    try {
      const response = await fetch(`/api/search/${encodeURIComponent(id)}`);
      const value = await response.json();
      if (token !== searchToken) return;
      if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : EMPTY_SNAPSHOT_ERROR);
      searchSnapshot = value as SearchSnapshot;
      if (searchSnapshot.status === 'done') {
        searchRunning = false;
        stopSearchPolling();
        return;
      }
      pollTimer = setTimeout(() => void readSearchStatus(id, token), POLL_INTERVAL_MS);
    } catch (cause) {
      if (token !== searchToken) return;
      searchRunning = false;
      stopSearchPolling();
      searchError = cause instanceof Error ? cause.message : EMPTY_SNAPSHOT_ERROR;
    }
  }

  async function runSearch(payload: { domain: string; prompts_text: string; regions: number[] }) {
    // A newer run makes every answer of the previous one irrelevant.
    const token = ++searchToken;
    stopSearchPolling();
    searchStarted = true;
    searchRunning = true;
    searchSnapshot = null;
    searchError = '';
    try {
      const response = await fetch('/api/search', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const value = await response.json();
      if (token !== searchToken) return;
      if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : 'Не удалось запустить поиск');
      await readSearchStatus((value as SearchCreated).id, token);
    } catch (cause) {
      if (token !== searchToken) return;
      searchRunning = false;
      searchError = cause instanceof Error ? cause.message : 'Не удалось запустить поиск';
    }
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    const problem = validateRun({ brand, domain, promptsText, providerIds: selected, regions: chosenRegions });
    if (problem) {
      error = problem;
      return;
    }
    // The two branches are independent: one may fail, the other still reports.
    if (selected.length > 0) void runModelCheck();
    if (chosenRegions.length > 0) void runSearch({ domain, prompts_text: promptsText, regions: chosenRegions });
  }

  onDestroy(stopSearchPolling);

  marked.setOptions({ breaks: true, gfm: true });

  function renderMarkdown(text: string): string {
    const html = marked.parse(text, { async: false }) as string;
    return DOMPurify.sanitize(html);
  }
</script>

<svelte:head><title>ИИ-трекинг · Проверка бренда</title></svelte:head>

<main class="mx-48 max-w-[1920px] px-4 pb-16 sm:px-6 lg:px-8">
  <nav aria-label="Хлебные крошки" class="flex items-center gap-2 py-6 text-xs font-medium text-muted">
    <a href="/" class="hover:text-accent focus-visible:outline-2 focus-visible:outline-accent">Инструменты</a>
    <span aria-hidden="true">/</span>
    <span class="text-ink">Проверка бренда</span>
  </nav>

  <section class="relative overflow-hidden rounded-3xl bg-ink px-6 py-10 text-white shadow-lg shadow-ink/10 sm:px-10 sm:py-12 lg:px-14">
    <div class="pointer-events-none absolute -top-32 -right-24 size-96 rounded-full border border-white/15" aria-hidden="true"></div>
    <div class="pointer-events-none absolute -right-8 -bottom-48 size-96 rounded-full bg-accent/30 blur-3xl" aria-hidden="true"></div>
    <div class="relative max-w-4xl">
      <p class="mb-5 text-xs font-bold tracking-[0.16em] text-emerald-200 uppercase">Проверка ответов подключённых моделей</p>
      <h1 class="max-w-4xl text-3xl font-bold leading-tight tracking-tight sm:text-4xl lg:text-5xl">Узнайте, упоминает ли ИИ ваш бренд</h1>
      <p class="mt-6 max-w-3xl text-sm leading-7 text-emerald-50/90 sm:text-base">
        Задайте вопросы выбранным моделям и узнайте, встретилось ли название бренда в их ответах. Результат показывает ответы API на момент проверки.
      </p>
    </div>
  </section>

  <section class="mt-8 overflow-hidden rounded-3xl border border-line bg-white shadow-sm shadow-ink/5" aria-labelledby="check-title">
    <form onsubmit={submit} novalidate class="space-y-7 px-6 py-7 sm:px-8">
      <div class="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]">
        <div>
          <label for="prompts" class="mb-2 block text-sm font-semibold text-ink">Вопросы клиентов <span class="text-rose-600">*</span></label>
          <textarea id="prompts" class="block min-h-56 w-full resize-y rounded-xl border border-line bg-canvas/50 px-4 py-3 text-sm leading-6 text-ink outline-none transition placeholder:text-muted/70 focus:border-accent focus:bg-white focus:ring-4 focus:ring-accent/15" bind:value={promptsText}></textarea>
          <div class="mt-2 flex justify-between gap-4 text-xs text-muted"><p>Каждый вопрос — с новой строки{data.form ? `, до ${data.form.limits.max_prompt_length} символов` : ''}</p><span class="shrink-0">{data.form ? `До ${data.form.limits.max_prompts} вопросов` : ''}</span></div>
        </div>
        <div class="space-y-5">
          <div>
            <label for="brand" class="mb-2 block text-sm font-semibold text-ink">Название бренда <span class="text-rose-600">*</span></label>
            <input id="brand" class="block w-full rounded-xl border border-line bg-canvas/50 px-4 py-3 text-sm text-ink outline-none transition placeholder:text-muted/70 focus:border-accent focus:bg-white focus:ring-4 focus:ring-accent/15" type="text" maxlength={data.form?.limits.max_brand_length} bind:value={brand} />
            <p class="mt-2 text-xs text-muted">Ищем именно это название в тексте ответа</p>
          </div>
          <div>
            <label for="domain" class="mb-2 block text-sm font-semibold text-ink">Сайт <span class="font-normal text-muted">нужен для поиска в Яндексе</span></label>
            <input id="domain" class="block w-full rounded-xl border border-line bg-canvas/50 px-4 py-3 text-sm text-ink outline-none transition placeholder:text-muted/70 focus:border-accent focus:bg-white focus:ring-4 focus:ring-accent/15" type="text" maxlength={data.form?.limits.max_domain_length} bind:value={domain} />
            <p class="mt-2 text-xs text-muted">Домен или ссылка http(s); совпадение ищется по хосту и его поддоменам</p>
          </div>
        </div>
      </div>

      <fieldset class="border-t border-line pt-6">
        <legend class="mb-3 text-sm font-semibold text-ink">Модели для проверки</legend>
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {#each data.providers as provider (provider.id)}
            <label class:opacity-60={!provider.configured} class="flex cursor-pointer items-start gap-3 rounded-xl border border-line bg-white px-4 py-3 transition hover:border-accent/50">
              <input type="checkbox" class="mt-1 size-4 accent-accent" checked={selected.includes(provider.id)} disabled={!provider.configured} onchange={() => toggleProvider(provider.id)} />
              <span class="min-w-0"><span class="block font-semibold text-ink">{provider.name}</span><span class="mt-0.5 block truncate text-xs text-muted">{provider.configured ? provider.model : provider.status_label}</span></span>
            </label>
          {/each}
        </div>
      </fieldset>

      <fieldset class="border-t border-line pt-6" aria-labelledby="regions-legend">
        <legend id="regions-legend" class="mb-3 text-sm font-semibold text-ink">Поиск сайта в Яндексе</legend>
        <p class="mb-4 max-w-3xl text-xs leading-5 text-muted">
          Добавьте от одного до пяти регионов — проверим, попадает ли сайт в первую десятку выдачи по каждому вопросу.
          Без регионов проверяются только модели. Отложенный поиск занимает от нескольких минут до нескольких часов.
        </p>

        {#if data.searchRegionError}
          <p role="alert" class="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{data.searchRegionError}. Проверка моделей работает без него.</p>
        {/if}

        <div class="space-y-3">
          {#each regionRows as value, index (index)}
            <div class="flex items-center gap-3" data-region-row>
              <label class="sr-only" for={`region-${index}`}>Регион {index + 1}</label>
              <select id={`region-${index}`} class="min-h-12 w-full max-w-sm rounded-xl border border-line bg-canvas/50 px-4 py-3 text-sm text-ink outline-none transition focus:border-accent focus:bg-white focus:ring-4 focus:ring-accent/15" bind:value={regionRows[index]}>
                <option value="">Начните вводить регион</option>
                {#each catalog as region (region.id)}
                  <option value={region.id} disabled={regionTaken(region.id, index)}>{region.name}</option>
                {/each}
              </select>
              <button type="button" onclick={() => removeRegion(index)} aria-label={`Удалить регион ${index + 1}`} class="grid size-12 shrink-0 place-items-center rounded-xl border border-line bg-white text-lg text-muted transition hover:border-rose-300 hover:text-rose-700 focus-visible:outline-2 focus-visible:outline-accent">×</button>
            </div>
          {/each}
        </div>

        <button type="button" onclick={addRegion} disabled={regionRows.length >= MAX_REGIONS || !catalog.length} class="mt-4 inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-white px-4 py-2 text-sm font-semibold text-ink transition hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50">＋ Добавить регион</button>

        {#if chosenRegions.length > 0}
          <p class="mt-3 text-xs text-muted">
            <span class="font-semibold text-ink" data-request-count>{requestCountLabel(yandexRequests)}</span>
            — по одному отложенному запросу на пару «вопрос × регион».
          </p>
        {/if}
      </fieldset>

      {#if error}<p role="alert" class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</p>{/if}
      <div class="flex flex-wrap items-center justify-between gap-4 border-t border-line pt-6">
        <p class="max-w-xl text-xs leading-5 text-muted">Вопросы отправляются выбранным моделям по очереди, а Яндекс ищет сайт по каждому вопросу и региону. Результат отражает ответы API и выдачу на момент проверки.</p>
        <button type="submit" disabled={loading || !data.form} class="inline-flex min-h-12 items-center justify-center gap-3 rounded-xl bg-accent px-6 py-3 text-sm font-bold text-white shadow-sm transition hover:bg-accent-dark focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-wait disabled:opacity-60">{loading ? 'Проверяем…' : 'Проверить бренд'}<span aria-hidden="true">↗</span></button>
      </div>
    </form>
  </section>

  {#if loading}
    <section class="mt-8 rounded-3xl border border-line bg-white px-6 py-14 text-center shadow-sm" aria-live="polite">
      <div class="mx-auto grid size-12 place-items-center rounded-2xl bg-accent-soft text-2xl text-accent">◎</div>
      <h2 class="mt-5 text-xl font-bold">Спрашиваем модели…</h2>
      <p class="mt-2 text-sm text-muted">Проверяем вопросы по очереди.</p>
    </section>
  {:else if report}
    <section class="mt-10" aria-labelledby="summary-title">
      <div class="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
            <h2 id="summary-title" class="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">Сводка проверки</h2>
        </div>
        <p class="text-xs text-muted">Бренд: {report.brand}{report.domain ? ` · Сайт: ${report.domain}` : ''}</p>
      </div>
      <div class="grid gap-4 sm:grid-cols-3">
        <article class="rounded-2xl border border-line bg-white p-5 shadow-sm"><p class="text-sm font-semibold text-muted">Видимость бренда</p><p class="mt-4 text-4xl font-bold tracking-tight text-accent">{report.summary.visibility_label}</p><p class="mt-2 text-xs text-muted">{report.summary.mentions_label}</p></article>
        <article class="rounded-2xl border border-line bg-white p-5 shadow-sm"><p class="text-sm font-semibold text-muted">Успешные ответы</p><p class="mt-4 text-4xl font-bold tracking-tight text-ink">{report.summary.successful}</p><p class="mt-2 text-xs text-muted">От {report.checks.length} выбранных моделей</p></article>
        <article class="rounded-2xl border border-line bg-white p-5 shadow-sm"><p class="text-sm font-semibold text-muted">Ошибки запросов</p><p class="mt-4 text-4xl font-bold tracking-tight text-ink">{report.summary.failed}</p><p class="mt-2 text-xs text-muted">{report.summary.errors_label}</p></article>
      </div>
    </section>

    <section class="mt-8 overflow-hidden rounded-3xl border border-line bg-white shadow-sm" aria-labelledby="table-title">
      <div class="border-b border-line px-6 py-5 sm:px-8"><h2 id="table-title" class="text-xl font-bold tracking-tight">Таблица результатов</h2><p class="mt-1 text-sm text-muted">Сводка по каждому вопросу и выбранной модели.</p></div>
      <div class="overflow-x-auto">
        <table aria-label="Таблица результатов" class="w-full min-w-160 border-collapse text-left text-sm">
          <thead class="bg-canvas text-xs font-bold tracking-wide text-muted uppercase"><tr><th scope="col" class="px-6 py-3 sm:px-8">Вопрос</th><th scope="col" class="px-6 py-3">Модель</th><th scope="col" class="px-6 py-3">Ответ API</th><th scope="col" class="px-6 py-3">Бренд</th></tr></thead>
          <tbody class="divide-y divide-line">
            {#each report.rows as row}
              <tr class="align-top"><th scope="row" class="max-w-80 px-6 py-4 font-semibold text-ink sm:px-8">{row.prompt}</th><td class="px-6 py-4 text-muted">{row.provider_name}</td><td class="px-6 py-4 text-muted">{row.error ? 'Ошибка API' : 'Получен'}</td><td class="px-6 py-4"><span class={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${row.error ? 'bg-rose-50 text-rose-700' : row.mentioned ? 'bg-accent-soft text-accent-dark' : 'bg-slate-100 text-slate-600'}`}>{row.error ? '—' : row.mentioned ? 'Есть' : 'Нет'}</span></td></tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>

    <section class="mt-8" aria-labelledby="details-title">
      <div class="mb-5"><h2 id="details-title" class="text-2xl font-bold tracking-tight">Детальный результат</h2><p class="mt-1 text-sm text-muted">Исходные ответы моделей и ошибки по каждому вопросу.</p></div>
      <div class="space-y-6">
        {#each report.checks as check (check.provider_id)}
          <section class="provider-report overflow-hidden rounded-3xl border border-line bg-white shadow-sm" aria-label={`Результаты ${check.provider_name}`}>
            <div class="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-canvas/60 px-6 py-4 sm:px-8"><h3 class="text-lg font-bold">{check.provider_name}</h3><p class="text-xs text-muted">Упоминаний: {check.summary.mentioned} из {check.summary.successful} успешных · Ошибок: {check.summary.failed}</p></div>
            <div class="divide-y divide-line">
              {#each check.results as result, index (`${check.provider_id}-${index}`)}
                <article class="px-6 py-5 sm:px-8">
                    <div class="flex flex-wrap items-start justify-between gap-3"><h4 class="max-w-2xl text-sm font-semibold leading-6">{result.prompt}</h4><span class={`rounded-full px-3 py-1 text-xs font-semibold ${result.error ? 'bg-rose-50 text-rose-700' : result.mentioned ? 'bg-accent-soft text-accent-dark' : 'bg-slate-100 text-slate-600'}`}>{result.error ? 'Ошибка' : result.mentioned ? 'Бренд упомянут' : 'Нет упоминания'}</span></div>
                    <p class="mt-4 text-xs font-bold tracking-wide text-muted uppercase">{result.error ? 'Причина' : 'Ответ модели'}</p>
                    {#if result.error}
                        <p class="mt-2 max-h-72 overflow-auto text-sm leading-7 wrap-anywhere whitespace-pre-wrap text-rose-700">{result.error}</p>
                    {:else}
                        <div class="prose prose-sm max-w-none mt-2 max-h-72 overflow-auto text-ink/85">
                        {@html renderMarkdown(result.answer ?? '')}
                        </div>
                    {/if}
                </article>
              {/each}
            </div>
          </section>
        {/each}
      </div>
    </section>
  {:else if !searchStarted}
    <section class="mt-8 rounded-3xl border border-dashed border-line bg-white px-6 py-14 text-center shadow-sm" aria-labelledby="empty-title">
      <div class="mx-auto grid size-12 place-items-center rounded-2xl bg-accent-soft text-2xl text-accent">◎</div>
      <h2 id="empty-title" class="mt-5 text-xl font-bold">Пока нет проверки</h2>
      <p class="mx-auto mt-2 max-w-md text-sm leading-6 text-muted">Выберите модели, введите бренд и вопросы — или добавьте регион, чтобы проверить сайт в выдаче Яндекса.</p>
    </section>
  {/if}

  {#if searchStarted}
    <SearchReport snapshot={searchSnapshot} error={searchError} />
    {#if searchRunning && !searchError}
      <p class="mt-4 text-xs leading-5 text-muted" aria-live="polite">Поиск идёт в фоне: страница обновляет результат каждые 30 секунд. Результаты не сохраняются — после перезагрузки страницы задача станет недоступна.</p>
    {/if}
  {/if}

  <aside class="mt-8 rounded-2xl border border-line bg-accent-soft px-6 py-5 text-sm leading-6 text-ink"><strong>Как читать результат</strong><p class="mt-2 text-muted">Ответы моделей и выдача Яндекса — это срез на момент проверки. Поиск сообщает только о первой десятке органических результатов по выбранному региону: он не говорит о видимости сайта в интернете в целом, а ошибка запроса не означает, что сайта нет в выдаче.</p></aside>
</main>
