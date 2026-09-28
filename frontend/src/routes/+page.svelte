<script lang="ts">
  import { onDestroy, onMount, untrack } from 'svelte';
  import SeoForm from '$lib/components/SeoForm.svelte';
  import SeoRunProgress from '$lib/components/SeoRunProgress.svelte';
  import { validateSeoForm } from '$lib/seo-form';
  import type { SeoFormInput } from '$lib/seo-form';
  import type { FormConfig, PublicProvider, SeoAnalysisCreated, SeoAnalysisSnapshot, SeoHistoryPage } from '$lib/types';

  type Data = {
    providers: PublicProvider[];
    form?: FormConfig | null;
    loadError: string;
  };
  let { data }: { data: Data } = $props();

  const POLL_INTERVAL_MS = 30_000;
  let activeId = $state<string | null>(null);
  let pendingId = $state<string | null>(null);
  let snapshot = $state<SeoAnalysisSnapshot | null>(null);
  let error = $state(untrack(() => data.loadError));
  let runError = $state('');
  let cancelling = $state(false);
  let pollTimer: ReturnType<typeof setTimeout> | undefined;
  let destroyed = false;

  const terminal = $derived(!!snapshot && snapshot.status !== 'running');

  function detail(value: unknown, fallback: string): string {
    return value !== null && typeof value === 'object' && 'detail' in value && typeof value.detail === 'string'
      ? value.detail : fallback;
  }
  async function payload(response: Response): Promise<unknown> {
    try { return await response.json(); }
    catch { return null; }
  }
  function stopPolling() {
    if (pollTimer !== undefined) clearTimeout(pollTimer);
    pollTimer = undefined;
  }
  function schedulePoll(id: string) {
    stopPolling();
    pollTimer = setTimeout(() => void pollAnalysis(id), POLL_INTERVAL_MS);
  }
  async function pollAnalysis(id: string) {
    if (destroyed || pendingId !== id) return;
    try {
      const response = await fetch(`/api/seo/analyses/${encodeURIComponent(id)}`);
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось получить состояние анализа'));
      if (destroyed || pendingId !== id) return;
      const current = value as SeoAnalysisSnapshot;
      snapshot = current;
      runError = '';
      if (current.status === 'running') schedulePoll(id);
      else { pendingId = null; stopPolling(); }
    } catch (cause) {
      if (destroyed) return;
      runError = cause instanceof Error ? cause.message : 'Не удалось обновить анализ';
      schedulePoll(id);
    }
  }
  async function loadAnalysis(id: string) {
    activeId = id;
    runError = '';
    try {
      const response = await fetch(`/api/seo/analyses/${encodeURIComponent(id)}`);
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось открыть анализ'));
      if (destroyed || activeId !== id) return;
      const current = value as SeoAnalysisSnapshot;
      snapshot = current;
      if (current.status === 'running') { pendingId = id; schedulePoll(id); }
      else { pendingId = null; stopPolling(); }
    } catch (cause) {
      if (destroyed) return;
      runError = cause instanceof Error ? cause.message : 'Не удалось открыть анализ';
    }
  }
  async function loadActiveFromHistory() {
    try {
      const response = await fetch('/api/seo/analyses');
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось загрузить историю анализов'));
      if (destroyed) return;
      const page = value as SeoHistoryPage;
      const active = page.items.find((item) => item.status === 'running');
      if (active && !pendingId) await loadAnalysis(active.id);
    } catch (cause) {
      if (destroyed) return;
      runError = cause instanceof Error ? cause.message : 'Не удалось загрузить историю анализов';
    }
  }
  async function startAnalysis(input: SeoFormInput) {
    error = '';
    runError = '';
    try {
      const response = await fetch('/api/seo/analyses', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          url: input.url.trim(),
          sphere: input.sphere.trim(),
          seeds: input.seeds.map((seed) => seed.trim()).filter((seed) => seed.length > 0),
          services: input.services.map((service) => service.trim()).filter((service) => service.length > 0),
          connection_ids: input.connectionIds
        })
      });
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось запустить анализ'));
      const created = value as SeoAnalysisCreated;
      snapshot = null;
      await loadAnalysis(created.id);
      void loadActiveFromHistory();
    } catch (cause) {
      throw cause instanceof Error ? cause : new Error('Не удалось запустить анализ');
    }
  }
  function submit(input: SeoFormInput) {
    error = '';
    const problem = validateSeoForm(input);
    if (problem) { error = problem; return; }
    return startAnalysis(input);
  }
  async function cancel() {
    if (!activeId || cancelling) return;
    cancelling = true;
    runError = '';
    try {
      const response = await fetch(`/api/seo/analyses/${encodeURIComponent(activeId)}/cancel`, { method: 'POST' });
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось отменить анализ'));
      if (destroyed) return;
      snapshot = value as SeoAnalysisSnapshot;
      pendingId = null;
      stopPolling();
    } catch (cause) {
      if (destroyed) return;
      runError = cause instanceof Error ? cause.message : 'Не удалось отменить анализ';
    } finally {
      cancelling = false;
    }
  }

  onMount(() => { void loadActiveFromHistory(); });
  onDestroy(() => { destroyed = true; stopPolling(); });
