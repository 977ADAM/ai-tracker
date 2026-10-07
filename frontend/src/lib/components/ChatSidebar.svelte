<script lang="ts">
  import type { ChatSummary } from '$lib/types';
  import { statusLabel } from '$lib/chat';

  let {
    chats,
    activeId,
    onSelect,
    onCreate,
    onDelete,
    busy = false
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
      day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
      timeZone: 'Europe/Moscow'
    });
  }
</script>

<aside
  class="rounded-3xl border border-line bg-white px-4 py-5 shadow-sm sm:px-5"
  aria-labelledby="chat-sidebar-title"
>
  <div class="flex flex-wrap items-center justify-between gap-3">
    <h2 id="chat-sidebar-title" class="text-lg font-bold tracking-tight">Чаты</h2>
    <button
      type="button"
      onclick={onCreate}
      disabled={busy}
      class="rounded-xl border border-line px-3 py-2 text-sm font-semibold hover:border-accent disabled:cursor-not-allowed disabled:opacity-40"
    >
      Новый чат
    </button>
  </div>

  {#if chats.length === 0}
    <p class="mt-5 text-sm text-muted">Чатов пока нет.</p>
  {:else}
    <ul class="mt-5 space-y-2" aria-label="Чаты">
      {#each chats as chat (chat.id)}
        <li class="flex items-stretch gap-1">
          <button
            type="button"
            onclick={() => onSelect(chat.id)}
            disabled={busy}
            aria-current={chat.id === activeId ? 'true' : undefined}
            aria-label={`Открыть чат ${chat.title}`}
            class={`min-w-0 flex-1 rounded-2xl border px-4 py-3 text-left disabled:cursor-not-allowed disabled:opacity-40 ${
              chat.id === activeId ? 'border-accent bg-accent-soft' : 'border-line hover:border-accent/60'
            }`}
          >
            <span class="block truncate font-semibold text-ink">{chat.title}</span>
            <span class="mt-1 block text-xs text-muted">{dateLabel(chat.updated_at)}</span>
            <span data-chat-status class="mt-1 block text-xs font-semibold text-muted">{statusLabel(chat)}</span>
          </button>
          <button
            type="button"
            onclick={() => confirmDelete(chat)}
            disabled={busy || !removable(chat)}
            aria-label={`Удалить чат ${chat.id}`}
            class="rounded-2xl px-3 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Удалить
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</aside>
