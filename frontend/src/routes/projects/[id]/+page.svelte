<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import type { Project, Measurement, ModelRow, SearchRow, Page } from '$lib/project-types';
  import { projectRequest, measurementLabels, percent } from '$lib/project-client';
  import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
  import MeasurementReport from '$lib/components/MeasurementReport.svelte';
  let { data }: { data: { project: Project; history: Page<Measurement> } } = $props();
  let project = $state(untrack(() => data.project));
  let history = $state<Measurement[]>(untrack(() => data.history.items));
  let historyCursor = $state<string | null>(untrack(() => data.history.cursor));
  let selected = $state<Measurement | null>(
    untrack(
      () => data.history.items.find((r) => r.status === 'running') ?? data.history.items[0] ?? null,
    ),
  );
  let modelRows = $state<ModelRow[]>([]),
    searchRows = $state<SearchRow[]>([]);
  let modelCursor = $state<string | null>(null),
    searchCursor = $state<string | null>(null);
  let loading = $state(false),
    busy = $state(false),
    error = $state('');
  let deleteRun = $state<string | null>(null);
  let epoch = 0,
    disposed = false;
  let active = $derived(history.find((r) => r.status === 'running'));
  let ready = $derived(project.queries.length > 0 && project.connection_ids.length > 0);
  const rowKey = (r: ModelRow) => `${r.query_index}:${r.connection_id}`;
  async function rows(m: Measurement, more: 'model' | 'search' | null = null) {
    const ticket = epoch;
    const id = m.id;
    loading = true;
    try {
      if (more !== 'search') {
        const page = await projectRequest<Page<ModelRow>>(
          `/api/measurements/${id}/rows?kind=model&limit=100${more === 'model' && modelCursor ? '&cursor=' + encodeURIComponent(modelCursor) : ''}`,
        );
        if (ticket !== epoch || disposed) return;
        const map = new Map(modelRows.map((r) => [rowKey(r), r]));
        for (const r of page.items) map.set(rowKey(r), r);
        modelRows = [...map.values()];
        if (more === 'model' || modelRows.length <= 100) modelCursor = page.cursor;
      }
      if (m.snapshot.project.yandex_enabled && more !== 'model') {
        const page = await projectRequest<Page<SearchRow>>(
          `/api/measurements/${id}/rows?kind=search${more === 'search' && searchCursor ? '&cursor=' + encodeURIComponent(searchCursor) : ''}`,
        );
        if (ticket !== epoch || disposed) return;
        const map = new Map(searchRows.map((r) => [r.query_index, r]));
        for (const r of page.items) map.set(r.query_index, r);
        searchRows = [...map.values()];
        searchCursor = page.cursor;
      }
    } catch (e) {
      if (ticket === epoch && !disposed)
        error = e instanceof Error ? e.message : 'Не удалось загрузить ответы';
    } finally {
      if (ticket === epoch && !disposed) loading = false;
    }
  }
  async function choose(m: Measurement) {
    epoch++;
    selected = m;
    modelRows = [];
    searchRows = [];
    modelCursor = null;
    searchCursor = null;
    error = '';
    await rows(m);
  }
  async function refreshHistory() {
    const ticket = epoch;
    const page = await projectRequest<Page<Measurement>>(
      `/api/projects/${project.id}/measurements`,
    );
    if (disposed || ticket !== epoch) return;
    const map = new Map(history.map((r) => [r.id, r]));
    for (const r of page.items) map.set(r.id, r);
    history = [...map.values()].sort((a, b) => b.created_at.localeCompare(a.created_at));
    if (history.length <= 20) historyCursor = page.cursor;
  }
  async function start() {
    busy = true;
    error = '';
    try {
      const r = await projectRequest<{ id: string }>(
        `/api/projects/${project.id}/measurements`,
        'POST',
      );
      await refreshHistory();
      const m = await projectRequest<Measurement>(`/api/measurements/${r.id}`);
      await choose(m);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Ошибка запуска';
    } finally {
      busy = false;
    }
  }
  async function cancel() {
    if (!active) return;
    busy = true;
    try {
      const m = await projectRequest<Measurement>(`/api/measurements/${active.id}/cancel`, 'POST');
      if (selected?.id === m.id) selected = m;
      await refreshHistory();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Ошибка отмены';
    } finally {
      busy = false;
    }
  }
  async function remove() {
    if (!deleteRun) return;
    busy = true;
    try {
      await projectRequest(`/api/measurements/${deleteRun}`, 'DELETE');
      history = history.filter((r) => r.id !== deleteRun);
      if (selected?.id === deleteRun) {
        selected = null;
        modelRows = [];
        searchRows = [];
      }
      deleteRun = null;
      await refreshHistory();
      if (!selected && history[0]) await choose(history[0]);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Ошибка удаления';
    } finally {
      busy = false;
    }
  }
  async function moreHistory() {
    if (!historyCursor) return;
    const page = await projectRequest<Page<Measurement>>(
      `/api/projects/${project.id}/measurements?cursor=${encodeURIComponent(historyCursor)}`,
    );
    history = [...history, ...page.items];
    historyCursor = page.cursor;
  }
  $effect(() => {
    if (data.project.id !== project.id || data.project.revision !== project.revision) {
      epoch++;
      project = data.project;
      history = data.history.items;
      historyCursor = data.history.cursor;
      selected =
        data.history.items.find((r) => r.status === 'running') ?? data.history.items[0] ?? null;
      modelRows = [];
      searchRows = [];
      if (selected) void rows(selected);
    }
  });
  onMount(() => {
    if (selected) void rows(selected);
    let pending = false;
    const timer = setInterval(async () => {
      if (pending || !active) return;
      pending = true;
      const ticket = epoch;
      try {
        const id = active.id;
        const m = await projectRequest<Measurement>(`/api/measurements/${id}`);
        if (disposed || ticket !== epoch) return;
        history = history.map((r) => (r.id === m.id ? m : r));
        if (selected?.id === m.id) {
          selected = m;
          await rows(m);
        }
        if (m.status !== 'running') await refreshHistory();
      } catch (e) {
        if (!disposed) error = e instanceof Error ? e.message : 'Ошибка обновления';
      } finally {
        pending = false;
      }
    }, 5000);
    return () => {
      disposed = true;
      epoch++;
      clearInterval(timer);
    };
  });
