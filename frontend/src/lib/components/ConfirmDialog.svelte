<script lang="ts">
  import { onMount } from 'svelte';
  let {
    title,
    description,
    busy = false,
    onConfirm,
    onClose,
  }: {
    title: string;
    description: string;
    busy?: boolean;
    onConfirm: () => void;
    onClose: () => void;
  } = $props();
  let dialog: HTMLDialogElement;
  onMount(() => dialog.showModal());
</script>

<dialog
  bind:this={dialog}
  onclose={onClose}
  class="m-auto w-[calc(100%_-_2rem)] max-w-md rounded-2xl border border-line bg-white p-6 text-ink shadow-2xl backdrop:bg-black/40"
  aria-labelledby="confirm-title"
>
  <h2 id="confirm-title" class="text-lg font-semibold">{title}</h2>
  <p class="mt-3 text-sm text-muted">{description}</p>
  <div class="mt-6 flex gap-3">
    <button
      disabled={busy}
      class="rounded-lg bg-red-600 px-4 py-2 text-sm text-white"
      onclick={onConfirm}>Удалить</button
    ><button
      disabled={busy}
      class="rounded-lg border border-line px-4 py-2 text-sm"
      onclick={() => dialog.close()}>Отмена</button
    >
  </div>
</dialog>
