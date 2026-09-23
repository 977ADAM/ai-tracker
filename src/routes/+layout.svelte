<script lang="ts">
  import '../app.css';
  let { children } = $props();
</script>

<header class="border-b border-slate-200 bg-white/80">
  <div class="mx-auto flex min-h-18 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
    <a href="/" class="inline-flex items-center gap-3 text-lg font-extrabold tracking-tight text-slate-800"><span class="grid h-9 w-9 place-items-center rounded-xl bg-emerald-100 text-2xl text-emerald-700">✳</span>ИИ-трекинг</a>
    <nav aria-label="Основная навигация" class="flex gap-4 text-sm font-semibold text-slate-600"><a href="/" class="hover:text-emerald-700">Проверка</a><a href="/settings" class="hover:text-emerald-700">Настройки API</a></nav>
  </div>
</header>
{@render children()}
