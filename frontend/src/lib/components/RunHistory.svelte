<script lang="ts">
  import type { RunHistoryItem } from '$lib/types';

  let {
    items,
    nextCursor,
    onView,
    onDelete,
    onMore,
    loading = false,
  }: {
    items: RunHistoryItem[];
    nextCursor: string | null;
    onView: (id: string) => void;
    onDelete: (id: string) => void;
    onMore: () => void;
    loading?: boolean;
  } = $props();

  function confirmDelete(id: string) {
    if (window.confirm('Удалить этот прогон и его результаты?')) onDelete(id);
  }

  function dateLabel(value: string): string {
    return new Date(value).toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Europe/Moscow',
    });
  }
</script>

<section
  class="mt-8 rounded-3xl border border-line bg-white px-6 py-7 shadow-sm sm:px-8"
  aria-labelledby="history-title"
>
  <h2 id="history-title" class="text-2xl font-bold tracking-tight">История</h2>
  {#if items.length === 0}
    <p class="mt-5 text-sm text-muted">Сохранённых прогонов пока нет.</p>
  {:else}
    <div class="mt-5 overflow-x-auto">
      <table
        class="w-full min-w-160 border-collapse text-left text-sm"
        aria-label="История прогонов"
      >
        <thead class="bg-canvas text-sm font-semibold"
          ><tr
            ><th scope="col" class="px-4 py-4">Ключевые слова</th><th scope="col" class="px-4 py-4"
              >Дата</th
            ><th scope="col" class="px-4 py-4">Состояние</th><th scope="col" class="px-4 py-4"
              >Действия</th
            ></tr
          ></thead
        >
        <tbody class="divide-y divide-line">
          {#each items as item (item.id)}
            <tr
              ><td class="px-4 py-5">{item.prompts.join(', ')}</td><td
                class="px-4 py-5 whitespace-nowrap">{dateLabel(item.created_at)}</td
              >
              <td class="px-4 py-5"
                >{item.status === 'pending'
                  ? 'Выполняется'
                  : item.status === 'interrupted'
                    ? 'Прервано'
                    : 'Завершено'}</td
              >
              <td class="px-4 py-5 whitespace-nowrap"
                ><button
                  type="button"
                  onclick={() => onView(item.id)}
                  class="rounded-lg border border-line px-3 py-2 hover:border-accent"
                  >Посмотреть задачу</button
                >
                <button
                  type="button"
                  onclick={() => confirmDelete(item.id)}
                  disabled={item.status === 'pending'}
                  aria-label={`Удалить прогон ${item.id}`}
                  class="ml-2 rounded-lg px-3 py-2 text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-40"
                  >Удалить</button
                ></td
              ></tr
            >
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
      >Показать ещё</button
    >
  {/if}
</section>
