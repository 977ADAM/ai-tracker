<script lang="ts">
  import { base } from '$app/paths';
  import { onMount } from 'svelte';
  import { providerIcon } from '$lib/provider-icon';
  import { measurementDate, measurementFreshness } from '$lib/measurement-date';
  import type { ProjectSummary } from '$lib/project-types';
  import VisibilityRing from './VisibilityRing.svelte';
  let {
    project,
    busy = false,
    onStart = () => {},
    onDelete = () => {},
  }: {
    project: ProjectSummary;
    busy?: boolean;
    onStart?: () => void;
    onDelete?: () => void;
  } = $props();
  let latest = $derived(project.latest_measurement);
  let counts = $derived(
    latest?.aggregates.sentiment ?? { positive: 0, neutral: 0, negative: 0, unknown: 0 },
  );
  const rows = [
    { key: 'positive', label: 'Положительных', color: '#76b719' },
    { key: 'neutral', label: 'Нейтральных', color: '#ffc34d' },
    { key: 'negative', label: 'Отрицательных', color: '#ff6669' },
  ] as const;
  function deltaColor(value: number, negativeMetric = false) {
    if (value === 0) return 'text-slate-500';
    return (negativeMetric ? value < 0 : value > 0) ? 'text-lime-700' : 'text-red-600';
  }
  let hasComparison = $derived(
    latest != null &&
      (latest.comparison.visibility_delta != null ||
        latest.comparison.mentioned_delta != null ||
        latest.comparison.sentiment_delta != null),
  );
  let now = $state<Date | null>(null);
  onMount(() => {
    now = new Date();
    const timer = setInterval(() => (now = new Date()), 60000);
    return () => clearInterval(timer);
  });
</script>

<article
  class="project-card flex flex-col rounded-2xl border border-slate-100 bg-white shadow-sm transition-shadow hover:shadow-md"
  data-project-card
