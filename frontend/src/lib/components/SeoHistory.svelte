<script lang="ts">
  import type { SeoAnalysisStatus, SeoHistoryItem } from '$lib/types';

  let {
    items,
    nextCursor,
    onView,
    onDelete,
    onMore,
    loading = false,
    error = ''
  }: {
    items: SeoHistoryItem[];
    nextCursor: string | null;
    onView: (id: string) => void;
    onDelete: (id: string) => void;
    onMore: () => void;
    loading?: boolean;
    error?: string;
  } = $props();

  const STATUS_LABELS: Record<SeoAnalysisStatus, string> = {
    running: 'Выполняется',
    completed: 'Завершён',
    failed: 'Ошибка',
    interrupted: 'Прерван',
    cancelled: 'Отменён'
  };

  const th = 'px-4 py-4 text-xs font-bold tracking-wide text-muted uppercase';
  const td = 'whitespace-nowrap px-4 py-5';

  /** Only a finished analysis may be deleted; an active one is still writing rows. */
  function terminal(status: SeoAnalysisStatus): boolean {
    return status !== 'running';
  }

  function confirmDelete(item: SeoHistoryItem) {
    if (window.confirm('Удалить этот SEO-анализ и его результаты?')) onDelete(item.id);
  }

  function counter(value: number | null | undefined): string {
    return typeof value === 'number' ? String(value) : '0';
  }

  function dateLabel(value: string): string {
    return new Date(value).toLocaleString('ru-RU', {
      day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
      timeZone: 'Europe/Moscow'
    });
  }
</script>

<section class="mt-8 rounded-3xl border border-line bg-white px-6 py-7 shadow-sm sm:px-8" aria-labelledby="seo-history-title">
  <div class="flex flex-wrap items-end justify-between gap-3">
    <div>
      <h2 id="seo-history-title" class="text-2xl font-bold tracking-tight">SEO-история</h2>
      <p class="mt-2 text-sm leading-6 text-muted">
        Сохранённые SEO-анализы, новые сверху. Отчёт открывается из сохранённых данных, без новых
        обращений к Яндексу и моделям.
      </p>
    </div>
  </div>

  {#if error}
    <p role="alert" class="mt-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{error}</p>
  {/if}

  {#if items.length === 0}
    <p class="mt-5 text-sm text-muted">Сохранённых SEO-анализов пока нет.</p>
  {:else}
    <div class="mt-5 overflow-x-auto">
      <table class="w-full min-w-200 border-collapse text-left text-sm" aria-label="SEO-история">
        <thead class="bg-canvas">
          <tr>
            <th scope="col" class={th}>Сфера и сайт</th>
            <th scope="col" class={th}>Компания</th>
            <th scope="col" class={th}>Дата</th>
            <th scope="col" class={th}>Состояние</th>
            <th scope="col" class={th}>Строки</th>
            <th scope="col" class={th}>Действия</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line">
          {#each items as item (item.id)}
            <tr data-seo-history data-status={item.status} data-analysis={item.id}>
              <th scope="row" class="px-4 py-5 font-medium text-ink">
                <span class="block">{item.sphere || '—'}</span>
                <span class="mt-1 block break-all text-xs font-normal text-muted">{item.host}</span>
              </th>
              <td class={`${td} text-muted`}>{item.company_name || '—'}</td>
              <td class={`${td} text-muted`}>{dateLabel(item.created_at)}</td>
              <td class={td}>{STATUS_LABELS[item.status]}</td>
              <td class={`${td} text-muted`}>
                запросов {counter(item.counters?.queries)}, Яндекс {counter(item.counters?.search_rows)},
                модели {counter(item.counters?.model_rows)}
              </td>
              <td class={td}>
                <button
                  type="button"
                  onclick={() => onView(item.id)}
                  class="rounded-lg border border-line px-3 py-2 hover:border-accent"
                >
                  Открыть отчёт
                </button>
                <button
                  type="button"
                  onclick={() => confirmDelete(item)}
                  disabled={!terminal(item.status)}
                  aria-label={`Удалить анализ ${item.id}`}
                  class="ml-2 rounded-lg px-3 py-2 text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Удалить
                </button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}

  {#if nextCursor}
    <button
      type="button"
      onclick={onMore}
      disabled={loading}
      class="mt-5 rounded-xl border border-line px-4 py-2 text-sm font-semibold hover:border-accent disabled:opacity-50"
    >
      {loading ? 'Загружаем…' : 'Показать ещё'}
    </button>
  {/if}
</section>
