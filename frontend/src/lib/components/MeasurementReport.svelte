<script lang="ts">
  import type { Measurement, ModelRow, SearchRow } from '$lib/project-types';
  import { percent, sentimentLabels } from '$lib/project-client';
  import { plainText } from '$lib/markdown';
  import MeasurementOverview from './MeasurementOverview.svelte';
  import AnswerDialog from './AnswerDialog.svelte';
  let {
    snapshot,
    view = 'mentions',
    modelRows = [],
    searchRows = [],
    modelCursor = null,
    searchCursor = null,
    loading = false,
    onMore = () => {},
  }: {
    snapshot: Measurement;
    view?: 'mentions' | 'sources';
    modelRows?: ModelRow[];
    searchRows?: SearchRow[];
    modelCursor?: string | null;
    searchCursor?: string | null;
    loading?: boolean;
    onMore?: (kind: 'model' | 'search') => void;
  } = $props();
  let a = $derived(snapshot.aggregates);
  let open = $state<ModelRow | null>(null);
  let visibleRows = $derived(
    view === 'sources' ? modelRows.filter((r) => r.answer_mode === 'deepseek_web') : modelRows,
  );
  const posLabels: Record<string, string> = {
    first: 'Первый абзац',
    early: '2–3 абзацы',
    late: 'Ниже',
    absent: 'Не назван',
    ahead: 'Раньше конкурентов',
  };
  const th = 'px-3 py-3 text-left text-xs font-medium text-muted';
  const td = 'border-t border-line px-3 py-3 text-sm';
</script>

