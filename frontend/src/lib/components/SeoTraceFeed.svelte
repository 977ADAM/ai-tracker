<script lang="ts">
  import { seoAgentLabel } from '$lib/seo-agents';
  import type { SeoTraceStep } from '$lib/types';

  let {
    steps = [],
    nextCursor = null,
    loading = false,
    error = '',
    onMore = () => {}
  }: {
    steps?: SeoTraceStep[];
    nextCursor?: string | null;
    loading?: boolean;
    error?: string;
    onMore?: () => void;
  } = $props();

  const KIND_LABELS: Record<SeoTraceStep['kind'], string> = {
    model: 'Модель',
    tool: 'Инструмент',
    handoff: 'Передача управления',
    system: 'Система'
  };

  const STATUS_LABELS: Record<SeoTraceStep['status'], string> = {
    pending: 'Ожидает',
    running: 'Выполняется',
    done: 'Готово',
    error: 'Ошибка',
    rejected: 'Отклонён',
    skipped: 'Пропущен'
  };

  /** Compact safe arguments; the backend already removed secrets and bodies. */
  const ARGUMENT_LIMIT = 160;

  // The trace grows with every agent step, so it starts folded: the header shows
  // how many steps wait behind the toggle, and a live run stays readable.
  let open = $state(false);

  /** The Russian plural of «шаг» for a step count: 1 шаг, 2 шага, 91 шаг, 11 шагов. */
  function stepWord(count: number): string {
    const tail = count % 100;
    if (tail >= 11 && tail <= 14) return 'шагов';
    const last = count % 10;
    if (last === 1) return 'шаг';
    if (last >= 2 && last <= 4) return 'шага';
    return 'шагов';
  }

  function statusClass(status: SeoTraceStep['status']): string {
    if (status === 'running') return 'text-accent';
    if (status === 'done') return 'text-emerald-700';
    if (status === 'error' || status === 'rejected') return 'text-rose-700';
    return 'text-muted';
  }

  function shortArguments(value: Record<string, unknown> | undefined): string {
    if (!value || Object.keys(value).length === 0) return '—';
    let text: string;
    try { text = JSON.stringify(value); }
    catch { return '—'; }
    if (!text || text === '{}') return '—';
    return text.length > ARGUMENT_LIMIT ? `${text.slice(0, ARGUMENT_LIMIT - 1)}…` : text;
  }
</script>

<div class="mt-6 rounded-2xl border border-line bg-canvas/40 px-4 py-4" aria-labelledby="seo-trace-title" data-trace-feed>
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h3 id="seo-trace-title" class="text-lg font-bold tracking-tight">Трасса агентов</h3>
      {#if steps.length === 0}
        <p class="text-sm text-muted" data-trace-summary>
          {loading ? 'Загружаем трассу…' : 'Шагов пока нет.'}
        </p>
      {:else}
        <p class="text-sm font-medium text-muted" data-trace-summary>
          {steps.length} {stepWord(steps.length)}
        </p>
      {/if}
    </div>
    {#if steps.length > 0}
      <button
        type="button"
        onclick={() => (open = !open)}
        aria-expanded={open}
        aria-controls="seo-trace-body"
        class="inline-flex min-h-11 shrink-0 items-center gap-2 rounded-xl border border-line bg-white px-4 py-2 text-sm font-semibold text-ink hover:border-accent"
        data-trace-toggle
      >
        <span aria-hidden="true" class={`inline-block transition-transform ${open ? 'rotate-90' : ''}`}>▸</span>
        {open ? 'Скрыть трассу' : 'Показать трассу'}
      </button>
    {/if}
  </div>

  {#if steps.length > 0}
    <p class="mt-1 text-sm leading-6 text-muted">
      По порядку трассы: агент, инструмент, безопасные аргументы, краткий результат и статус.
    </p>
  {/if}

  {#if error}
    <p role="alert" class="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" data-trace-error>
      {error}
    </p>
  {/if}

  {#if steps.length === 0}
    <p class="mt-4 text-sm text-muted" data-trace-empty>
      {loading ? 'Загружаем трассу…' : 'Шаги трассы пока не записаны.'}
    </p>
  {:else if open}
    <div id="seo-trace-body" data-trace-body>
      <ol class="mt-4 space-y-3" aria-label="Шаги трассы">
        {#each steps as step (step.step_index)}
          <li class="rounded-xl border border-line bg-white px-4 py-3" data-trace-step={step.step_index} data-trace-status={step.status}>
            <div class="flex flex-wrap items-center justify-between gap-2">
              <span class="text-sm font-semibold text-ink">
                #{step.step_index} · {seoAgentLabel(step.agent)} · {KIND_LABELS[step.kind]}
              </span>
              <span class={`text-sm font-medium ${statusClass(step.status)}`}>{STATUS_LABELS[step.status]}</span>
            </div>
            <p class="mt-2 text-xs leading-5 text-muted">
              <span class="font-semibold text-ink">Инструмент:</span>
              <code class="break-all" data-trace-name>{step.name}</code>
            </p>
            <p class="mt-1 text-xs leading-5 text-muted">
              <span class="font-semibold text-ink">Аргументы:</span>
              <code class="break-all" data-trace-arguments>{shortArguments(step.arguments)}</code>
            </p>
            <p class="mt-1 text-xs leading-5 text-muted">
              <span class="font-semibold text-ink">Результат:</span>
              <span data-trace-result>{step.result_summary || '—'}</span>
            </p>
            {#if step.error}
              <p class="mt-1 text-xs leading-5 text-rose-700" data-trace-step-error>{step.error}</p>
            {/if}
          </li>
        {/each}
      </ol>

      {#if nextCursor}
        <div class="mt-4 flex justify-start">
          <button
            type="button"
            onclick={onMore}
            disabled={loading}
            class="inline-flex min-h-11 items-center rounded-xl border border-line bg-white px-5 py-2.5 text-sm font-semibold text-ink hover:border-accent disabled:opacity-50"
          >
            {loading ? 'Загружаем…' : 'Показать ещё'}
          </button>
        </div>
      {/if}
    </div>
  {/if}
</div>