>
  <header>
    <div class="flex items-center justify-between gap-2">
      <a
        href={`/projects/${project.id}`}
        class="min-w-0 flex-1 text-[22px] font-semibold tracking-tight text-slate-700 hover:text-accent"
        title={project.name}><h2 class="truncate">{project.name}</h2></a
      >
      <div class="flex shrink-0 items-center gap-1">
        {#if latest}
          <button
            class="grid size-8 place-items-center rounded-lg text-slate-500 hover:bg-slate-100 disabled:opacity-40"
            aria-label="Запустить замер"
            title="Запустить новый замер"
            disabled={busy || !!project.active_measurement}
            onclick={onStart}
          >
            <svg
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
              ><path
                d="M20 7v-4m0 4h-4M4 17v4m0-4h4M20 7a8 8 0 0 0-13-2M4 17a8 8 0 0 0 13 2"
              /><path d="M4.2 9a8 8 0 0 1 2.8-4M19.8 15a8 8 0 0 1-2.8 4" /></svg
            >
          </button>
        {/if}
        <button
          class="grid size-8 place-items-center rounded-lg text-red-400 hover:bg-red-50 disabled:opacity-40"
          aria-label={`Удалить проект ${project.name}`}
          title="Удалить проект"
          disabled={busy || !!project.active_measurement}
          onclick={onDelete}
        >
          <svg
            width="21"
            height="21"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.7"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
            ><path
              d="M3 6h18M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M5 6l1 14a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1l1-14M10 10v7M14 10v7"
            /></svg
          >
        </button>
      </div>
    </div>
    <p class="mt-1 truncate text-sm text-slate-500" title={project.brand}>
      Бренд: <strong class="font-semibold">«{project.brand}»</strong>
    </p>
    <div class="mt-3 flex min-h-7 items-center justify-between gap-2">
      <div class="flex min-w-0 items-center gap-1" aria-label="Подключённые модели">
        {#each project.connections as c (c.connection_id)}<span
            class="grid size-7 shrink-0 place-items-center rounded-full bg-white text-[11px] font-bold text-blue-600"
            title={c.name}
            aria-label={c.name}
          >
            {#if providerIcon(c.name)}
              <img
                src={`${base}/providers/${providerIcon(c.name)}.svg`}
                width="24"
                height="24"
                alt=""
              />
            {:else}{c.name.split(' · ')[0].slice(0, 2).toUpperCase()}{/if}
          </span>{/each}
        {#if !project.connections.length}<span class="text-xs text-slate-500"
            >Модели не выбраны</span
          >{/if}
      </div>
      {#if latest}<time
          datetime={latest.finished_at ?? latest.created_at}
          title={`Последний завершённый замер: ${measurementDate(latest.finished_at ?? latest.created_at)} · московское время`}
          class="shrink-0 rounded-lg bg-secondary-soft px-2 py-1 text-[11px] font-semibold text-teal-700"
          >{now
            ? measurementFreshness(latest.finished_at ?? latest.created_at, now)
            : measurementDate(latest.finished_at ?? latest.created_at)}</time
        >{:else}<span class="shrink-0 text-xs text-slate-500">Нет замеров</span>{/if}
    </div>
    <a
      href={project.site_url}
      target="_blank"
      rel="noopener noreferrer"
      class="mt-2 block truncate text-xs text-slate-600 hover:text-accent"
      >{project.site_url.replace(/^https?:\/\//, '').replace(/\/$/, '')}</a
    >
  </header>
  {#if latest}
    <div class="card-metrics mt-4 border-t border-slate-200 pt-4">
      <div class="flex min-w-0 flex-col">
        <p class="text-sm font-medium text-slate-500">Видимость в ИИ</p>
        <div class="flex flex-1 items-center">
          <VisibilityRing
            successful={latest?.aggregates.successful ?? 0}
            visibility={latest?.aggregates.visibility ?? null}
            sentiment={counts}
            delta={latest?.comparison.visibility_delta}
          />
        </div>
      </div>
      <div class="min-w-0 space-y-1.5">
        <div class="metric-row">
          <span class="metric-bar" style:background="#737e88"></span>
          <p class="metric-label">Всего упоминаний</p>
          <div class="flex items-baseline justify-between gap-1">
            <span class="metric-value font-semibold"
              >{#if latest}{latest.aggregates.mentioned}<span class="text-sm font-normal"
                  >{` из ${latest.aggregates.successful}`}</span
                >{:else}—{/if}</span
            >
            {#if latest?.comparison.mentioned_delta != null}<span
                title="Изменение числа упоминаний к предыдущему замеру"
                class={`text-xs font-semibold ${deltaColor(latest.comparison.mentioned_delta)}`}
                >{latest.comparison.mentioned_delta === 0
                  ? '—'
                  : `${latest.comparison.mentioned_delta > 0 ? '+' : ''}${latest.comparison.mentioned_delta}`}</span
              >{/if}
          </div>
        </div>
        {#each rows as row (row.key)}<div class="metric-row">
            <span class="metric-bar" style:background={row.color}></span>
            <p class="metric-label">{row.label}</p>
            <div class="flex items-baseline justify-between gap-1">
              <span class="metric-value">{latest ? counts[row.key] : '—'}</span>
              {#if latest?.comparison.sentiment_delta}<span
                  title="Изменение числа ответов к предыдущему замеру"
                  class={`text-xs font-semibold ${deltaColor(latest.comparison.sentiment_delta[row.key], row.key === 'negative')}`}
                  >{latest.comparison.sentiment_delta[row.key] === 0
                    ? '—'
                    : `${latest.comparison.sentiment_delta[row.key] > 0 ? '+' : ''}${latest.comparison.sentiment_delta[row.key]}`}</span
                >{/if}
            </div>
          </div>{/each}
      </div>
    </div>
  {:else}
    <div
      class="mt-4 flex min-h-[248px] flex-1 flex-col items-center justify-center border-t border-slate-200 px-2 pt-5 pb-2 text-center"
    >
      <div
        class="mb-4 grid size-12 place-items-center rounded-2xl bg-accent-soft text-accent"
        aria-hidden="true"
      >
        <svg
          width="26"
          height="26"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          stroke-linejoin="round"><path d="M5 19V13m7 6V5m7 14V9" /></svg
        >
      </div>
      <h3 class="text-base font-semibold text-slate-700">
        {project.active_measurement ? 'Первый замер выполняется' : 'Запустите первый замер'}
      </h3>
      <p class="mt-2 max-w-[250px] text-sm leading-5 text-slate-500">
        {project.active_measurement
          ? 'Результаты появятся здесь после завершения проверки.'
          : 'Узнайте, как часто модели упоминают ваш бренд и в какой тональности.'}
      </p>
      {#if project.active_measurement}
        <p
          role="status"
          class="mt-4 rounded-lg bg-secondary-soft px-3 py-2 text-xs font-medium text-teal-700"
        >
          Получено {project.active_measurement.progress.model_done} из {project.active_measurement
            .progress.model_total} ответов
        </p>
      {:else}
        <button
          type="button"
          onclick={onStart}
          disabled={busy}
          class="mt-5 rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-accent-dark focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-wait disabled:opacity-50"
        >
          {busy ? 'Запускаем…' : 'Запустить замер'}
        </button>
      {/if}
    </div>
  {/if}
  {#if latest}
    <footer class="mt-4 min-h-8 space-y-1 text-xs leading-4 text-slate-600">
      {#if hasComparison}<p class="font-medium">Изменения — к предыдущему замеру</p>{/if}
      {#if counts.unknown}<p class="flex items-center gap-1.5">
          <span class="size-2 rounded-full bg-slate-400" aria-hidden="true"></span>Тональность не
          определена: {counts.unknown}
        </p>{/if}
      {#if latest}<p>
          Получено {latest.aggregates.successful} из {latest.aggregates.planned} ответов
        </p>
        {#if latest.comparison.reason}<p>{latest.comparison.reason}</p>{/if}{/if}
      {#if project.active_measurement}<p
          class="rounded-lg bg-accent-soft px-2 py-1 font-medium text-accent"
          role="status"
        >
          Замер выполняется · {project.active_measurement.progress.model_done} из {project
            .active_measurement.progress.model_total}
        </p>{/if}
    </footer>
  {/if}
</article>

<style>
  .project-card {
    padding: 18px;
    min-width: 0;
  }
  .card-metrics {
    display: grid;
    grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
    gap: 12px;
  }
  .metric-row {
    position: relative;
    border-radius: 10px;
    background: #f7f8fa;
    padding: 7px 10px 7px 13px;
  }
  .metric-bar {
    position: absolute;
    left: 7px;
    top: 8px;
    bottom: 8px;
    width: 3px;
    border-radius: 3px;
  }
  .metric-label {
    font-size: 12px;
    line-height: 16px;
    color: #566273;
    white-space: nowrap;
  }
  .metric-value {
    font-size: 21px;
    line-height: 27px;
    color: #36414f;
  }
</style>
