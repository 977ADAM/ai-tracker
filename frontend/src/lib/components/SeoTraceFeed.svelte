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
  <h3 id="seo-trace-title" class="text-lg font-bold tracking-tight">Трасса агентов</h3>
  <p class="mt-1 text-sm leading-6 text-muted">
    Шаги идут по порядку трассы: агент, инструмент, безопасные аргументы, краткий результат и статус.
  </p>

  {#if error}
    <p role="alert" class="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" data-trace-error>
      {error}
    </p>
  {/if}

  {#if steps.length === 0}
    <p class="mt-4 text-sm text-muted" data-trace-empty>
      {loading ? 'Загружаем трассу…' : 'Шаги трассы пока не записаны.'}
    </p>
  {:else}
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
  {/if}

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
