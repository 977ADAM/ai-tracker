<script lang="ts">
  import type { ChatMessage } from '$lib/types';
  import { messageText } from '$lib/chat';

  let { message }: { message: ChatMessage } = $props();

  // Svelte escapes interpolation, so an answer that contains "<b>" stays text.
  // Card messages carry their data in `payload` and are rendered by Tasks 10-11.
  const text = $derived(messageText(message));
  const mine = $derived(message.role === 'user');

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

{#if text}
  <article
    data-chat-message
    data-role={message.role}
    class={`rounded-xl border border-line px-3.5 py-1.5 shadow-sm ${mine ? 'bg-accent-soft' : 'bg-white'}`}
    aria-label={mine ? 'Ваше сообщение' : 'Сообщение ассистента'}
  >
    <p class="flex flex-wrap items-center gap-x-2 text-xs text-muted">
      <span class="font-bold text-ink">{mine ? 'Вы' : 'Ассистент'}</span>
      <span>{dateLabel(message.created_at)}</span>
    </p>
    <p
      data-chat-message-text
      class="mt-2 text-[13px] leading-5 break-words whitespace-pre-wrap text-ink"
    >
      {text}
    </p>
  </article>
{/if}
