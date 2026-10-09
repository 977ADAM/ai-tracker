<script lang="ts">
  import type { SeoAnalysisSnapshot, SeoStageStatus, SeoTraceStep } from '$lib/types';
  import {
    actualQueryCount,
    queriesGenerated,
    SEO_STAGE_LABELS,
    snapshotActualEstimate,
  } from '$lib/seo-form';
  import { hasAgentState } from '$lib/seo-agents';
  import SeoAgentPanel from './SeoAgentPanel.svelte';
  import SeoTraceFeed from './SeoTraceFeed.svelte';

  let {
    snapshot,
    cancelling = false,
    onCancel,
    trace = [],
    traceCursor = null,
    traceLoading = false,
    traceError = '',
    onTraceMore = () => {},
  }: {
    snapshot: SeoAnalysisSnapshot;
    cancelling?: boolean;
    onCancel: () => void;
    trace?: SeoTraceStep[];
    traceCursor?: string | null;
    traceLoading?: boolean;
    traceError?: string;
    onTraceMore?: () => void;
  } = $props();

  /**
   * Analyses from before the agent runtime carry six `pending` agents with a
   * null `updated_at`; their real progress is in `stages`, so the old list is
   * the honest screen for them.
   */
  const agentRun = $derived(hasAgentState(snapshot.agents));

  function stageStatusLabel(status: SeoStageStatus): string {
    if (status === 'running') return 'Выполняется';
    if (status === 'done') return 'Готово';
    if (status === 'error') return 'Ошибка';
    if (status === 'skipped') return 'Пропущен';
    return 'Ожидает';
  }

  function stageStatusClass(status: SeoStageStatus): string {
    if (status === 'running') return 'text-accent';
    if (status === 'done') return 'text-emerald-700';
    if (status === 'error') return 'text-rose-700';
    if (status === 'skipped') return 'text-muted';
    return 'text-muted';
  }

  function analysisStatusLabel(value: SeoAnalysisSnapshot['status']): string {
    if (value === 'running') return 'Выполняется';
    if (value === 'completed') return 'Завершён';
    if (value === 'failed') return 'Ошибка';
    if (value === 'interrupted') return 'Прерван';
    return 'Отменён';
  }

  const stages = $derived(
    SEO_STAGE_LABELS.map((name, index) => {
      const saved = snapshot.stages.find((item) => item.stage === index + 1);
      return {
        number: index + 1,
        name,
        status: saved?.status ?? ('pending' as SeoStageStatus),
        error: saved?.error ?? null,
      };
    }),
  );

  const counters = $derived(snapshot.counters);
  const actual = $derived(snapshotActualEstimate(snapshot));
  const generated = $derived(queriesGenerated(snapshot));
  const queryCount = $derived(actualQueryCount(snapshot));
  const failedStages = $derived(stages.filter((stage) => stage.error !== null));
  const terminal = $derived(snapshot.status !== 'running');
</script>

<section
  class="mt-2.5 rounded-xl border border-line bg-white px-4 py-3.5 shadow-sm"
  aria-labelledby="seo-run-title"
>
  <div class="flex flex-wrap items-start justify-between gap-2">
    <div>
      <h2 id="seo-run-title" class="text-base font-bold tracking-tight">Прогон SEO-анализа</h2>
      <p class="mt-1 text-[13px] text-muted">Анализ {snapshot.id}</p>
    </div>
    <span
      class="rounded-full border border-line bg-canvas px-4 py-1.5 text-[13px] font-semibold text-ink"
      data-analysis-status
      aria-live="polite"
    >
      {analysisStatusLabel(snapshot.status)}
    </span>
  </div>

  {#if agentRun}
    <SeoAgentPanel {snapshot} />
  {:else}
    <ol class="mt-3 space-y-1.5" aria-label="Этапы анализа">
      {#each stages as stage (stage.number)}
        <li class="rounded-xl border border-line bg-canvas/40 px-3 py-2" data-stage={stage.number}>
          <div class="flex flex-wrap items-center justify-between gap-2">
            <span class="text-[13px] font-semibold text-ink">{stage.number}. {stage.name}</span>
            <span class={`text-[13px] font-medium ${stageStatusClass(stage.status)}`}
              >{stageStatusLabel(stage.status)}</span
            >
          </div>
          {#if stage.error}
            <p class="mt-2 text-[11px] leading-4 text-rose-700">{stage.error}</p>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}

  <div
    class="mt-2.5 rounded-xl border border-line bg-canvas/40 px-3 py-2 text-[13px] leading-5 text-ink"
    aria-label="Счётчики строк"
  >
    <p class="font-semibold">Готовые строки</p>
    <p class="mt-1 text-muted">
      Запросы: {counters.queries} · Яндекс: {counters.search_rows} (ошибок {counters.search_errors})
      · модели: {counters.model_rows} (ошибок {counters.model_errors})
    </p>
  </div>

  {#if generated}
    <p class="mt-3 text-[13px] leading-5 text-ink" aria-label="Фактическая оценка вызовов">
      После генерации: {queryCount} запросов, то есть {actual.searchActual} поисковых вызовов (3 ключевых
      + {queryCount}) и не больше {actual.modelActual} модельных за прогон.
    </p>
  {/if}

  {#each failedStages as stage (stage.number)}
    <p
      role="alert"
      class="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-[13px] text-amber-900"
    >
      {stage.name}: {stage.error}
    </p>
  {/each}

  <SeoTraceFeed
    steps={trace}
    nextCursor={traceCursor}
    loading={traceLoading}
    error={traceError}
    onMore={onTraceMore}
  />

  {#if terminal}
    <p class="mt-3 border-t border-line pt-6 text-[13px] leading-5 text-muted">
      {#if snapshot.status === 'completed'}
        Анализ завершён, результат сохранён. Отчёт открыт ниже, а все прогоны лежат в SEO-истории.
      {:else if snapshot.status === 'cancelled'}
        Анализ отменён. Полученные строки сохранены, продолжить прогон нельзя.
      {:else if snapshot.status === 'interrupted'}
        Прогон прерван перезапуском приложения. Сохранённые строки доступны, незавершённые строки
        продолжать нельзя.
      {:else}
        Прогон остановлен из-за ошибки этапа. Платные проверки не были продолжены.
      {/if}
    </p>
  {:else}
    <div class="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-6">
      <p class="max-w-xl text-[11px] leading-4 text-muted">
        Состояние обновляется раз в 30 секунд. Прогон продолжится, даже если закрыть страницу.
      </p>
      <button
        type="button"
        onclick={onCancel}
        disabled={cancelling}
        class="inline-flex min-h-8 items-center rounded-xl border border-line bg-white px-5 py-1.5 text-[13px] font-semibold text-rose-700 hover:border-rose-300 disabled:opacity-50"
      >
        {cancelling ? 'Отменяем…' : 'Отменить анализ'}
      </button>
    </div>
  {/if}
</section>
