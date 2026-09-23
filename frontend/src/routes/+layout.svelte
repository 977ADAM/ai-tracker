<script lang="ts">
  import '../app.css';

  let { children } = $props();
</script>

<div class="min-h-screen bg-canvas font-sans text-ink antialiased">
  <header class="border-b border-line bg-white/90">
    <div class="mx-auto flex max-w-[1920px] flex-wrap items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
      <a href="/" class="inline-flex items-center gap-3 rounded-lg font-bold tracking-tight text-ink focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent">
        <span class="grid size-10 place-items-center rounded-xl bg-ink text-xl text-white" aria-hidden="true">✳</span>
        <span class="text-lg">ИИ-трекинг</span>
      </a>
      <nav aria-label="Основная навигация" class="flex items-center gap-1 rounded-full border border-line bg-canvas p-1 text-sm font-semibold">
        <a href="/" class="rounded-full px-4 py-2 text-ink transition hover:bg-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">Проверка</a>
        <a href="/settings" class="rounded-full px-4 py-2 text-ink transition hover:bg-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">Настройки API</a>
      </nav>
    </div>
  </header>

  {@render children()}
</div>
