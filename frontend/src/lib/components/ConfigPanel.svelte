<script lang="ts">
  const FOCUSABLE = 'button:not([disabled]), [tabindex]:not([tabindex="-1"])';

  type Config = { directory: string; exists: boolean; content: string | null };

  let {
    open,
    onclose,
    panel = $bindable(null)
  }: {
    open: boolean;
    onclose: () => void;
    panel?: HTMLDivElement | null;
  } = $props();

  let config = $state<Config | null>(null);
  let error = $state('');
  let busy = $state(false);

  async function load(isCurrent: () => boolean) {
    busy = true;
    error = '';
    config = null;
    try {
      const response = await fetch('/api/config');
      const value: unknown = await response.json().catch(() => {
        throw new Error('Некорректный ответ сервиса');
      });
      if (!isCurrent()) return;
      if (!response.ok) {
        const detail = value && typeof value === 'object' && 'detail' in value && typeof value.detail === 'string'
          ? value.detail
          : 'Не удалось прочитать конфигурацию';
        throw new Error(detail);
      }
      if (!value || typeof value !== 'object' || !('directory' in value) || typeof value.directory !== 'string') {
        throw new Error('Некорректный ответ сервиса');
      }
      const loaded = value as Config;
      config = {
        directory: loaded.directory,
        exists: loaded.exists === true,
        content: typeof loaded.content === 'string' ? loaded.content : null
      };
    } catch (cause) {
      if (!isCurrent()) return;
      config = null;
      error = cause instanceof Error ? cause.message : 'Не удалось прочитать конфигурацию';
    } finally {
      if (isCurrent()) busy = false;
    }
  }

  $effect(() => {
    if (!open) return;
    let current = true;
    void load(() => current);
    return () => {
      current = false;
    };
  });

  $effect(() => {
    if (!open || !panel) return;
    panel.querySelector<HTMLElement>(FOCUSABLE)?.focus();
  });
</script>

{#if open}
  <div class="fixed inset-0 z-[60] bg-black/50" data-config-backdrop onclick={onclose} aria-hidden="true"></div>
  <div class="pointer-events-none fixed inset-0 z-[70] flex items-center justify-center p-2 sm:p-4">
    <div
      id="config"
      class="pointer-events-auto flex h-full max-h-200 w-full max-w-200 flex-col overflow-hidden rounded-2xl bg-shell text-shell-ink shadow-2xl"
      role="dialog"
      aria-modal="true"
      aria-labelledby="config-title"
      bind:this={panel}
    >
      <div class="flex items-start justify-between gap-3 px-5 py-4 sm:px-6">
        <div class="min-w-0">
          <h2 id="config-title" class="text-base font-bold tracking-tight">Конфигурация</h2>
          {#if config}
            <p class="mt-1 break-all font-mono text-xs leading-5 text-shell-muted">{config.directory}</p>
          {/if}
        </div>
        <button
          type="button"
          class="grid size-10 shrink-0 place-items-center rounded-lg text-shell-muted transition hover:bg-white/5 hover:text-shell-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shell-accent"
          onclick={onclose}
          aria-label="Закрыть конфигурацию"
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" class="size-5" aria-hidden="true">
            <path d="M5.5 5.5l9 9m0-9l-9 9" stroke-linecap="round" />
          </svg>
        </button>
      </div>
      <div class="min-h-0 flex-1 overflow-auto px-5 pb-6 sm:px-6">
        {#if error}
          <p role="alert" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm leading-6 text-rose-100">{error}</p>
        {:else if busy || !config}
          <p class="text-sm text-shell-muted">Читаем настройки…</p>
        {:else if config.exists && config.content !== null}
          <p class="mb-3 text-xs leading-5 text-shell-muted">
            Провайдеры, поисковая система и SEO-анализ в одном документе. Ключи API в файлы не записываются: они лежат в системном хранилище ключей.
          </p>
          <pre class="overflow-x-auto text-xs leading-5 whitespace-pre-wrap text-shell-ink">{config.content}</pre>
        {:else}
          <p class="text-sm leading-6 text-shell-muted">
            Настройки ещё не сохранены. Документ появится после первого сохранения провайдера,
            поисковой системы или служебной LLM.
          </p>
        {/if}
      </div>
    </div>
  </div>
{/if}
