<script lang="ts">
  import type { SearchRow, SearchRowStatus, SearchSnapshot } from '$lib/types';

  let {
    snapshot = null,
    error = ''
  }: { snapshot?: SearchSnapshot | null; error?: string } = $props();

  const STATUS_LABELS: Record<SearchRowStatus, string> = {
    submitting: 'Отправляем запрос в Яндекс',
    waiting: 'Яндекс считает',
    found: 'Сайт в первой десятке',
    absent: 'Сайт не найден в первой десятке',
    error: 'Ошибка запроса'
  };

  function badgeClasses(status: SearchRowStatus): string {
    if (status === 'found') return 'bg-accent-soft text-accent-dark';
    if (status === 'error') return 'bg-rose-50 text-rose-700';
    if (status === 'absent') return 'bg-slate-100 text-slate-600';
    return 'bg-amber-50 text-amber-700';
  }

  function position(row: SearchRow): string {
    return row.status === 'found' && row.position !== null ? String(row.position) : '—';
  }
</script>

<section class="mt-10" aria-labelledby="search-title">
  <div class="mb-5 flex flex-wrap items-end justify-between gap-3">
    <div>
      <p class="text-xs font-bold tracking-[0.16em] text-muted uppercase">Поиск в Яндексе</p>
      <h2 id="search-title" class="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">Сайт в первой десятке</h2>
    </div>
    {#if snapshot}
      <p class="text-xs text-muted">Сайт: {snapshot.domain} · Готово {snapshot.completed} из {snapshot.total}</p>
    {/if}
  </div>

  {#if error}
    <p role="alert" class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</p>
  {:else if snapshot}
    <div class="grid gap-4 sm:grid-cols-3">
      <article class="rounded-2xl border border-line bg-white p-5 shadow-sm">
        <p class="text-sm font-semibold text-muted">Найдено в первой десятке</p>
        <p class="mt-4 text-4xl font-bold tracking-tight text-accent">{snapshot.summary.found}</p>
        <p class="mt-2 text-xs text-muted">Из {snapshot.total} пар «вопрос × регион»</p>
      </article>
      <article class="rounded-2xl border border-line bg-white p-5 shadow-sm">
        <p class="text-sm font-semibold text-muted">Получен вердикт</p>
        <p class="mt-4 text-4xl font-bold tracking-tight text-ink">{snapshot.summary.successful}</p>
        <p class="mt-2 text-xs text-muted">Найден или отсутствует в первой десятке</p>
      </article>
      <article class="rounded-2xl border border-line bg-white p-5 shadow-sm">
        <p class="text-sm font-semibold text-muted">Ошибки запросов</p>
        <p class="mt-4 text-4xl font-bold tracking-tight text-ink">{snapshot.summary.failed}</p>
        <p class="mt-2 text-xs text-muted">Ошибка не считается отсутствием сайта</p>
      </article>
    </div>

    <div class="mt-6 overflow-hidden rounded-3xl border border-line bg-white shadow-sm">
      <div class="overflow-x-auto">
        <table aria-label="Результаты поиска Яндекса" class="w-full min-w-160 border-collapse text-left text-sm">
          <thead class="bg-canvas text-xs font-bold tracking-wide text-muted uppercase">
            <tr>
              <th scope="col" class="px-6 py-3 sm:px-8">Вопрос</th>
              <th scope="col" class="px-6 py-3">Регион</th>
              <th scope="col" class="px-6 py-3">Место</th>
              <th scope="col" class="px-6 py-3">Результат</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-line">
            {#each snapshot.results as row, index (`${row.prompt}-${row.region_id}-${index}`)}
              <tr class="align-top" data-search-row data-status={row.status}>
                <th scope="row" class="max-w-80 px-6 py-4 font-semibold text-ink sm:px-8">{row.prompt}</th>
                <td class="px-6 py-4 text-muted">{row.region_name}</td>
                <td class="px-6 py-4 text-muted">{position(row)}</td>
                <td class="px-6 py-4">
                  <span class={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${badgeClasses(row.status)}`}>{STATUS_LABELS[row.status]}</span>
                  {#if row.status === 'found' && row.url}
                    <a class="mt-2 block max-w-96 truncate text-xs font-semibold text-accent hover:underline" href={row.url} target="_blank" rel="noopener noreferrer">{row.url}</a>
                  {:else if row.status === 'error' && row.error}
                    <span class="mt-2 block max-w-96 text-xs text-rose-700">{row.error}</span>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      {#if snapshot.status === 'pending'}
        <p class="border-t border-line bg-canvas/60 px-6 py-4 text-xs leading-5 text-muted sm:px-8" aria-live="polite">
          Яндекс ещё считает: отложенный поиск занимает от нескольких минут до нескольких часов, страница обновляет результат сама.
          Если закрыть или перезагрузить страницу, доступ к этой задаче потеряется.
        </p>
      {/if}
    </div>
  {:else}
    <section class="rounded-3xl border border-dashed border-line bg-white px-6 py-14 text-center shadow-sm">
      <div class="mx-auto grid size-12 place-items-center rounded-2xl bg-accent-soft text-2xl text-accent">◎</div>
      <h3 class="mt-5 text-xl font-bold">Поиск в Яндексе не запускался</h3>
      <p class="mx-auto mt-2 max-w-md text-sm leading-6 text-muted">Добавьте регион и укажите сайт — проверим, попадает ли он в первую десятку выдачи.</p>
    </section>
  {/if}
</section>
