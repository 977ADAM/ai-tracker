<script lang="ts">
  import { onDestroy, onMount, untrack } from 'svelte';
  import SeoForm from '$lib/components/SeoForm.svelte';
  import SeoHistory from '$lib/components/SeoHistory.svelte';
  import SeoReport from '$lib/components/SeoReport.svelte';
  import SeoRunProgress from '$lib/components/SeoRunProgress.svelte';
  import { hasAgentState } from '$lib/seo-agents';
  import { validateSeoForm } from '$lib/seo-form';
  import type { SeoFormInput } from '$lib/seo-form';
  import type {
    FormConfig, PublicProvider, SeoAnalysisCreated, SeoAnalysisSnapshot, SeoHistoryItem, SeoHistoryPage,
    SeoModelRow, SeoRowsKind, SeoRowsPage, SeoSearchRow, SeoTracePage, SeoTraceStep
  } from '$lib/types';

  type Data = {
    providers: PublicProvider[];
    form?: FormConfig | null;
    loadError: string;
  };
  let { data }: { data: Data } = $props();

  const POLL_INTERVAL_MS = 30_000;
  let activeId = $state<string | null>(null);
  let pendingId = $state<string | null>(null);
  let snapshot = $state<SeoAnalysisSnapshot | null>(null);
  let error = $state(untrack(() => data.loadError));
  let runError = $state('');
  let cancelling = $state(false);
  let pollTimer: ReturnType<typeof setTimeout> | undefined;
  let destroyed = false;

  // The SEO history and the report detail are independent resources: a failure
  // in either one must never take the form or the run screen down with it.
  let history = $state<SeoHistoryItem[]>([]);
  let historyCursor = $state<string | null>(null);
  let historyLoading = $state(false);
  let historyError = $state('');
  let reportRows = $state<{ model: SeoModelRow[]; search: SeoSearchRow[] }>({ model: [], search: [] });
  let reportCursors = $state<{ model: string | null; search: string | null }>({ model: null, search: null });
  let rowsLoading = $state<SeoRowsKind | null>(null);
  let rowsError = $state('');

  // The agent trace is its own paginated resource. An analysis from before the
  // agent runtime has no steps at all, so nothing is requested for it; once a
  // run does have agents, the first page is kept fresh while the run lasts and
  // the user's own paging is never thrown away by a poll.
  let trace = $state<SeoTraceStep[]>([]);
  let traceCursor = $state<string | null>(null);
  let traceLoading = $state(false);
  let traceError = $state('');
  let traceId = $state<string | null>(null);
  let tracePaged = $state(false);

  const terminal = $derived(!!snapshot && snapshot.status !== 'running');
  const connectionNames = $derived(Object.fromEntries(data.providers.map((provider) => [provider.id, provider.name])));

  function detail(value: unknown, fallback: string): string {
    return value !== null && typeof value === 'object' && 'detail' in value && typeof value.detail === 'string'
      ? value.detail : fallback;
  }
  async function payload(response: Response): Promise<unknown> {
    try { return await response.json(); }
    catch { return null; }
  }
  function stopPolling() {
    if (pollTimer !== undefined) clearTimeout(pollTimer);
    pollTimer = undefined;
  }
  function schedulePoll(id: string) {
    stopPolling();
    pollTimer = setTimeout(() => void pollAnalysis(id), POLL_INTERVAL_MS);
  }

  const EMPTY_ROWS = { model: [], search: [] };
  const EMPTY_CURSORS = { model: null, search: null };

  async function loadRows(id: string, kind: SeoRowsKind, cursor: string | null, append: boolean) {
    rowsLoading = kind;
    try {
      const query = cursor === null ? `kind=${kind}` : `kind=${kind}&cursor=${encodeURIComponent(cursor)}`;
      const response = await fetch(`/api/seo/analyses/${encodeURIComponent(id)}/rows?${query}`);
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось загрузить строки отчёта'));
      if (destroyed || activeId !== id) return;
      const page = value as SeoRowsPage;
      if (kind === 'model') {
        const items = page.items as SeoModelRow[];
        reportRows = { ...reportRows, model: append ? [...reportRows.model, ...items] : items };
        reportCursors = { ...reportCursors, model: page.next_cursor };
      } else {
        const items = page.items as SeoSearchRow[];
        reportRows = { ...reportRows, search: append ? [...reportRows.search, ...items] : items };
        reportCursors = { ...reportCursors, search: page.next_cursor };
      }
      rowsError = '';
    } catch (cause) {
      if (destroyed || activeId !== id) return;
      rowsError = cause instanceof Error ? cause.message : 'Не удалось загрузить строки отчёта';
    } finally {
      if (rowsLoading === kind) rowsLoading = null;
    }
  }

  /** The detail rows come from saved data only: opening a report never pays for a new call. */
  async function loadReport(id: string, status: SeoAnalysisSnapshot['status']) {
    reportRows = EMPTY_ROWS;
    reportCursors = EMPTY_CURSORS;
    rowsError = '';
    if (status === 'running') return;
    await Promise.all([
      loadRows(id, 'model', null, false),
      loadRows(id, 'search', null, false)
    ]);
  }

  function resetTrace() {
    trace = [];
    traceCursor = null;
    traceError = '';
    traceId = null;
    tracePaged = false;
    traceLoading = false;
  }

  /** One trace page: the first page replaces the feed, later pages append to it. */
  async function loadTrace(id: string, cursor: string | null, append: boolean) {
    traceLoading = true;
    try {
      const query = cursor === null ? '' : `?cursor=${encodeURIComponent(cursor)}`;
      const response = await fetch(`/api/seo/analyses/${encodeURIComponent(id)}/trace${query}`);
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось загрузить трассу агентов'));
      if (destroyed || activeId !== id) return;
      const page = value as SeoTracePage;
      trace = append ? [...trace, ...page.items] : page.items;
      traceCursor = page.next_cursor;
      traceId = id;
      traceError = '';
      if (append) tracePaged = true;
    } catch (cause) {
      if (destroyed || activeId !== id) return;
      traceError = cause instanceof Error ? cause.message : 'Не удалось загрузить трассу агентов';
    } finally {
      if (!destroyed && activeId === id) traceLoading = false;
    }
  }

  /** A trace failure must never break the run screen, so it is only best-effort. */
  async function syncTrace(id: string, current: SeoAnalysisSnapshot) {
    if (!hasAgentState(current.agents)) return;
    if (tracePaged && traceId === id) return;
    await loadTrace(id, null, false);
  }

  function loadMoreTrace() {
    if (!snapshot) return;
    void loadTrace(snapshot.id, traceCursor, true);
  }

  async function loadAnalysis(id: string) {
    activeId = id;
    runError = '';
    reportRows = EMPTY_ROWS;
    reportCursors = EMPTY_CURSORS;
    rowsError = '';
    resetTrace();
    try {
      const response = await fetch(`/api/seo/analyses/${encodeURIComponent(id)}`);
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось открыть анализ'));
      if (destroyed || activeId !== id) return;
      const current = value as SeoAnalysisSnapshot;
      snapshot = current;
      if (current.status === 'running') { pendingId = id; schedulePoll(id); }
      else { pendingId = null; stopPolling(); }
      await syncTrace(id, current);
      await loadReport(id, current.status);
    } catch (cause) {
      if (destroyed) return;
      runError = cause instanceof Error ? cause.message : 'Не удалось открыть анализ';
    }
  }

  async function pollAnalysis(id: string) {
    if (destroyed || pendingId !== id) return;
    try {
      const response = await fetch(`/api/seo/analyses/${encodeURIComponent(id)}`);
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось получить состояние анализа'));
      if (destroyed || pendingId !== id) return;
      const current = value as SeoAnalysisSnapshot;
      snapshot = current;
      runError = '';
      await syncTrace(id, current);
      if (current.status === 'running') schedulePoll(id);
      else {
        pendingId = null;
        stopPolling();
        // The report is read from the saved rows, which are complete by now.
        await loadReport(id, current.status);
        await loadHistory();
      }
    } catch (cause) {
      if (destroyed) return;
      runError = cause instanceof Error ? cause.message : 'Не удалось обновить анализ';
      schedulePoll(id);
    }
  }

  async function loadHistory(cursor: string | null = null) {
    historyLoading = true;
    historyError = '';
    try {
      const path = cursor === null
        ? '/api/seo/analyses'
        : `/api/seo/analyses?cursor=${encodeURIComponent(cursor)}`;
      const response = await fetch(path);
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось загрузить SEO-историю'));
      if (destroyed) return;
      const page = value as SeoHistoryPage;
      history = cursor === null ? page.items : [...history, ...page.items];
      historyCursor = page.next_cursor;
      if (cursor === null) {
        const active = page.items.find((item) => item.status === 'running');
        if (active && !pendingId) await loadAnalysis(active.id);
      }
    } catch (cause) {
      if (destroyed) return;
      historyError = cause instanceof Error ? cause.message : 'Не удалось загрузить SEO-историю';
    } finally {
      historyLoading = false;
    }
  }

  async function startAnalysis(input: SeoFormInput) {
    error = '';
    runError = '';
    try {
      const response = await fetch('/api/seo/analyses', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          url: input.url.trim(),
          sphere: input.sphere.trim(),
          seeds: input.seeds.map((seed) => seed.trim()).filter((seed) => seed.length > 0),
          services: input.services.map((service) => service.trim()).filter((service) => service.length > 0),
          connection_ids: input.connectionIds
        })
      });
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось запустить анализ'));
      const created = value as SeoAnalysisCreated;
      snapshot = null;
      await loadAnalysis(created.id);
      void loadHistory();
    } catch (cause) {
      throw cause instanceof Error ? cause : new Error('Не удалось запустить анализ');
    }
  }
  function submit(input: SeoFormInput) {
    error = '';
    const problem = validateSeoForm(input);
    if (problem) { error = problem; return; }
    return startAnalysis(input);
  }

  async function cancel() {
    if (!activeId || cancelling) return;
    cancelling = true;
    runError = '';
    try {
      const response = await fetch(`/api/seo/analyses/${encodeURIComponent(activeId)}/cancel`, { method: 'POST' });
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось отменить анализ'));
      if (destroyed) return;
      const current = value as SeoAnalysisSnapshot;
      snapshot = current;
      pendingId = null;
      stopPolling();
      await syncTrace(current.id, current);
      await loadReport(current.id, current.status);
      await loadHistory();
    } catch (cause) {
      if (destroyed) return;
      runError = cause instanceof Error ? cause.message : 'Не удалось отменить анализ';
    } finally {
      cancelling = false;
    }
  }

  /** Opening a saved analysis reads the database only; nothing is paid for again. */
  async function openAnalysis(id: string) {
    await loadAnalysis(id);
  }

  function loadMoreRows(kind: SeoRowsKind) {
    if (!snapshot) return;
    void loadRows(snapshot.id, kind, reportCursors[kind], true);
  }

  async function removeAnalysis(id: string) {
    historyError = '';
    try {
      const response = await fetch(`/api/seo/analyses/${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(detail(await payload(response), 'Не удалось удалить SEO-анализ'));
      if (destroyed) return;
      history = history.filter((item) => item.id !== id);
      if (activeId === id) {
        activeId = null;
        pendingId = null;
        snapshot = null;
        stopPolling();
        reportRows = EMPTY_ROWS;
        reportCursors = EMPTY_CURSORS;
        rowsError = '';
        resetTrace();
      }
    } catch (cause) {
      if (destroyed) return;
      historyError = cause instanceof Error ? cause.message : 'Не удалось удалить SEO-анализ';
    }
  }

  onMount(() => { void loadHistory(); });
  onDestroy(() => { destroyed = true; stopPolling(); });
</script>

<svelte:head><title>ИИ-трекинг · SEO-анализ сайта</title></svelte:head>

<main class="mx-48 max-w-[1920px] px-4 pb-16 sm:px-6 lg:px-8">
    <nav aria-label="Хлебные крошки" class="flex items-center gap-2 py-6 text-xs font-medium text-muted">
        <a href="/" class="hover:text-accent">Инструменты</a>
        <span aria-hidden="true">/</span>
        <span class="text-ink">SEO-анализ сайта</span>
    </nav>

    <section class="relative overflow-hidden rounded-3xl bg-ink px-6 py-10 text-white shadow-lg shadow-ink/10 sm:px-10 sm:py-12 lg:px-14">
        <div class="relative max-w-4xl">
            <p class="mb-5 text-xs font-bold tracking-[0.16em] text-emerald-200 uppercase">SEO-анализ сайта и конкурентов</p>
            <h1 class="text-3xl font-bold leading-tight sm:text-4xl lg:text-5xl">Узнайте, где виден ваш сайт</h1>
            <p class="mt-6 max-w-3xl text-sm leading-7 text-emerald-50/90 sm:text-base">
                Один запуск: система обходит сайт, ищет конкурентов в Яндексе, генерирует запросы, проверяет их в ИИ и Поиске и собирает отчёт. Прогон можно отменить, а результаты сохраняются.
            </p>
        </div>
    </section>

    <SeoForm
        providers={data.providers}
        form={data.form ?? null}
        disabled={!!data.loadError || !data.form}
        error={error}
        onSubmit={submit}
    />

    {#if runError}
        <p role="alert" class="mt-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {runError}
        </p>
    {/if}

    {#if snapshot}
        <div class="scroll-mt-8" id="seo-run">
            <SeoRunProgress
                {snapshot}
                {cancelling}
                onCancel={() => void cancel()}
                {trace}
                traceCursor={traceCursor}
                traceLoading={traceLoading}
                traceError={traceError}
                onTraceMore={loadMoreTrace}
            />
        </div>
    {:else}
        <section class="mt-8 rounded-3xl border border-dashed border-line bg-white px-6 py-14 text-center shadow-sm">
            <h2 class="text-xl font-bold">Пока нет SEO-анализа</h2>
            <p class="mt-2 text-sm text-muted">Заполните форму выше и запустите первый анализ. Незавершённый прогон возобновится после перезагрузки страницы.</p>
        </section>
    {/if}

    {#if terminal && snapshot}
        <SeoReport
            {snapshot}
            rows={reportRows}
            cursors={reportCursors}
            {connectionNames}
            loadingRows={rowsLoading}
            error={rowsError}
            onMore={loadMoreRows}
        />
    {/if}

    <aside class="mt-8 rounded-2xl border border-line bg-accent-soft px-6 py-5 text-sm leading-6 text-ink">
        <strong>Как читать результат</strong>
        <p class="mt-2 text-muted">
            Поиск проверяет только первую десятку органических результатов Яндекса по всей России. Ошибка отдельного источника не означает, что сайта нет в выдаче: такие строки исключаются из метрик. Если в знаменателе нет ни одной успешной строки, отчёт показывает «—», а не ноль процентов.
        </p>
    </aside>

    <SeoHistory
        items={history}
        nextCursor={historyCursor}
        onView={(id) => void openAnalysis(id)}
        onDelete={(id) => void removeAnalysis(id)}
        onMore={() => void loadHistory(historyCursor)}
        loading={historyLoading}
        error={historyError}
    />
</main>