</script>

<svelte:head><title>ИИ-трекинг · SEO-анализ сайта</title></svelte:head>

<main class="mx-48 max-w-[1920px] px-4 pb-16 sm:px-6 lg:px-8">
    <nav aria-label="Хлебные крошки" class="flex items-center gap-2 py-6 text-xs font-medium text-muted">
        <a href="/" class="hover:text-accent">Инструменты</a>
        <span aria-hidden="true">/</span>
        <span class="text-ink">SEO-анализ сайта</span>
    </nav>

    <section class="relative overflow-hidden rounded-3xl bg-ink px-6 py-10 text-white shadow-lg shadow-ink/10 sm:px-10 sm:py-12 lg:px-14">
        <div class="relative max-w-4xl">
            <p class="mb-5 text-xs font-bold tracking-[0.16em] text-emerald-200 uppercase">SEO-анализ сайта и конкурентов</p>
            <h1 class="text-3xl font-bold leading-tight sm:text-4xl lg:text-5xl">Узнайте, где виден ваш сайт</h1>
            <p class="mt-6 max-w-3xl text-sm leading-7 text-emerald-50/90 sm:text-base">
                Один запуск: система обходит сайт, ищет конкурентов в Яндексе, генерирует запросы, проверяет их в ИИ и Поиске и собирает отчёт. Прогон можно отменить, а результаты сохраняются.
            </p>
        </div>
    </section>

    <SeoForm
        providers={data.providers}
        form={data.form ?? null}
        disabled={!!data.loadError || !data.form}
        error={error}
        onSubmit={submit}
    />

    {#if runError}
        <p role="alert" class="mt-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {runError}
        </p>
    {/if}

    {#if snapshot}
        <div class="scroll-mt-8" id="seo-run">
            <SeoRunProgress {snapshot} {cancelling} onCancel={() => void cancel()} />
        </div>
    {:else}
        <section class="mt-8 rounded-3xl border border-dashed border-line bg-white px-6 py-14 text-center shadow-sm">
            <h2 class="text-xl font-bold">Пока нет SEO-анализа</h2>
            <p class="mt-2 text-sm text-muted">Заполните форму выше и запустите первый анализ. Незавершённый прогон возобновится после перезагрузки страницы.</p>
        </section>
    {/if}

    {#if terminal && snapshot?.status === 'completed'}
        <aside class="mt-8 rounded-2xl border border-line bg-accent-soft px-6 py-5 text-sm leading-6 text-ink">
            <strong>Отчёт готов</strong>
            <p class="mt-2 text-muted">
                Подробные метрики, разрезы по категориям и услугам, а также SEO-история появятся в следующей версии.
            </p>
        </aside>
    {/if}

    <aside class="mt-8 rounded-2xl border border-line bg-accent-soft px-6 py-5 text-sm leading-6 text-ink">
        <strong>Как читать результат</strong>
        <p class="mt-2 text-muted">
            Поиск проверяет только первую десятку органических результатов Яндекса по всей России. Ошибка отдельного источника не означает, что сайта нет в выдаче: такие строки исключаются из метрик.
        </p>
    </aside>
</main>
