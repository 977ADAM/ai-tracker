<script lang="ts">
  import '../app.css';
  import SettingsPanel from '$lib/components/SettingsPanel.svelte';

  let { children, data } = $props();

  const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  let settingsOpen = $state(false);
  let opener = $state<HTMLButtonElement | null>(null);
  let panel = $state<HTMLDivElement | null>(null);

  function open() {
    settingsOpen = true;
  }

  function close() {
    if (!settingsOpen) return;
    settingsOpen = false;
    // The keyboard user came from the opener, so the opener takes focus back.
    opener?.focus();
  }

  function focusable(): HTMLElement[] {
    if (!panel) return [];
    return Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((item) => item.getClientRects().length > 0);
  }

  function onKeydown(event: KeyboardEvent) {
    if (!settingsOpen) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== 'Tab') return;
    const items = focusable();
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    const current = document.activeElement as HTMLElement | null;
    if (!current || !panel?.contains(current)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
      return;
    }
    if (event.shiftKey && current === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && current === last) {
      event.preventDefault();
      first.focus();
    }
  }

  // Keyboard focus must stay inside the open dialog, so it starts there too.
  $effect(() => {
    if (!settingsOpen) return;
    panel?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
  });
</script>

<svelte:window onkeydown={onKeydown} />

<div class="min-h-screen bg-canvas font-sans text-ink antialiased">
  <header class="border-b border-line bg-white/90">
    <div class="mx-auto flex max-w-[1920px] flex-wrap items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
      <a href="/" class="inline-flex items-center gap-3 rounded-lg font-bold tracking-tight text-ink focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent">
        <span class="grid size-10 place-items-center rounded-xl bg-ink text-xl text-white" aria-hidden="true">✳</span>
        <span class="text-lg">ИИ-трекинг</span>
      </a>
      <nav aria-label="Основная навигация" class="flex items-center gap-1 rounded-full border border-line bg-canvas p-1 text-sm font-semibold">
        <button
          type="button"
          class="rounded-full px-4 py-2 text-ink transition hover:bg-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          bind:this={opener}
          onclick={open}
          aria-expanded={settingsOpen}
          aria-controls="settings-panel"
        >
          Настройки API
        </button>
      </nav>
    </div>
  </header>

  {@render children()}

  {#if settingsOpen}
    <!-- затемнение: клик по нему закрывает панель -->
    <div class="fixed inset-0 z-40 bg-black/70" data-backdrop onclick={close} aria-hidden="true"></div>

    <!-- центрирующая обёртка: пропускает клики к затемнению -->
    <div class="pointer-events-none fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4">
      <div
        id="settings-panel"
        class="pointer-events-auto flex h-full max-h-[800px] w-full max-w-[800px] flex-col overflow-hidden rounded-2xl bg-shell text-shell-ink shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        bind:this={panel}
      >
        <div class="flex items-center justify-between gap-4 px-5 py-4 sm:px-6">
          <h2 id="settings-title" class="text-base font-bold tracking-tight">Настройки API</h2>
          <button
            type="button"
            class="grid size-10 shrink-0 place-items-center rounded-lg text-shell-muted transition hover:bg-white/5 hover:text-shell-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shell-accent"
            onclick={close}
            aria-label="Закрыть панель"
          >
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" class="size-5" aria-hidden="true">
              <path d="M5.5 5.5l9 9m0-9l-9 9" stroke-linecap="round" />
            </svg>
          </button>
        </div>

        <div class="flex min-h-0 min-w-0 flex-1 flex-col sm:flex-row">
          <nav aria-label="Разделы настроек" class="shrink-0 px-4 pb-2 sm:w-52 sm:pb-4 lg:w-56">
            <span
              aria-current="page"
              class="inline-flex items-center gap-2.5 rounded-lg bg-shell-active px-3.5 py-2.5 text-sm font-semibold text-shell-ink sm:w-full"
            >
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" class="size-4 shrink-0" aria-hidden="true">
                <path d="M4 5.5h12M4 10h12M4 14.5h7" stroke-linecap="round" />
              </svg>
              Модели
            </span>
          </nav>

          <div class="min-h-0 min-w-0 flex-1 overflow-y-auto px-4 pt-1 pb-6 sm:px-6 sm:pb-8 lg:px-8">
            <SettingsPanel data={data} />
          </div>
        </div>
      </div>
    </div>
  {/if}
</div>
