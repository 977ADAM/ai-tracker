<script lang="ts">
  let {
    disabled = false,
    busy = false,
    onSend
  }: { disabled?: boolean; busy?: boolean; onSend: (text: string) => void } = $props();

  /** The backend refuses an empty or over-long message; the field matches both rules. */
  const MAX_LENGTH = 4000;

  let text = $state('');
  let field = $state<HTMLTextAreaElement | null>(null);

  const blocked = $derived(disabled || busy);
  const canSend = $derived(text.trim().length > 0 && !blocked);
  const buttonLabel = $derived(busy ? 'Отправляем…' : 'Отправить');

  function send() {
    if (!canSend) return;
    onSend(text.trim());
    text = '';
    field?.focus();
  }

  function keydown(event: KeyboardEvent) {
    if (event.key !== 'Enter' || event.shiftKey) return;
    event.preventDefault();
    send();
  }
</script>

<section class="mt-8 rounded-3xl border border-line bg-white px-6 py-5 shadow-sm sm:px-8" aria-label="Ввод сообщения">
  <label class="mb-2 block text-sm font-semibold text-ink" for="chat-composer">Сообщение</label>
  <textarea
    id="chat-composer"
    bind:this={field}
    bind:value={text}
    onkeydown={keydown}
    disabled={blocked}
    maxlength={MAX_LENGTH}
    rows="3"
    placeholder="Опишите задачу: сайт, сфера, ключевые запросы, услуги"
    class="block min-h-24 w-full resize-y rounded-xl border border-line bg-canvas/50 px-4 py-3 text-sm leading-6 text-ink outline-none focus:border-accent disabled:opacity-60"
  ></textarea>

  <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
    <p class="text-xs leading-5 text-muted">Enter — отправить, Shift+Enter — новая строка.</p>
    <button
      type="button"
      onclick={send}
      disabled={!canSend}
      class="inline-flex min-h-11 items-center gap-2 rounded-xl bg-accent px-5 py-2 text-sm font-bold text-white disabled:opacity-60"
    >
      {buttonLabel}
      <span aria-hidden="true">↑</span>
    </button>
  </div>
</section>
