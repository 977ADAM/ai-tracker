<script lang="ts">
  import type { Aggregates, Comparison } from '$lib/project-types';
  import { percent } from '$lib/project-client';
  let { aggregates: a, comparison }: { aggregates: Aggregates; comparison: Comparison } = $props();
  const categories = [
    { key: 'positive', label: 'Положительная', color: '#76b719' },
    { key: 'neutral', label: 'Нейтральная', color: '#ffc34d' },
    { key: 'negative', label: 'Отрицательная', color: '#ff6669' },
    { key: 'unknown', label: 'Не определена', color: '#64748b' },
  ] as const;
  let distribution = $derived([
    ...categories.map((row) => ({ ...row, value: a.sentiment[row.key] })),
    {
      key: 'absent',
      label: 'Без упоминания бренда',
      color: '#cbd5e1',
      value: Math.max(0, a.successful - a.mentioned),
    },
  ]);
</script>

<div class="space-y-4">
  <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
    <div class="rounded-xl border border-line bg-white p-4">
      <p class="text-xs text-muted">Видимость в ИИ</p>
      <strong class="mt-2 block text-2xl text-ink">{percent(a.visibility)}</strong>
      {#if comparison.visibility_delta != null}
        <p
          class="mt-1 text-xs font-medium"
          class:text-red-600={comparison.visibility_delta < 0}
          class:text-teal-700={comparison.visibility_delta > 0}
          class:text-muted={comparison.visibility_delta === 0}
        >
          {comparison.visibility_delta > 0 ? '+' : ''}{comparison.visibility_delta} п.п.
          <span class="mt-1 block font-normal text-muted">к предыдущему замеру</span>
        </p>
      {/if}
    </div>
    {#each categories as row (row.key)}
      <div class="rounded-xl border border-line bg-white p-4">
        <p class="flex items-center gap-2 text-xs text-muted">
          <span class="size-2 shrink-0 rounded-full" style:background={row.color} aria-hidden="true"
          ></span>{row.label}
        </p>
        <strong class="mt-2 block text-2xl text-ink">{a.sentiment[row.key]}</strong>
        <p class="mt-1 text-xs text-muted">тональность</p>
      </div>
    {/each}
  </div>
  <section
    class="rounded-2xl border border-line bg-white p-4 sm:p-5"
    aria-label="Распределение ответов"
  >
    <h2 class="font-semibold text-ink">Распределение ответов</h2>
    <p class="mt-1 text-xs leading-5 text-muted">
      Доля каждой категории среди всех полученных ответов.
    </p>
    {#if a.successful > 0}
      <dl class="mt-5 space-y-4">
        {#each distribution as row (row.key)}
          <div>
            <div class="mb-1.5 flex items-center justify-between gap-3 text-xs">
              <dt class="text-slate-600">{row.label}</dt>
              <dd class="shrink-0 font-semibold text-ink tabular-nums">
                {row.value}
                <span class="font-normal text-muted">· {percent(row.value / a.successful)}</span>
              </dd>
            </div>
            <div class="h-2.5 overflow-hidden rounded-full bg-canvas" aria-hidden="true">
              <div
                class="h-full rounded-full"
                style:width={`${Math.min(100, (row.value / a.successful) * 100)}%`}
                style:background={row.color}
              ></div>
            </div>
          </div>
        {/each}
      </dl>
    {:else}
      <p class="mt-4 rounded-lg bg-canvas p-4 text-sm text-muted">
        График появится после получения успешных ответов.
      </p>
    {/if}
  </section>
</div>
