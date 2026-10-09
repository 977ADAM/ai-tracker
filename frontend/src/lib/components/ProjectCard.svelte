<script lang="ts">
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
</script>

<article
  class="rounded-2xl border border-slate-100 bg-white p-5 shadow-sm transition-shadow hover:shadow-md"
  data-project-card
>
  <div class="flex items-start justify-between gap-3">
    <a
      href={`/projects/${project.id}`}
      class="min-w-0 text-xl font-semibold tracking-tight text-slate-700 hover:text-accent"
      title={project.name}><h2 class="truncate">{project.name}</h2></a
    >
    <div class="flex shrink-0 gap-1">
      <button
        class="grid size-8 place-items-center rounded-lg text-muted hover:bg-canvas disabled:opacity-40"
        aria-label="Запустить замер"
        title="Запустить замер"
        disabled={busy || !!project.active_measurement}
        onclick={onStart}>↻</button
      >
      <button
        class="grid size-8 place-items-center rounded-lg text-red-400 hover:bg-red-50 disabled:opacity-40"
        aria-label={`Удалить проект ${project.name}`}
        disabled={busy || !!project.active_measurement}
        onclick={onDelete}>×</button
      >
    </div>
  </div>
  <div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
    <span>Бренд: <strong>«{project.brand}»</strong></span><span>в</span
    >{#each project.connections as c (c)}<span
        class="rounded-full bg-slate-100 px-2 py-1"
        title={c.name}>{c.name}</span
      >{/each}
  </div>
  <div class="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
    <a
      href={project.site_url}
      target="_blank"
      rel="noopener noreferrer"
      class="max-w-[55%] truncate text-slate-400">{project.site_url.replace(/^https?:\/\//, '')}</a
    >
    {#if latest}<time
        datetime={latest.finished_at ?? latest.created_at}
        class="rounded-md bg-accent-soft px-2 py-1 font-medium text-muted"
        >{(latest.finished_at ?? latest.created_at).slice(0, 10)}</time
      >{:else}<span class="text-slate-400">Нет замеров</span>{/if}
  </div>
  <div class="mt-4 border-t border-slate-100 pt-4">
    <p class="mb-3 text-sm text-slate-500">Видимость в ИИ</p>
    <div class="flex flex-wrap items-center justify-between gap-4">
      <VisibilityRing
        successful={latest?.aggregates.successful ?? 0}
        visibility={latest?.aggregates.visibility ?? null}
        sentiment={counts}
        delta={latest?.comparison.visibility_delta}
      />
      <div class="min-w-40 flex-1 space-y-2 text-sm">
        <div class="rounded-lg bg-slate-50 px-3 py-2">
          <p class="text-xs text-slate-500">Всего упоминаний</p>
          <div class="mt-1 flex justify-between font-semibold text-slate-700">
            <span
              >{latest
                ? `${latest.aggregates.mentioned} из ${latest.aggregates.successful}`
                : '—'}</span
            >{#if latest?.comparison.mentioned_delta != null}<span class="text-xs text-slate-500"
                >{latest.comparison.mentioned_delta > 0 ? '+' : ''}{latest.comparison
                  .mentioned_delta}</span
              >{/if}
          </div>
        </div>
        {#each rows as row (row)}<div class="relative rounded-lg bg-slate-50 px-3 py-2">
            <span class="absolute inset-y-2 left-0 w-0.5 rounded" style:background={row.color}
            ></span>
            <p class="text-xs text-slate-500">{row.label}</p>
            <div class="mt-0.5 flex justify-between text-slate-700">
              <span>{latest ? counts[row.key] : '—'}</span
              >{#if latest?.comparison.sentiment_delta}<span class="text-xs text-slate-500"
                  >{latest.comparison.sentiment_delta[row.key] > 0 ? '+' : ''}{latest.comparison
                    .sentiment_delta[row.key]}</span
                >{/if}
            </div>
          </div>{/each}
      </div>
    </div>
  </div>
  {#if counts.unknown}<p class="mt-3 text-xs text-slate-500">
      Тональность не определена: {counts.unknown}
    </p>{/if}
  {#if latest}<p class="mt-3 text-xs text-slate-400">
      Получено {latest.aggregates.successful} из {latest.aggregates.planned} ответов
    </p>
    {#if latest.comparison.reason}<p class="mt-1 text-xs text-slate-400">
        {latest.comparison.reason}
      </p>{/if}{/if}
  {#if project.active_measurement}<div
      class="mt-4 rounded-lg bg-accent-soft px-3 py-2 text-xs font-medium text-accent"
      role="status"
    >
      Замер выполняется · {project.active_measurement.progress.model_done} из {project
        .active_measurement.progress.model_total}
    </div>{/if}
</article>