</script>

<svelte:head><title>{project.name} · ИИ-трекинг</title></svelte:head>
<main class="mx-auto max-w-7xl px-4 py-8 sm:px-6">
  <a href="/" class="text-sm text-muted">← Проекты</a>
  <div class="mt-4 flex flex-wrap items-start justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold">{project.name}</h1>
      <p class="mt-2 text-sm text-muted">
        Бренд: {project.brand} ·
        <a href={project.site_url} target="_blank" rel="noopener noreferrer">{project.site_url}</a>
      </p>
    </div>
    <div class="flex gap-3">
      <a
        href={`/projects/${project.id}/setup`}
        class="rounded-xl border border-line bg-white px-4 py-3 text-sm font-medium"
        >Мастер настройки</a
      >
      <a
        href={`/projects/${project.id}/settings`}
        class="rounded-xl border border-line bg-white px-4 py-3 text-sm font-medium"
        >Настройки проекта</a
      ><button
        disabled={busy || !!active || !ready}
        onclick={start}
        class="rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-white disabled:opacity-40"
        >Запустить замер</button
      >
    </div>
  </div>
  <p class="mt-4 text-xs text-muted">
    {project.queries.length} запросов × {project.connection_ids.length} моделей = {project.queries
      .length * project.connection_ids.length} ответов; до {project.queries.length *
      project.connection_ids.length} оценок тональности{project.yandex_enabled
      ? `; ${project.queries.length} поисков Яндекса`
      : ''}.
  </p>
  {#if !ready}<div class="mt-6 rounded-xl border border-line bg-white p-6">
      <h2 class="font-semibold">Проект создан</h2>
      <p class="mt-2 text-sm text-muted">
        Добавьте запросы и выберите модели внутри проекта, чтобы запустить первый замер.
      </p>
      <a
        href={`/projects/${project.id}/setup`}
        class="mt-4 inline-flex rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white"
        >Продолжить настройку</a
      >
    </div>{/if}
  {#if error}<p role="alert" class="mt-5 rounded-xl bg-red-50 p-4 text-sm text-red-700">
      {error}
    </p>{/if}
  {#if active}<div
      class="mt-6 flex flex-wrap items-center justify-between gap-4 rounded-xl bg-accent-soft p-4"
    >
      <div role="status">
        <strong class="text-sm">Замер выполняется</strong>
        <p class="mt-1 text-xs">
          Ответы: {active.progress.model_done}/{active.progress.model_total} · Тональность: {active
            .progress.sentiment_done}/{active.progress.sentiment_total} · Яндекс: {active.progress
            .search_done}/{active.progress.search_total}
        </p>
      </div>
      <button
        disabled={busy}
        class="rounded-lg border border-line bg-white px-4 py-2 text-sm"
        onclick={cancel}>Отменить замер</button
      >
    </div>{/if}
  <div class="mt-8 grid items-start gap-6 lg:grid-cols-[240px_minmax(0,1fr)]">
    <aside class="rounded-xl border border-line bg-white p-4">
      <h2 class="font-semibold">История замеров</h2>
      <div class="mt-4 space-y-2">
        {#each history as m (m)}<div
            class="rounded-lg border p-3"
            class:border-accent={selected?.id === m.id}
            class:border-line={selected?.id !== m.id}
          >
            <button class="w-full text-left" onclick={() => choose(m)}
              ><span class="block text-xs text-muted"
                >{m.created_at.slice(0, 19).replace('T', ' ')} UTC</span
              ><span class="mt-1 block text-sm font-medium"
                >{measurementLabels[m.status] ?? m.status} · {percent(
                  m.aggregates.visibility,
                )}</span
              ></button
            >{#if m.status !== 'running'}<button
                aria-label="Удалить замер"
                class="mt-2 text-xs text-red-500"
                onclick={() => (deleteRun = m.id)}>Удалить</button
              >{/if}
          </div>{/each}{#if !history.length}<p class="text-sm text-muted">
            Замеров пока нет.
          </p>{/if}{#if historyCursor}<button
            class="text-sm text-accent"
            onclick={() => moreHistory().catch((e) => (error = e.message))}>Показать ещё</button
          >{/if}
      </div>
    </aside>
    <div class="min-w-0">
      {#if selected}<div class="mb-4 flex flex-wrap justify-between gap-2">
          <h2 class="text-lg font-semibold">
            {measurementLabels[selected.status] ?? selected.status}
          </h2>
          <p class="text-xs text-muted">
            Снимок: {selected.snapshot.project.brand} · {selected.snapshot.project.queries.length} запросов
          </p>
        </div>
        <MeasurementReport
          snapshot={selected}
          {modelRows}
          {searchRows}
          {modelCursor}
          {searchCursor}
          {loading}
          onMore={(kind) => selected && rows(selected, kind)}
        />{:else}<div
          class="rounded-xl border border-dashed border-line p-10 text-center text-sm text-muted"
        >
          Результат появится здесь после запуска замера.
        </div>{/if}
    </div>
  </div>
  {#if deleteRun}<ConfirmDialog
      title="Удалить замер?"
      description="Ответы и отчёт этого замера будут удалены."
      {busy}
      onConfirm={remove}
      onClose={() => (deleteRun = null)}
    />{/if}
</main>
