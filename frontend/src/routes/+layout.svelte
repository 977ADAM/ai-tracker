<script lang="ts">
  import '../app.css';
  import SettingsPanel from '$lib/components/SettingsPanel.svelte';

  let { children, data } = $props();

  let settingsOpen = $state(false);
</script>

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
          onclick={() => (settingsOpen = true)}
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
    <!-- затемнение -->
    <div
      class="fixed inset-0 z-40 bg-ink/40"
      onclick={() => (settingsOpen = false)}
      aria-hidden="true"
    ></div>

    <!-- центрирующая обёртка + панель -->
    <div class="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        id="settings-panel"
        class="flex h-[800px] max-h-[90vh] w-[800px] max-w-[90vw] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-label="Настройки API"
      >
        <div class="flex items-center justify-between border-b border-line px-6 py-4">
          <h2 class="text-lg font-bold tracking-tight">Настройки API</h2>
          <button
            type="button"
            class="flex h-9 w-9 items-center justify-center rounded-full text-xl text-muted transition hover:bg-canvas hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            onclick={() => (settingsOpen = false)}
            aria-label="Закрыть панель"
          >
            ×
          </button>
        </div>

        <div class="flex-1 overflow-y-auto p-6">
          <SettingsPanel data={data} />
        </div>
      </div>
    </div>
  {/if}
</div>
