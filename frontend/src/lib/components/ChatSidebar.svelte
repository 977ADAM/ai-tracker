<script lang="ts">
  import type { ChatSummary } from '$lib/types';

  let {
    chats,
    activeId,
    onSelect,
    onCreate,
    onDelete,
    busy = false,
  }: {
    chats: ChatSummary[];
    activeId: string | null;
    onSelect: (id: string) => void;
    onCreate: () => void;
    onDelete: (id: string) => void;
    busy?: boolean;
  } = $props();

  /** A run in progress owns its chat: deleting it while it writes would lose the analysis. */
  function removable(chat: ChatSummary): boolean {
    return !chat.running;
  }

  function confirmDelete(chat: ChatSummary) {
    if (window.confirm(`Удалить чат «${chat.title}» и его сообщения?`)) onDelete(chat.id);
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

<aside
  class="rounded-xl border border-line bg-white px-3 py-2.5 shadow-sm"
  aria-labelledby="chat-sidebar-title"
>
  <div class="flex flex-wrap items-center justify-between gap-2">
    <h2 id="chat-sidebar-title" class="text-[13px] font-bold tracking-tight">Чаты</h2>
    <button
      type="button"
      onclick={onCreate}
      disabled={busy}
      class="rounded-xl border border-line px-2.5 py-1.5 text-[13px] font-semibold hover:border-accent disabled:cursor-not-allowed disabled:opacity-40"
    >
      Новый чат
    </button>
  </div>

  {#if chats.length === 0}
    <p class="mt-2.5 text-[13px] text-muted">Чатов пока нет.</p>
  {:else}
    <ul class="mt-2.5 space-y-2" aria-label="Чаты">
      {#each chats as chat (chat.id)}
        <li class="flex items-stretch gap-1">
          <button
            type="button"
            onclick={() => onSelect(chat.id)}
            disabled={busy}
            aria-current={chat.id === activeId ? 'true' : undefined}
            aria-label={`Открыть чат ${chat.title}`}
            class={`min-w-0 flex-1 rounded-lg border px-2.5 py-1.5 text-left disabled:cursor-not-allowed disabled:opacity-40 ${
              chat.id === activeId
                ? 'border-accent bg-accent-soft'
                : 'border-line hover:border-accent/60'
            }`}
          >
            <span class="block truncate font-semibold text-ink">{chat.title}</span>
          </button>
          <button
            type="button"
            onclick={() => confirmDelete(chat)}
            disabled={busy || !removable(chat)}
            aria-label={`Удалить чат ${chat.id}`}
            class="rounded-lg px-2 text-[11px] font-semibold text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Удалить
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</aside>
