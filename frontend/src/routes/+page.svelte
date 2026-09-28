<script lang="ts">
  import { onDestroy, onMount, untrack } from 'svelte';
  import RunResults from '$lib/components/RunResults.svelte';
  import RunHistory from '$lib/components/RunHistory.svelte';
  import { MAX_REGIONS, requestCount, requestCountLabel, validateRun } from '$lib/search-form';
  import type { FormConfig, PublicProvider, RunCreated, RunHistoryItem, RunHistoryPage, RunSnapshot, SearchRegion } from '$lib/types';

  type Data = {
    providers: PublicProvider[];
    form?: FormConfig | null;
    loadError: string;
    searchRegions?: SearchRegion[];
    searchRegionError?: string;
  };
  let { data }: { data: Data } = $props();

  type SearchEngine = 'yandex';

  const POLL_INTERVAL_MS = 30_000;
  let selected = $state<string[]>(untrack(() => data.form?.default_provider_ids ?? []));
  let brand = $state('');
  let domain = $state('');
  let promptsText = $state('');
  let regionRows = $state<(number | '')[]>([]);
  let regionEngines = $state<SearchEngine[]>([]);
  let loading = $state(false);
  let error = $state(untrack(() => data.loadError));
  let historyError = $state('');
  let historyLoading = $state(false);
  let history = $state<RunHistoryItem[]>([]);
  let nextCursor = $state<string | null>(null);
  let activeRunId = $state<string | null>(null);
  let pendingRunId = $state<string | null>(null);
  let snapshot = $state<RunSnapshot | null>(null);
  let pollTimer: ReturnType<typeof setTimeout> | undefined;
  let destroyed = false;

  const catalog = $derived(data.searchRegions ?? []);
  const chosenRegions = $derived(regionRows.filter((value): value is number => typeof value === 'number'));
  const yandexRequests = $derived(requestCount(promptsText, chosenRegions));
  const regionTargets = $derived(
    regionRows
      .map((region, index) => ({ region, engine: regionEngines[index] ?? 'yandex' }))
      .filter((entry): entry is { region: number; engine: SearchEngine } => typeof entry.region === 'number')
  );

  function toggleProvider(id: string) {
    selected = selected.includes(id) ? selected.filter((value) => value !== id) : [...selected, id];
  }
  function addRegion() {
    if (regionRows.length < MAX_REGIONS) {
      regionRows = [...regionRows, ''];
      regionEngines = [...regionEngines, 'yandex'];
    }
  }
  function removeRegion(index: number) {
    regionRows = regionRows.filter((_, position) => position !== index);
    regionEngines = regionEngines.filter((_, position) => position !== index);
  }
  function regionTaken(id: number, index: number): boolean {
    return regionRows.some((value, position) => position !== index && value === id);
  }
  function stopPolling() {
    if (pollTimer !== undefined) clearTimeout(pollTimer);
    pollTimer = undefined;
  }
  function detail(value: unknown, fallback: string): string {
    return value !== null && typeof value === 'object' && 'detail' in value && typeof value.detail === 'string'
      ? value.detail : fallback;
  }
  function updateHistoryRow(run: RunSnapshot) {
    history = history.map((item) => item.id === run.id
      ? { ...item, status: run.status, prompts: run.prompts } : item);
  }
  function schedulePoll(id: string) {
    stopPolling();
    pollTimer = setTimeout(() => void pollRun(id), POLL_INTERVAL_MS);
  }
  async function pollRun(id: string) {
    if (destroyed || pendingRunId !== id) return;
    try {
      const response = await fetch(`/api/runs/${encodeURIComponent(id)}`);
      const value: unknown = await response.json();
      if (!response.ok) throw new Error(detail(value, 'Не удалось получить состояние прогона'));
      const run = value as RunSnapshot;
      if (destroyed) return;
      if (activeRunId === id) snapshot = run;
      updateHistoryRow(run);
      if (run.status === 'pending') schedulePoll(id);
      else { pendingRunId = null; stopPolling(); }
    } catch (cause) {
      if (destroyed) return;
      historyError = cause instanceof Error ? cause.message : 'Не удалось обновить прогон';
      schedulePoll(id);
    }
  }
  async function loadRun(id: string, scroll = true) {
    activeRunId = id;
    try {
      const response = await fetch(`/api/runs/${encodeURIComponent(id)}`);
      const value: unknown = await response.json();
      if (!response.ok) throw new Error(detail(value, 'Не удалось открыть прогон'));
      if (destroyed || activeRunId !== id) return;
      snapshot = value as RunSnapshot;
      updateHistoryRow(snapshot);
      if (snapshot.status === 'pending' && pendingRunId === null) {
        pendingRunId = id;
        schedulePoll(id);
      } else if (snapshot.status !== 'pending' && pendingRunId === id) {
        pendingRunId = null;
        stopPolling();
      }
      if (scroll) setTimeout(() => document.getElementById('run-results')?.scrollIntoView({ behavior: 'smooth' }), 0);
    } catch (cause) {
      if (destroyed) return;
      error = cause instanceof Error ? cause.message : 'Не удалось открыть прогон';
    }
  }
  async function loadHistoryFirstPage() {
    try {
      const response = await fetch('/api/runs');
      const value: unknown = await response.json();
      if (!response.ok) throw new Error(detail(value, 'Не удалось загрузить историю'));
      if (destroyed) return;
      const page = value as RunHistoryPage;
      history = page.items;
      nextCursor = page.next_cursor;
      historyError = '';
      const pending = page.items.find((item) => item.status === 'pending');
      if (pending && !pendingRunId) {
        pendingRunId = pending.id;
        schedulePoll(pending.id);
      }
    } catch (cause) {
      if (destroyed) return;
      historyError = cause instanceof Error ? cause.message : 'Не удалось загрузить историю';
    }
  }
  async function loadMore() {
    if (!nextCursor || historyLoading) return;
    historyLoading = true;
    try {
      const response = await fetch(`/api/runs?cursor=${encodeURIComponent(nextCursor)}`);
      const value: unknown = await response.json();
      if (!response.ok) throw new Error(detail(value, 'Не удалось загрузить историю'));
      const page = value as RunHistoryPage;
      history = [...history, ...page.items.filter((item) => !history.some((old) => old.id === item.id))];
      nextCursor = page.next_cursor;
      historyError = '';
    } catch (cause) {
      historyError = cause instanceof Error ? cause.message : 'Не удалось загрузить историю';
    } finally { historyLoading = false; }
  }
  async function deleteRun(id: string) {
    try {
      const response = await fetch(`/api/runs/${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (!response.ok) {
        const value: unknown = await response.json();
        throw new Error(detail(value, 'Не удалось удалить прогон'));
      }
      history = history.filter((item) => item.id !== id);
      if (activeRunId === id) { activeRunId = null; snapshot = null; }
      historyError = '';
    } catch (cause) {
      historyError = cause instanceof Error ? cause.message : 'Не удалось удалить прогон';
    }
  }
  async function runCombined() {
    if (loading || pendingRunId) return;
    loading = true;
    error = '';
    try {
      const response = await fetch('/api/runs', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          brand,
          domain,
          prompts_text: promptsText,
          provider_ids: selected,
          regions: chosenRegions,
          region_targets: regionTargets,
        })
      });
      const value: unknown = await response.json();
      if (!response.ok) throw new Error(detail(value, 'Не удалось запустить проверку'));
      const created = value as RunCreated;
      activeRunId = created.id;
      pendingRunId = created.status === 'pending' ? created.id : null;
      await loadRun(created.id);
      await loadHistoryFirstPage();
      if (pendingRunId === created.id) schedulePoll(created.id);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Не удалось запустить проверку';
    } finally { loading = false; }
  }
  function submit(event: SubmitEvent) {
    event.preventDefault();
    if (loading || pendingRunId) return;
    error = '';
    const problem = validateRun({ brand, domain, promptsText, providerIds: selected, regions: chosenRegions });
    if (problem) { error = problem; return; }
    void runCombined();
  }

  onMount(() => { void loadHistoryFirstPage(); });
  onDestroy(() => { destroyed = true; stopPolling(); });
</script>

<svelte:head><title>ИИ-трекинг · Проверка бренда</title></svelte:head>

<main class="mx-48 max-w-[1920px] px-4 pb-16 sm:px-6 lg:px-8">
    <nav aria-label="Хлебные крошки" class="flex items-center gap-2 py-6 text-xs font-medium text-muted">
        <a href="/" class="hover:text-accent">Инструменты</a>
        <span aria-hidden="true">/</span>
        <span class="text-ink">Проверка бренда</span>
    </nav>

    <section class="relative overflow-hidden rounded-3xl bg-ink px-6 py-10 text-white shadow-lg shadow-ink/10 sm:px-10 sm:py-12 lg:px-14">
        <div class="relative max-w-4xl">
            <p class="mb-5 text-xs font-bold tracking-[0.16em] text-emerald-200 uppercase">Проверка бренда в ИИ и поиске</p>
            <h1 class="text-3xl font-bold leading-tight sm:text-4xl lg:text-5xl">Узнайте, где виден ваш бренд</h1>
            <p class="mt-6 max-w-3xl text-sm leading-7 text-emerald-50/90 sm:text-base">Проверьте ответы выбранных моделей и попадание сайта в первую десятку Яндекса. Результаты сохраняются в истории.</p>
        </div>
    </section>

    <section class="mt-8 overflow-hidden rounded-3xl border border-line bg-white shadow-sm" aria-labelledby="check-title">
        <form onsubmit={submit} novalidate class="space-y-7 px-6 py-7 sm:px-8">
            <div class="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]">
                <div>
                    <label for="prompts" class="mb-2 block text-sm font-semibold text-ink">
                        Вопросы клиентов
                        <span class="text-rose-600">*</span>
                    </label>
                    <textarea id="prompts" class="block min-h-56 w-full resize-y rounded-xl border border-line bg-canvas/50 px-4 py-3 text-sm leading-6 text-ink outline-none focus:border-accent" bind:value={promptsText}></textarea>
                    <p class="mt-2 text-xs text-muted">
                        Каждый вопрос — с новой строки. До {data.form?.limits.max_prompts ?? 20} вопросов.
                    </p>
                </div>

                <div class="space-y-5">
                    <div>
                        <label for="brand" class="mb-2 block text-sm font-semibold text-ink">
                            Название бренда
                            <span class="font-normal text-muted">для проверки моделей</span>
                        </label>
                        <input
                            id="brand"
                            class="block w-full rounded-xl border border-line bg-canvas/50 px-4 py-3 text-sm text-ink outline-none focus:border-accent"
                            type="text"
                            maxlength={data.form?.limits.max_brand_length}
                            bind:value={brand}
                        />
                        <p class="mt-2 text-xs text-muted">Ищем название в ответах моделей.</p>
                    </div>

                    <div>
                        <label for="domain" class="mb-2 block text-sm font-semibold text-ink">
                            Сайт
                        </label>
                        <input
                            id="domain"
                            class="block w-full rounded-xl border border-line bg-canvas/50 px-4 py-3 text-sm text-ink outline-none focus:border-accent"
                            type="text"
                            maxlength={data.form?.limits.max_domain_length}
                            bind:value={domain}
                        />
                        <p class="mt-2 text-xs text-muted">Совпадение ищется по хосту и его поддоменам.</p>
                    </div>
                </div>
            </div>

            <fieldset class="border-t border-line pt-6">
                <legend class="mb-3 text-sm font-semibold text-ink">Модели для проверки</legend>
                <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {#each data.providers as provider (provider.id)}
                        <label class:opacity-60={!provider.configured} class="flex cursor-pointer items-start gap-3 rounded-xl border border-line bg-white px-4 py-3 hover:border-accent/50">
                            <input
                                type="checkbox"
                                class="mt-1 size-4 accent-accent"
                                checked={selected.includes(provider.id)}
                                disabled={!provider.configured}
                                onchange={() => toggleProvider(provider.id)}
                            />
                            <span class="min-w-0">
                                <span class="block font-semibold text-ink">{provider.name}</span>
                                <span class="mt-0.5 block truncate text-xs text-muted">
                                    {provider.configured ? provider.model : provider.status_label}
                                </span>
                            </span>
                        </label>
                    {/each}
                </div>
            </fieldset>

            <fieldset class="border-t border-line pt-6" aria-labelledby="regions-legend">
                <legend id="regions-legend" class="mb-3 text-sm font-semibold text-ink">
                    Регионы для поиска в Яндексе
                </legend>
                <p class="mb-4 max-w-3xl text-xs leading-5 text-muted">
                    Добавьте до пяти регионов. Поиск проверит первую десятку по каждому вопросу и может занять несколько часов.
                </p>

                {#if data.searchRegionError}
                    <p role="alert" class="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                        {data.searchRegionError}. Проверка моделей работает без него.
                    </p>
                {/if}
                <div class="space-y-3">
                    {#each regionRows as value, index (index)}
                        <div class="flex items-center gap-3" data-region-row>
                            <select
                                id={`engine-${index}`}
                                aria-label={`Поисковая система для региона ${index + 1}`}
                                class="min-h-12 w-36 max-w-sm rounded-xl border border-line bg-canvas/50 px-4 py-3 text-sm text-ink outline-none focus:border-accent"
                                bind:value={regionEngines[index]}
                            >
                                <option value="yandex">Яндекс</option>
                            </select>

                            <select
                                id={`region-${index}`}
                                aria-label={`Регион ${index + 1}`}
                                class="min-h-12 w-48 max-w-sm rounded-xl border border-line bg-canvas/50 px-4 py-3 text-sm text-ink outline-none focus:border-accent"
                                bind:value={regionRows[index]}
                            >
                                <option value="">Выберите регион</option>
                                {#each catalog as region (region.id)}
                                    <option value={region.id} disabled={regionTaken(region.id, index)}>
                                        {region.name}
                                    </option>
                                {/each}
                            </select>

                            <button
                                type="button"
                                onclick={() => removeRegion(index)}
                                aria-label={`Удалить регион ${index + 1}`}
                                class="grid size-12 shrink-0 place-items-center rounded-xl border border-line bg-white text-lg text-muted hover:text-rose-700"
                            >
                                ×
                            </button>
                        </div>
                    {/each}
                </div>

                <button
                    type="button"
                    onclick={addRegion}
                    disabled={regionRows.length >= MAX_REGIONS || !catalog.length}
                    class="mt-4 inline-flex min-h-11 items-center rounded-xl border border-line bg-white px-4 py-2 text-sm font-semibold disabled:opacity-50"
                >
                    ＋ Добавить регион
                </button>

                {#if chosenRegions.length > 0}
                    <p class="mt-3 text-xs text-muted">
                        <span class="font-semibold text-ink" data-request-count>
                            {requestCountLabel(yandexRequests)}
                        </span>
                        — по одному отложенному запросу на пару «вопрос × регион».
                    </p>
                {/if}
            </fieldset>

            {#if error}
                <p role="alert" class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
                    {error}
                </p>
            {/if}

            <div class="flex flex-wrap items-center justify-between gap-4 border-t border-line pt-6">
                <p class="max-w-xl text-xs leading-5 text-muted">
                    Ответы и выдача отражают момент проверки. Прогон сохранится в истории.
                </p>
                <button
                    type="submit"
                    disabled={loading || pendingRunId !== null || !data.form}
                    class="inline-flex min-h-12 items-center gap-3 rounded-xl bg-accent px-6 py-3 text-sm font-bold text-white disabled:opacity-60"
                >
                    {loading ? 'Запускаем…' : pendingRunId ? 'Проверка выполняется' : 'Проверить бренд'}
                    <span aria-hidden="true">↗</span>
                </button>
            </div>
        </form>
    </section>

    {#if snapshot}
        <RunResults {snapshot} />
    {:else}
        <section class="mt-8 rounded-3xl border border-dashed border-line bg-white px-6 py-14 text-center shadow-sm">
            <h2 class="text-xl font-bold">Пока нет проверки</h2>
            <p class="mt-2 text-sm text-muted">Запустите проверку или откройте сохранённый прогон из истории.</p>
        </section>
    {/if}

    {#if historyError}
        <p role="alert" class="mt-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {historyError}
        </p>
    {/if}

    <RunHistory items={history} {nextCursor} onView={(id) => void loadRun(id)} onDelete={(id) => void deleteRun(id)} onMore={() => void loadMore()} loading={historyLoading} />

    <aside class="mt-8 rounded-2xl border border-line bg-accent-soft px-6 py-5 text-sm leading-6 text-ink">
        <strong>Как читать результат</strong>
        <p class="mt-2 text-muted">Поиск проверяет только первую десятку органических результатов в выбранных регионах. Ошибка или прерванный запрос не означает, что сайта нет в выдаче.</p>
    </aside>
</main>