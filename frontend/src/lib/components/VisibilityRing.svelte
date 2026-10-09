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
  const colors = ['#76b719', '#ffc34d', '#ff6669', '#aeb8c3'];
  let parts = $derived([
    sentiment.positive,
    sentiment.neutral,
    sentiment.negative,
    sentiment.unknown,
  ]);
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

<div
  class="relative mx-auto aspect-square w-44 shrink-0 sm:w-48"
  role="img"
  aria-label={`Видимость в ИИ: ${visibility == null ? 'нет данных' : Math.round(visibility * 100) + ' процентов'}`}
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
    <strong class="text-3xl tracking-tight text-slate-600"
      >{visibility == null ? '—' : Math.round(visibility * 100) + '%'}</strong
    >
    {#if delta != null}<span
        class="mt-1 text-sm font-semibold"
        class:text-red-500={delta < 0}
        class:text-accent={delta >= 0}>{delta > 0 ? '+' : ''}{delta} п.п.</span
      >{/if}
  </div>
</div>
