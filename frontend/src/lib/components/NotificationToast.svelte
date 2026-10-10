<script lang="ts">
  import { notification, dismissNotification } from '$lib/notifications';
  $effect(() => {
    if (!$notification) return;
    const timer = setTimeout(dismissNotification, 6000);
    return () => clearTimeout(timer);
  });
</script>

<div
  role="status"
  aria-live="polite"
  aria-atomic="true"
  class="fixed right-4 bottom-4 left-4 z-[60] sm:left-auto sm:max-w-sm"
>
  {#if $notification}
    <div
      class="flex items-center gap-3 rounded-xl border border-line bg-white px-4 py-3 text-sm text-ink shadow-lg"
    >
      <svg
        class="size-5 shrink-0 text-teal-700"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        aria-hidden="true"
        ><path d="m5 12 4 4L19 6" stroke-linecap="round" stroke-linejoin="round" /></svg
      >
      <p class="flex-1">{$notification.text}</p>
      <button
        type="button"
        aria-label="Закрыть уведомление"
        onclick={dismissNotification}
        class="grid size-7 shrink-0 place-items-center rounded-lg text-muted hover:bg-canvas focus-visible:outline-2 focus-visible:outline-accent"
        >×</button
      >
    </div>
  {/if}
</div>
