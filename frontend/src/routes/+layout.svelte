<script lang="ts">
  import { tick } from 'svelte';
  import '../app.css';
  import ConfigsPanel from '$lib/components/ConfigsPanel.svelte';
  import SettingsPanel from '$lib/components/SettingsPanel.svelte';
  import SearchSettingsPanel from '$lib/components/SearchSettingsPanel.svelte';
  import SeoSettingsPanel from '$lib/components/SeoSettingsPanel.svelte';

  let { children, data } = $props();

  const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  type SettingsTab = 'models' | 'search' | 'seo';
  const SETTINGS_TABS: readonly SettingsTab[] = ['models', 'search', 'seo'];

  let settingsOpen = $state(false);
  let opener = $state<HTMLButtonElement | null>(null);
  let panel = $state<HTMLDivElement | null>(null);
  let configButton = $state<HTMLButtonElement | null>(null);
  let configPanel = $state<HTMLDivElement | null>(null);
  let configWindow = $state(false);
  let activeTab = $state<SettingsTab>('models');
  let modelTab = $state<HTMLButtonElement | null>(null);
  let searchTab = $state<HTMLButtonElement | null>(null);
  let seoTab = $state<HTMLButtonElement | null>(null);

  function resetConfig() {
    configWindow = false;
  }

  function open() {
    resetConfig();
    activeTab = 'models';
    settingsOpen = true;
  }

  function tabElement(tab: SettingsTab): HTMLButtonElement | null {
    if (tab === 'models') return modelTab;
    return tab === 'search' ? searchTab : seoTab;
  }

  function onTabKeydown(event: KeyboardEvent) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    if (event.key === 'Home') activeTab = SETTINGS_TABS[0];
    else if (event.key === 'End') activeTab = SETTINGS_TABS[SETTINGS_TABS.length - 1];
    else {
      const step = event.key === 'ArrowRight' ? 1 : -1;
      const index = SETTINGS_TABS.indexOf(activeTab);
      activeTab = SETTINGS_TABS[(index + step + SETTINGS_TABS.length) % SETTINGS_TABS.length];
    }
    tabElement(activeTab)?.focus();
  }

  function close() {
    if (!settingsOpen) return;
    settingsOpen = false;
    resetConfig();
    // The keyboard user came from the opener, so the opener takes focus back.
    opener?.focus();
  }

  async function closeConfig() {
    if (!configWindow) return;
    resetConfig();
    // The settings dialog is inert while this window is open, so wait until it is not.
    await tick();
    configButton?.focus();
  }

  function showConfigurationFile() {
    configWindow = true;
  }

  function topPanel(): HTMLElement | null {
    return configWindow ? configPanel : panel;
  }

  function focusable(): HTMLElement[] {
    const root = topPanel();
    if (!root) return [];
    return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((item) => item.getClientRects().length > 0);
  }

  function onKeydown(event: KeyboardEvent) {
    if (!settingsOpen) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      if (configWindow) closeConfig();
      else close();
      return;
    }
    if (event.key !== 'Tab') return;
    const items = focusable();
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    const current = document.activeElement as HTMLElement | null;
    const root = topPanel();
    if (!current || !root?.contains(current)) {
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
    if (!settingsOpen || configWindow) return;
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
        class="pointer-events-auto flex h-full max-h-200 w-full max-w-200 flex-col overflow-hidden rounded-2xl bg-shell text-shell-ink shadow-2xl"
        role="dialog"
        aria-modal={!configWindow}
        aria-labelledby="settings-title"
        inert={configWindow}
        bind:this={panel}
      >
        <div class="flex flex-wrap items-center justify-between gap-3 px-5 py-4 sm:px-6">
          <h2 id="settings-title" class="text-base font-bold tracking-tight">Настройки API</h2>
          <div class="ml-auto flex items-center gap-2">
            <button
              type="button"
              class="inline-flex min-h-10 items-center rounded-full border border-shell-line px-3.5 text-sm font-medium text-shell-ink transition hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shell-accent disabled:opacity-60"
              aria-expanded={configWindow}
              aria-controls="configuration-file"
              aria-haspopup="dialog"
              bind:this={configButton}
              onclick={showConfigurationFile}
            >Открыть файл конфигурации</button>
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
        </div>

        <div class="flex min-h-0 min-w-0 flex-1 flex-col sm:flex-row">
          <div role="tablist" aria-label="Разделы настроек" tabindex="-1" class="flex shrink-0 gap-1 px-4 pb-2 sm:w-52 sm:flex-col sm:pb-4 lg:w-56" onkeydown={onTabKeydown}>
            <button
              type="button"
              id="settings-models-tab"
              role="tab"
              aria-controls="settings-models-panel"
              aria-selected={activeTab === 'models'}
              tabindex={activeTab === 'models' ? 0 : -1}
              bind:this={modelTab}
              onclick={() => (activeTab = 'models')}
              class={`inline-flex min-h-11 items-center gap-2.5 rounded-lg px-3.5 py-2.5 text-left text-sm font-semibold text-shell-ink transition hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shell-accent sm:w-full ${activeTab === 'models' ? 'bg-shell-active' : ''}`}
            >
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" class="size-4 shrink-0" aria-hidden="true">
                <path d="M4 5.5h12M4 10h12M4 14.5h7" stroke-linecap="round" />
              </svg>
              Модели
            </button>
            <button
              type="button"
              id="settings-search-tab"
              role="tab"
              aria-controls="settings-search-panel"
              aria-selected={activeTab === 'search'}
              tabindex={activeTab === 'search' ? 0 : -1}
              bind:this={searchTab}
              onclick={() => (activeTab = 'search')}
              class={`inline-flex min-h-11 items-center gap-2.5 rounded-lg px-3.5 py-2.5 text-left text-sm font-semibold text-shell-ink transition hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shell-accent sm:w-full ${activeTab === 'search' ? 'bg-shell-active' : ''}`}
            >
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" class="size-4 shrink-0" aria-hidden="true">
                <circle cx="8.5" cy="8.5" r="5" /><path d="m12.2 12.2 4.2 4.2" stroke-linecap="round" />
              </svg>
              Поисковые системы
            </button>
            <button
              type="button"
              id="settings-seo-tab"
              role="tab"
              aria-controls="settings-seo-panel"
              aria-selected={activeTab === 'seo'}
              tabindex={activeTab === 'seo' ? 0 : -1}
              bind:this={seoTab}
              onclick={() => (activeTab = 'seo')}
              class={`inline-flex min-h-11 items-center gap-2.5 rounded-lg px-3.5 py-2.5 text-left text-sm font-semibold text-shell-ink transition hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shell-accent sm:w-full ${activeTab === 'seo' ? 'bg-shell-active' : ''}`}
            >
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" class="size-4 shrink-0" aria-hidden="true">
                <path d="M4 15.5V11m4 4.5V6m4 9.5V8.5m4 7V4.5" stroke-linecap="round" />
              </svg>
              SEO-анализ
            </button>
          </div>

          <div id="settings-models-panel" role="tabpanel" aria-labelledby="settings-models-tab" tabindex="0" hidden={activeTab !== 'models'} class="min-h-0 min-w-0 flex-1 overflow-y-auto px-4 pt-1 pb-6 sm:px-6 sm:pb-8 lg:px-8">
            <SettingsPanel data={data} />
          </div>
          <div id="settings-search-panel" role="tabpanel" aria-labelledby="settings-search-tab" tabindex="0" hidden={activeTab !== 'search'} class="min-h-0 min-w-0 flex-1 overflow-y-auto px-4 pt-1 pb-6 sm:px-6 sm:pb-8 lg:px-8">
            <SearchSettingsPanel settings={data.searchSettings} loadError={data.searchSettingsError} />
          </div>
          <div id="settings-seo-panel" role="tabpanel" aria-labelledby="settings-seo-tab" tabindex="0" hidden={activeTab !== 'seo'} class="min-h-0 min-w-0 flex-1 overflow-y-auto px-4 pt-1 pb-6 sm:px-6 sm:pb-8 lg:px-8">
            <SeoSettingsPanel settings={data.seoSettings} loadError={data.seoSettingsError} />
          </div>
        </div>
      </div>
    </div>

    <ConfigsPanel bind:panel={configPanel} open={configWindow} onclose={closeConfig} />
  {/if}
</div>
