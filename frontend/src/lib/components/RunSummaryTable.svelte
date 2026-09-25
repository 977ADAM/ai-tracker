<script lang="ts">
  import type { RunSnapshot } from '$lib/types';

  let { snapshot }: { snapshot: RunSnapshot } = $props();
</script>

<section class="mt-8 overflow-hidden rounded-3xl border border-line bg-white shadow-sm" aria-labelledby="run-table-title">
  <div class="flex flex-wrap items-start justify-between gap-4 px-6 py-6 sm:px-8">
    <div>
      <h2 id="run-table-title" class="text-2xl font-bold tracking-tight">Таблица результатов</h2>
      <p class="mt-2 text-sm leading-6 text-muted">Сводка по каждому запросу, модели и региону поиска.</p>
    </div>
    {#if snapshot.status !== 'pending'}
      <a href={`/api/runs/${encodeURIComponent(snapshot.id)}/export.csv`} class="inline-flex min-h-11 items-center rounded-xl border border-line px-4 py-2 text-sm font-semibold text-ink transition hover:border-accent">Экспорт</a>
    {/if}
  </div>
  <div class="overflow-x-auto px-6 pb-6 sm:px-8">
    <table aria-label="Таблица результатов" class="w-full min-w-225 border-collapse text-left text-sm">
      <thead class="bg-canvas text-xs font-semibold text-ink">
        <tr><th scope="col" class="px-4 py-4">Запрос</th><th scope="col" class="px-4 py-4">Поисковик</th><th scope="col" class="px-4 py-4">Язык</th><th scope="col" class="px-4 py-4">Регион</th><th scope="col" class="px-4 py-4">ИИ-ответ</th><th scope="col" class="px-4 py-4">Сайт найден</th><th scope="col" class="px-4 py-4">Позиция</th><th scope="col" class="px-4 py-4">Бренд найден</th><th scope="col" class="px-4 py-4">Статус</th></tr>
      </thead>
      <tbody class="divide-y divide-line">
        {#each snapshot.summary_rows as row, index (`${row.source}-${index}`)}
          <tr class="align-top" data-status={row.status}>
            <th scope="row" class="px-4 py-4 font-medium text-ink">{row.prompt}</th>
            <td class="px-4 py-4">{row.source}</td><td class="px-4 py-4">{row.language || '—'}</td>
            <td class="px-4 py-4">{row.region}</td><td class="px-4 py-4">{row.ai_answer}</td>
            <td class="px-4 py-4">{row.site_found}</td><td class="px-4 py-4">{row.position}</td>
            <td class="px-4 py-4">{row.brand_found}</td><td class="px-4 py-4">{row.status}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</section>