<div class="space-y-6" data-measurement-report>
  {#if view === 'mentions'}
    <MeasurementOverview aggregates={a} comparison={snapshot.comparison} />
    <div class="rounded-xl bg-accent-soft p-4 text-sm">
      <p>
        Бренд упомянут в <strong>{a.mentioned} из {a.successful}</strong> успешных ответов. Получено {a.successful}
        из {a.planned} запланированных.
      </p>
      {#if a.model_errors}<p class="mt-1">
          Ошибок или прерванных ответов: {a.model_errors}.
        </p>{/if}{#if a.sentiment.unknown}<p class="mt-1">
          Тональность не определена для {a.sentiment.unknown} упоминаний.
        </p>{/if}{#if snapshot.comparison.reason}<p class="mt-2 text-xs text-muted">
          {snapshot.comparison.reason}
        </p>{/if}
    </div>
    <section class="overflow-hidden rounded-xl border border-line bg-white">
      <h2 class="px-4 pt-4 font-semibold">Модели и позиция бренда</h2>
      <div class="overflow-x-auto">
        <table class="w-full">
          <thead
            ><tr
              ><th class={th}>Модель</th><th class={th}>Упоминания</th><th class={th}
                >В источниках</th
              >{#each Object.values(posLabels) as label (label)}<th class={th}>{label}</th
                >{/each}</tr
            ></thead
          ><tbody
            >{#each a.models as m (m)}<tr
                ><td class={td}>{m.name}</td><td class={td}
                  >{percent(m.visibility)}
                  <span class="text-xs text-muted">({m.mentioned}/{m.successful})</span></td
                ><td class={td}
                  >{percent(m.citation.share)}{#if m.citation.average_position != null}<span
                      class="block text-xs text-muted"
                      >Порядок: {m.citation.average_position.toFixed(1)}</span
                    >{/if}</td
                >{#each Object.keys(posLabels) as k (k)}<td class={td}
                    >{percent(m.position[k].share)}</td
                  >{/each}</tr
              >{/each}</tbody
          >
        </table>
      </div>
    </section>
    <section class="overflow-hidden rounded-xl border border-line bg-white">
      <h2 class="px-4 pt-4 font-semibold">Запросы</h2>
      <div class="overflow-x-auto">
        <table class="w-full">
          <thead
            ><tr
              ><th class={th}>Запрос</th><th class={th}>Ответы</th><th class={th}>Упоминания</th><th
                class={th}>Видимость</th
              ></tr
            ></thead
          ><tbody
            >{#each a.queries as q (q)}<tr
                ><td class={td}
                  >{q.text}{#if q.group}<span class="mt-1 block text-xs text-muted">{q.group}</span
                    >{/if}</td
                ><td class={td}>{q.successful}</td><td class={td}>{q.mentioned}</td><td class={td}
                  >{percent(q.visibility)}</td
                ></tr
              >{/each}</tbody
          >
        </table>
      </div>
    </section>
    {#if a.groups?.length}<section class="overflow-hidden rounded-xl border border-line bg-white">
        <h2 class="px-4 pt-4 font-semibold">Группы промптов</h2>
        <table class="w-full">
          <thead
            ><tr
              ><th class={th}>Группа</th><th class={th}>Упоминания</th><th class={th}>Видимость</th
              ></tr
            ></thead
          ><tbody
            >{#each a.groups as group (group.name)}<tr
                ><td class={td}>{group.name}</td><td class={td}
                  >{group.mentioned} из {group.successful}</td
                ><td class={td}>{percent(group.visibility)}</td></tr
              >{/each}</tbody
          >
        </table>
      </section>{/if}
    {#if a.competitors.length}<section
        class="overflow-hidden rounded-xl border border-line bg-white"
      >
        <h2 class="px-4 pt-4 font-semibold">Конкуренты</h2>
        <table class="w-full">
          <thead
            ><tr
              ><th class={th}>Бренд</th><th class={th}>Упоминания</th><th class={th}>Видимость</th
              ></tr
            ></thead
          ><tbody
            >{#each a.competitors as c (c)}<tr
                ><td class={td}>{c.brand}</td><td class={td}>{c.mentioned} из {c.successful}</td><td
                  class={td}>{percent(c.visibility)}</td
                ></tr
              >{/each}</tbody
          >
        </table>
      </section>{/if}
  {/if}
  {#if view === 'sources'}<section class="overflow-hidden rounded-xl border border-line bg-white">
      <h2 class="px-4 pt-4 font-semibold">Цитирование сайта моделями</h2>
      <table class="w-full">
        <thead
          ><tr
            ><th class={th}>Модель</th><th class={th}>Ответов с цитатами сайта</th><th class={th}
              >Доля</th
            ><th class={th}>Средний порядок</th></tr
          ></thead
        ><tbody
          >{#each a.models as m (m.connection_id)}<tr
              ><td class={td}>{m.name}</td><td class={td}
                >{m.citation.successes} из {m.citation.denominator}</td
              ><td class={td}>{percent(m.citation.share)}</td><td class={td}
                >{m.citation.average_position?.toFixed(1) ?? '—'}</td
              ></tr
            >{/each}</tbody
        >
      </table>
    </section>
    <section class="overflow-hidden rounded-xl border border-line bg-white">
      <h2 class="px-4 pt-4 font-semibold">Источники</h2>
      {#if a.sources.length}<table class="w-full">
          <thead
            ><tr><th class={th}>Домен</th><th class={th}>Ответов</th><th class={th}>Цитат</th></tr
            ></thead
          ><tbody
            >{#each a.sources as source (source)}<tr
                ><td class={td}>{source.domain}</td><td class={td}>{source.answers}</td><td
                  class={td}>{source.citations}</td
                ></tr
              >{/each}</tbody
          >
        </table>{:else}<p class="p-4 text-sm text-muted">
          Внешних цитируемых источников нет. У моделей без веб-поиска цитирование не применяется.
        </p>{/if}
    </section>
  {/if}
  <section class="overflow-hidden rounded-xl border border-line bg-white">
    <h2 class="px-4 pt-4 font-semibold">
      {view === 'sources' ? 'Ответы с веб-поиском' : 'Ответы моделей'}
    </h2>
    <div class="overflow-x-auto">
      <table class="w-full">
        <thead
          ><tr
            ><th class={th}>Запрос / модель</th><th class={th}>Ответ</th><th class={th}
              >Тональность</th
            ><th class={th}>Источники</th></tr
          ></thead
        ><tbody
          >{#each visibleRows as row (row)}<tr
              ><td class={`${td} min-w-40`}
                ><span>{row.query}</span><span class="mt-1 block text-xs text-muted"
                  >{row.provider_name} · {row.answer_mode === 'deepseek_web'
                    ? 'Веб-поиск'
                    : 'Текст'}</span
                ></td
              ><td class={`${td} max-w-lg min-w-48`}
                >{#if row.answer}<p>
                    {plainText(row.answer).slice(0, 160)}{plainText(row.answer).length > 160
                      ? '…'
                      : ''}
                  </p>
                  <button
                    class="mt-2 text-xs font-medium text-accent underline"
                    onclick={() => (open = row)}>Читать полностью</button
                  >{:else}<span class="text-muted"
                    >{row.error ??
                      (row.status === 'pending'
                        ? 'Ожидает'
                        : row.status === 'sent'
                          ? 'Запрос отправлен'
                          : row.status)}</span
                  >{/if}</td
              ><td class={td}
                >{row.brand_mentioned
                  ? sentimentLabels[row.sentiment?.label ?? 'unknown']
                  : 'Бренд не назван'}</td
              ><td class={td}>{row.answer_mode === 'text' ? '—' : row.citations.length}</td></tr
            >{/each}</tbody
        >
      </table>
    </div>
    {#if modelCursor}<button
        class="m-4 rounded-lg border border-line px-4 py-2 text-sm"
        disabled={loading}
        onclick={() => onMore('model')}>Показать ещё ответы</button
      >{/if}
  </section>
  {#if view === 'mentions' && snapshot.snapshot.project.yandex_enabled}<section
      class="overflow-hidden rounded-xl border border-line bg-white"
    >
      <h2 class="px-4 pt-4 font-semibold">
        Яндекс · регион {snapshot.snapshot.project.yandex_region}
      </h2>
      <table class="w-full">
        <thead
          ><tr
            ><th class={th}>Сайт</th><th class={th}>В первой десятке</th><th class={th}
              >Средняя позиция</th
            ></tr
          ></thead
        ><tbody
          >{#each a.search as site (site)}<tr
              ><td class={td}>{site.brand}</td><td class={td}
                >{site.found} из {site.successful} · {percent(site.visibility)}</td
              ><td class={td}>{site.average_position?.toFixed(1) ?? '—'}</td></tr
            >{/each}</tbody
        >
      </table>
      <div class="border-t border-line p-4 text-sm">
        {#each searchRows as row (row)}<p class="mt-2">
            {row.query}: {row.error ??
              (row.status === 'success' ? `${row.documents.length} результатов` : row.status)}
          </p>{/each}{#if searchCursor}<button
            class="mt-4 rounded-lg border border-line px-4 py-2"
            disabled={loading}
            onclick={() => onMore('search')}>Показать ещё поиски</button
          >{/if}
      </div>
    </section>{/if}
</div>
{#if open}<AnswerDialog row={open} onClose={() => (open = null)} />{/if}
