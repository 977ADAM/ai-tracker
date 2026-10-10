<script lang="ts">
  import type { SentimentCounts } from '$lib/project-types';
  let {
    successful,
    visibility,
    sentiment,
    delta = null,
  }: {
    successful: number;
    visibility: number | null;
    sentiment: SentimentCounts;
    delta?: number | null;
  } = $props();
  const tooltipId = $props.id();
  let expanded = $state(false);
  const colors = ['#76b719', '#ffc34d', '#ff6669', '#aeb8c3'];
  let parts = $derived([
    sentiment.positive,
    sentiment.neutral,
    sentiment.negative,
    sentiment.unknown,
  ]);
  let withoutMention = $derived(Math.max(0, successful - parts.reduce((sum, n) => sum + n, 0)));
  let segments = $derived.by(() => {
    let offset = 0;
    return parts.map((n, i) => {
      const length = successful ? (n / successful) * 100 : 0;
      const segment = { color: colors[i], length, offset };
      offset += length;
      return segment;
    });
  });
</script>

<div class="group relative mx-auto aspect-square w-full max-w-44 shrink-0">
  <button
    type="button"
    class="relative block size-full rounded-full focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
    aria-label={`Видимость в ИИ: ${visibility == null ? 'нет данных' : Math.round(visibility * 100) + ' процентов'}. Распределение ответов`}
    aria-describedby={tooltipId}
    onclick={() => (expanded = !expanded)}
    onkeydown={(event) => {
      if (event.key === 'Escape') {
        expanded = false;
        event.currentTarget.blur();
      }
    }}
  >
    <svg viewBox="0 0 120 120" class="size-full -rotate-90" aria-hidden="true">
      <circle cx="60" cy="60" r="50" fill="none" stroke="#eff3f7" stroke-width="12" />
      {#each segments as segment (segment)}
        <circle
          cx="60"
          cy="60"
          r="50"
          fill="none"
          stroke={segment.color}
          stroke-width="12"
          pathLength="100"
          stroke-dasharray={`${segment.length} ${100 - segment.length}`}
          stroke-dashoffset={-segment.offset}
        />
      {/each}
    </svg>
    <div class="absolute inset-0 flex flex-col items-center justify-center">
      <strong class="text-[clamp(24px,2.3vw,32px)] tracking-tight text-slate-600"
        >{visibility == null ? '—' : Math.round(visibility * 100) + '%'}</strong
      >
      {#if delta != null}<span
          title="Изменение видимости к предыдущему замеру, в процентных пунктах"
          class="mt-1 text-xs font-semibold"
          class:text-red-600={delta < 0}
          class:text-lime-700={delta > 0}
          class:text-slate-500={delta === 0}>{delta > 0 ? '+' : ''}{delta} п.п.</span
        >{/if}
    </div>
  </button>
  <div
    id={tooltipId}
    role="tooltip"
    class={`ring-tooltip absolute bottom-full left-0 z-20 mb-2 w-60 rounded-xl border border-line bg-white p-3 text-xs leading-5 text-slate-700 shadow-lg ${expanded ? 'block' : 'hidden group-focus-within:block group-hover:block'}`}
  >
    <p class="mb-1 font-semibold">Распределение ответов</p>
    {#if successful > 0}
      <dl class="space-y-1">
        {#each [{ label: 'Положительные', value: sentiment.positive, color: colors[0] }, { label: 'Нейтральные', value: sentiment.neutral, color: colors[1] }, { label: 'Отрицательные', value: sentiment.negative, color: colors[2] }, { label: 'Тональность не определена', value: sentiment.unknown, color: colors[3] }, { label: 'Без упоминания бренда', value: withoutMention, color: '#eff3f7' }] as row (row.label)}
          <div class="flex items-center justify-between gap-3">
            <dt class="flex items-center gap-2">
              <span
                class="size-2 shrink-0 rounded-full border border-slate-300"
                style:background={row.color}
                aria-hidden="true"
              ></span>{row.label}
            </dt>
            <dd class="font-semibold">{row.value}</dd>
          </div>
        {/each}
      </dl>
      <p class="mt-2 border-t border-line pt-2 text-slate-600">Всего получено: {successful}</p>
    {:else}
      <p>Успешных ответов пока нет.</p>
    {/if}
  </div>
</div>
