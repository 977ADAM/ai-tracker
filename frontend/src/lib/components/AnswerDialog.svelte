<script lang="ts">
  import { onMount } from 'svelte';
  import type { ModelRow } from '$lib/project-types';
  import { markdownHtml } from '$lib/markdown';
  import { sentimentLabels } from '$lib/project-client';
  let { row, onClose }: { row: ModelRow; onClose: () => void } = $props();
  let dialog: HTMLDialogElement;
  let html = $state('');
  onMount(() => {
    html = markdownHtml(row.answer ?? '');
    dialog.showModal();
  });
</script>

<dialog
  bind:this={dialog}
  onclose={onClose}
  class="m-auto max-h-[85vh] w-[calc(100%_-_2rem)] max-w-3xl rounded-2xl border border-line bg-white p-0 text-ink shadow-2xl backdrop:bg-black/40"
  aria-labelledby="answer-title"
>
  <div
    class="sticky top-0 flex items-start justify-between gap-4 border-b border-line bg-white p-5"
  >
    <div>
      <h2 id="answer-title" class="text-lg font-semibold">{row.query}</h2>
      <p class="mt-1 text-xs text-muted">
        {row.provider_name} · {row.answer_mode === 'deepseek_web' ? 'Веб-поиск' : 'Текстовый ответ'}
      </p>
    </div>
    <button class="rounded-lg border border-line px-3 py-2 text-sm" onclick={() => dialog.close()}
      >Закрыть</button
    >
  </div>
  <div class="p-5">
    <div class="prose prose-sm max-w-none">{@html html}</div>
    {#if row.brand_mentioned}<div class="mt-6 rounded-xl bg-canvas p-4">
        <h3 class="text-sm font-semibold">
          Тональность: {sentimentLabels[row.sentiment?.label ?? 'unknown']}
        </h3>
        <p class="mt-1 text-xs text-muted">Оценка служебной модели</p>
        {#if row.sentiment}<blockquote class="mt-3 text-sm">
            «{row.sentiment.evidence}»
          </blockquote>{:else}<p class="mt-2 text-sm">
            {row.sentiment_error ?? 'Оценка недоступна'}
          </p>{/if}
      </div>{/if}
    <h3 class="mt-6 text-sm font-semibold">Источники</h3>
    {#if row.answer_mode === 'text'}<p class="mt-2 text-sm text-muted">
        Веб-поиск не запрашивался.
      </p>{:else if !row.citations.length}<p class="mt-2 text-sm text-muted">
        Ответ не содержит цитат.
      </p>{:else}<ul class="mt-3 space-y-2">
        {#each row.citations as c (c)}<li class="text-sm">
            <a
              class="break-all text-accent underline"
              href={c.url}
              target="_blank"
              rel="noopener noreferrer">{c.title ?? c.url}</a
            >
          </li>{/each}
      </ul>{/if}
  </div>
</dialog>
