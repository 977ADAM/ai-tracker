<script lang="ts">
  import { SEO_AGENT_LABELS, SEO_AGENT_STATUS_LABELS } from '$lib/seo-agents';
  import type { SeoAgentStatus, SeoAnalysisSnapshot } from '$lib/types';

  let { snapshot }: { snapshot: SeoAnalysisSnapshot } = $props();

  // The panel always shows all six agents: one the backend did not save yet is
  // rendered as pending instead of disappearing from the run screen.

  /** The metered resources of the run, each shown as «used / limit». */
  const BUDGET_ITEMS: readonly {
    key: 'pages' | 'searches' | 'model_answers' | 'tool_calls' | 'handoffs';
    label: string;
  }[] = [
    { key: 'pages', label: 'Страницы' },
    { key: 'searches', label: 'Поисковые запросы' },
    { key: 'model_answers', label: 'Ответы моделей' },
    { key: 'tool_calls', label: 'Вызовы инструментов' },
    { key: 'handoffs', label: 'Передачи управления' },
  ];

  const th = 'px-2.5 py-1.5 text-left text-xs font-semibold text-muted';

  function statusClass(status: SeoAgentStatus): string {
    if (status === 'running') return 'text-accent';
    if (status === 'waiting') return 'text-amber-700';
    if (status === 'done') return 'text-emerald-700';
    if (status === 'error') return 'text-rose-700';
    return 'text-muted';
  }

  /** The saved row of one agent, or a pending placeholder for a missing one. */
  function agentRow(id: string, label: string) {
    const saved = snapshot.agents?.find((item) => item.agent === id);
    return {
      id,
      label,
      status: saved?.status ?? ('pending' as SeoAgentStatus),
      error: saved?.error ?? null,
    };
  }

  /** The model turns one agent spent, from the per-agent step counters. */
  function agentSteps(id: string): number {
    return snapshot.budget?.agent_steps?.[id] ?? 0;
  }
</script>

<div class="mt-3" aria-labelledby="seo-agents-title" data-agent-panel>
  <h3 id="seo-agents-title" class="text-[13px] font-bold tracking-tight">Агенты прогона</h3>
  <p class="mt-1 text-[13px] leading-5 text-muted">
    Супервизор передаёт работу специалистам; каждый шаг агента попадает в трассу ниже.
  </p>

  <ol class="mt-2.5 space-y-1.5" aria-label="Агенты прогона">
    {#each SEO_AGENT_LABELS as entry (entry.id)}
      {@const row = agentRow(entry.id, entry.label)}
      <li class="rounded-lg border border-line bg-canvas/40 px-3 py-2" data-agent={row.id}>
        <div class="flex flex-wrap items-center justify-between gap-2">
          <span class="text-[13px] font-semibold text-ink">{row.label}</span>
          <span
            class={`text-[13px] font-medium ${statusClass(row.status)}`}
            data-agent-status={row.id}
            data-agent-state={row.status}
          >
            {SEO_AGENT_STATUS_LABELS[row.status]}
          </span>
        </div>
        <p class="mt-1 text-[11px] leading-4 text-muted" data-agent-steps>
          Шагов: {agentSteps(row.id)}
        </p>
        {#if row.error}
          <p class="mt-2 text-[11px] leading-4 text-rose-700" data-agent-error>{row.error}</p>
        {/if}
      </li>
    {/each}
  </ol>

  <div
    class="mt-2.5 rounded-lg border border-line bg-canvas/40 px-3 py-2"
    aria-label="Израсходовано"
    data-budget
  >
    <p class="text-[13px] font-semibold text-ink">Израсходовано</p>
    <table class="mt-2 w-full border-collapse text-[13px]">
      <caption class="sr-only">Израсходованные лимиты прогона</caption>
      <tbody class="divide-y divide-line">
        {#each BUDGET_ITEMS as item (item.key)}
          {@const spent = snapshot.budget?.[item.key]}
          <tr data-budget-item={item.key}>
            <th scope="row" class={th}>{item.label}</th>
            <td class="px-2.5 py-1.5 text-right font-medium text-ink" data-budget-used={item.key}>
              {spent?.used ?? 0} / {spent?.limit ?? 0}
            </td>
          </tr>
        {/each}
        <tr data-budget-item="seed_searches">
          <th scope="row" class={th}>Ключевых запросов</th>
          <td
            class="px-2.5 py-1.5 text-right font-medium text-ink"
            data-budget-used="seed_searches"
          >
            {snapshot.budget?.seed_searches ?? 0}
          </td>
        </tr>
        <tr data-budget-item="steps">
          <th scope="row" class={th}>Шагов агентов</th>
          <td class="px-2.5 py-1.5 text-right font-medium text-ink" data-budget-used="steps">
            {snapshot.budget?.steps ?? 0}
          </td>
        </tr>
      </tbody>
    </table>
    {#if snapshot.budget_exhausted}
      <p
        role="status"
        class="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-[13px] text-amber-900"
        data-budget-exhausted
      >
        Прогон остановлен по лимиту: новые платные вызовы не выполняются.
      </p>
    {/if}
  </div>
</div>
