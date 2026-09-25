<script lang="ts">
  import { marked } from 'marked';
  import DOMPurify from 'dompurify';
  import type { RunSnapshot } from '$lib/types';
  import RunSummaryTable from './RunSummaryTable.svelte';

  let { snapshot }: { snapshot: RunSnapshot } = $props();

  marked.setOptions({ breaks: true, gfm: true });

  function answerHtml(text: string): string {
    return DOMPurify.sanitize(marked.parse(text, { async: false }) as string);
  }

  function safeLink(value: string | null): string | null {
    if (!value) return null;
    try {
      const url = new URL(value);
      return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
    } catch { return null; }
  }

  function statusLabel(value: string): string {
    if (value === 'pending' || value === 'submitting' || value === 'waiting') return 'Выполняется';
    if (value === 'interrupted') return 'Прервано';
    if (value === 'error') return 'Ошибка';
    if (value === 'found') return 'Сайт найден';
    if (value === 'absent') return 'Не найдено';
    if (value === 'mentioned') return 'Бренд упомянут';
    return 'Нет упоминания';
  }
</script>

<div id="run-results" class="mt-8 scroll-mt-8">
  <div class="flex flex-wrap items-end justify-between gap-3"><h2 class="text-2xl font-bold tracking-tight">Результат прогона</h2><p class="text-sm text-muted">{snapshot.status === 'pending' ? 'Проверка продолжается' : snapshot.status === 'interrupted' ? 'Прогон прерван' : 'Проверка завершена'}</p></div>
  <RunSummaryTable {snapshot} />

  {#if snapshot.models.length}
    <section class="mt-8 space-y-4" aria-labelledby="model-details-title">
      <h3 id="model-details-title" class="text-xl font-bold">Ответы моделей</h3>
      {#each snapshot.models as row (`${row.provider_id}-${row.prompt_index}`)}
        <article class="rounded-2xl border border-line bg-white p-5 shadow-sm">
          <div class="flex flex-wrap items-start justify-between gap-3"><div><p class="text-xs font-semibold text-muted">{row.provider_name}</p><h4 class="mt-1 font-semibold">{row.prompt}</h4></div><span class="text-sm font-medium">{statusLabel(row.status)}</span></div>
          {#if row.error}<p class="mt-4 text-sm text-rose-700">{row.error}</p>
          {:else if row.answer}<div class="prose prose-sm mt-4 max-w-none text-ink/85">{@html answerHtml(row.answer)}</div>
          {:else}<p class="mt-4 text-sm text-muted">{row.status === 'interrupted' ? 'Ответ не был получен до прерывания' : 'Ответ ожидается'}</p>{/if}
        </article>
      {/each}
    </section>
  {/if}

  {#if snapshot.search.length}
    <section class="mt-8 space-y-4" aria-labelledby="search-details-title">
      <h3 id="search-details-title" class="text-xl font-bold">Поиск в Яндексе</h3>
      {#each snapshot.search as row (row.search_index)}
        <article class="rounded-2xl border border-line bg-white p-5 shadow-sm">
          <div class="flex flex-wrap items-start justify-between gap-3"><div><p class="text-xs font-semibold text-muted">{row.region_name}</p><h4 class="mt-1 font-semibold">{row.prompt}</h4></div><span class="text-sm font-medium">{statusLabel(row.status)}</span></div>
          {#if row.status === 'found'}<p class="mt-3 text-sm">Позиция: {row.position ?? '—'}{#if safeLink(row.url)} · <a href={safeLink(row.url) ?? undefined} target="_blank" rel="noopener noreferrer" class="text-accent underline">Открыть найденную страницу</a>{/if}</p>
          {:else if row.error}<p class="mt-3 text-sm text-rose-700">{row.error}</p>
          {:else if row.status === 'interrupted'}<p class="mt-3 text-sm text-muted">Результат не был получен до прерывания.</p>
          {:else if row.status === 'absent'}<p class="mt-3 text-sm text-muted">Сайт не найден в первой десятке.</p>
          {:else}<p class="mt-3 text-sm text-muted">Яндекс ещё считает результат.</p>{/if}
        </article>
      {/each}
    </section>
  {/if}
</div>
