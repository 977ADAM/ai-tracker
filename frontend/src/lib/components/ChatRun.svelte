<script lang="ts">
  import type {
    SeoAnalysisSnapshot,
    SeoModelRow,
    SeoRowsKind,
    SeoSearchRow,
    SeoTraceStep,
  } from '$lib/types';
  import SeoRunProgress from './SeoRunProgress.svelte';
  import SeoReport from './SeoReport.svelte';
  import SeoTraceFeed from './SeoTraceFeed.svelte';

  /**
   * One run card inside the chat feed. While the analysis runs it is the live
   * progress panel; in a terminal state it is a compact summary whose report
   * stays folded until the user asks for it — the report is heavy, and a chat
   * with several finished runs must stay readable.
   */
  let {
    snapshot,
    analysisId,
    cancelling = false,
    rows = { model: [], search: [] },
    cursors = { model: null, search: null },
    loadingRows = null,
    traces = { steps: [], cursor: null, loading: false, error: '' },
    connectionNames = {},
    error = '',
    onCancel = () => {},
    onMoreRows = () => {},
    onMoreTrace = () => {},
    onOpenReport = () => {},
  }: {
    snapshot: SeoAnalysisSnapshot | null;
    analysisId: string;
    cancelling?: boolean;
    rows?: { model: SeoModelRow[]; search: SeoSearchRow[] };
    cursors?: { model: string | null; search: string | null };
    loadingRows?: SeoRowsKind | null;
    traces?: { steps: SeoTraceStep[]; cursor: string | null; loading: boolean; error: string };
    connectionNames?: Record<string, string>;
    error?: string;
    onCancel?: () => void;
    onMoreRows?: (kind: SeoRowsKind) => void;
    onMoreTrace?: () => void;
    onOpenReport?: () => void;
  } = $props();

  const STATUS_LABELS: Record<SeoAnalysisSnapshot['status'], string> = {
    running: 'Выполняется',
    completed: 'Завершён',
    failed: 'Ошибка',
    interrupted: 'Прерван',
    cancelled: 'Отменён',
  };

  let reportOpen = $state(false);

  /** The rows are fetched on the first opening; a closing keeps what is loaded. */
  function toggleReport(): void {
    if (!reportOpen) onOpenReport();
    reportOpen = !reportOpen;
  }

  function terminalNote(status: SeoAnalysisSnapshot['status']): string {
    if (status === 'completed') return 'Анализ завершён, результат сохранён.';
    if (status === 'cancelled')
      return 'Анализ отменён. Полученные строки сохранены, продолжить прогон нельзя.';
    if (status === 'interrupted')
      return 'Прогон прерван перезапуском приложения. Сохранённые строки доступны.';
    return 'Прогон остановлен из-за ошибки этапа. Платные проверки не были продолжены.';
  }
</script>

{#if !snapshot}
  <section
    data-chat-run
    data-analysis-id={analysisId}
    aria-busy="true"
    class="rounded-xl border border-dashed border-line bg-white px-4 py-3.5 shadow-sm"
  >
    <p class="text-[13px] font-semibold text-muted">Загружаем прогон…</p>
    <p class="mt-1 text-[11px] leading-4 text-muted">
      Карточка появится, когда приложение получит состояние анализа.
    </p>
  </section>
{:else if snapshot.status === 'running'}
  <div data-chat-run data-analysis-id={analysisId}>
    <SeoRunProgress
      {snapshot}
      {cancelling}
      {onCancel}
      trace={traces.steps}
      traceCursor={traces.cursor}
      traceLoading={traces.loading}
      traceError={traces.error}
      onTraceMore={onMoreTrace}
    />
  </div>
{:else}
  <section
    data-chat-run
    data-analysis-id={analysisId}
    aria-labelledby={`chat-run-title-${analysisId}`}
    class="rounded-xl border border-line bg-white px-3.5 py-1.5 shadow-sm"
  >
    <div class="flex flex-wrap items-start justify-between gap-2">
      <div>
        <h2 id={`chat-run-title-${analysisId}`} class="text-[13px] font-bold tracking-tight">
          Прогон SEO-анализа
        </h2>
        <p class="mt-1 text-[13px] text-muted">Анализ {analysisId}</p>
      </div>
      <span
        data-run-status
        class="rounded-full border border-line bg-canvas px-4 py-1.5 text-[13px] font-semibold text-ink"
      >
        {STATUS_LABELS[snapshot.status]}
      </span>
    </div>

    <p class="mt-3 text-[13px] leading-5 text-muted" data-run-counters>
      Запросы: {snapshot.counters.queries} · Яндекс: {snapshot.counters.search_rows}
      (ошибок {snapshot.counters.search_errors}) · модели: {snapshot.counters.model_rows}
      (ошибок {snapshot.counters.model_errors})
    </p>

    <p class="mt-2 text-[13px] leading-5 text-ink" data-run-note>{terminalNote(snapshot.status)}</p>

    <div class="mt-2.5 border-t border-line pt-4">
      <button
        type="button"
        onclick={toggleReport}
        aria-expanded={reportOpen}
        class="inline-flex min-h-8 items-center rounded-xl border border-line bg-white px-5 py-1.5 text-[13px] font-semibold text-ink hover:border-accent"
        data-report-toggle
      >
        {reportOpen ? 'Скрыть отчёт' : 'Открыть отчёт'}
      </button>
    </div>

    {#if reportOpen}
      <!--
        The agent trace of a finished run stays reachable: the report and the
        trace unfold together. The trace sits right under the toggle so it is
        not buried under the long report.
      -->
      <SeoTraceFeed
        steps={traces.steps}
        nextCursor={traces.cursor}
        loading={traces.loading}
        error={traces.error}
        onMore={onMoreTrace}
      />
      <SeoReport
        {snapshot}
        {rows}
        {cursors}
        {connectionNames}
        {loadingRows}
        {error}
        onMore={onMoreRows}
      />
    {/if}
  </section>
{/if}
