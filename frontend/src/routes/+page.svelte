<script lang="ts">
  import { notify } from '$lib/notifications';
  import { onMount, untrack } from 'svelte';
  import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
  import ProjectCard from '$lib/components/ProjectCard.svelte';
  import { projectRequest } from '$lib/project-client';
  import type { ProjectSummary, Page } from '$lib/project-types';
  let { data }: { data: { projects: Page<ProjectSummary>; projectsError: string } } = $props();
  let projects = $state<ProjectSummary[]>(untrack(() => data.projects.items));
  let cursor = $state<string | null>(untrack(() => data.projects.cursor));
  let error = $state(untrack(() => data.projectsError));
  let busy = $state<string | null>(null);
  let deleteId = $state<string | null>(null);
  let pollingError = $state('');
  let disposed = false;
  $effect(() => {
    projects = data.projects.items;
    cursor = data.projects.cursor;
    error = data.projectsError;
  });
  async function refresh() {
    try {
      const target = projects.length;
      const page = await projectRequest<Page<ProjectSummary>>('/api/projects');
      while (page.cursor && page.items.length < target) {
        const next = await projectRequest<Page<ProjectSummary>>(
          '/api/projects?cursor=' + encodeURIComponent(page.cursor),
        );
        page.items.push(...next.items);
        page.cursor = next.cursor;
      }
      if (!disposed) {
        projects = page.items;
        cursor = page.cursor;
        pollingError = '';
      }
    } catch (e) {
      if (!disposed) pollingError = String(e instanceof Error ? e.message : e);
    }
  }
  async function start(p: ProjectSummary) {
    busy = p.id;
    error = '';
    try {
      await projectRequest(`/api/projects/${p.id}/measurements`, 'POST');
      notify('Замер запущен');
      await refresh();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Ошибка запуска';
    } finally {
      busy = null;
    }
  }
  async function remove() {
    if (!deleteId) return;
    busy = deleteId;
    try {
      await projectRequest(`/api/projects/${deleteId}`, 'DELETE');
      notify('Проект удалён');
      deleteId = null;
      await refresh();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Ошибка удаления';
    } finally {
      busy = null;
    }
  }
  async function more() {
    if (!cursor) return;
    busy = 'more';
    try {
      const page = await projectRequest<Page<ProjectSummary>>(
        '/api/projects?cursor=' + encodeURIComponent(cursor),
      );
      projects = [...projects, ...page.items];
      cursor = page.cursor;
    } catch (e) {
      error = e instanceof Error ? e.message : 'Ошибка загрузки';
    } finally {
      busy = null;
    }
  }
  onMount(() => {
    const timer = setInterval(() => {
      if (projects.some((p) => p.active_measurement)) void refresh();
    }, 5000);
    return () => {
      disposed = true;
      clearInterval(timer);
    };
  });
</script>

<svelte:head><title>Проекты · ИИ-трекинг</title></svelte:head>
<main class="mx-auto max-w-[1600px] px-4 py-8 sm:px-6 lg:px-8">
  <div class="mb-8 flex flex-wrap items-center justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold tracking-tight">Проекты</h1>
      <p class="mt-2 text-sm text-muted">Следите за тем, как модели упоминают ваш бренд.</p>
    </div>
    {#if projects.length || error}
      <a
        href="/projects/new"
        class="rounded-xl bg-accent px-5 py-3 text-sm font-semibold text-white hover:bg-accent-dark"
        >+ Создать проект</a
      >
    {/if}
  </div>
  {#if error}<p role="alert" class="mb-5 rounded-xl bg-red-50 p-4 text-sm text-red-700">
      {error}
    </p>{/if}
  {#if pollingError}<p role="status" class="mb-5 text-sm text-red-700">{pollingError}</p>{/if}
  {#if projects.length}<div
      class="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"
    >
      {#each projects as p (p.id)}<ProjectCard
          project={p}
          busy={busy === p.id}
          onStart={() => start(p)}
          onDelete={() => (deleteId = p.id)}
        />{/each}
    </div>{:else if !error}<div
      class="rounded-2xl border border-dashed border-line bg-white px-6 py-20 text-center"
    >
      <h2 class="text-xl font-semibold">Узнайте, видят ли нейросети ваш бренд</h2>
      <ol class="mx-auto mt-8 grid max-w-3xl gap-6 text-left sm:grid-cols-3 sm:gap-8">
        <li>
          <span
            class="mb-3 grid size-8 place-items-center rounded-full bg-accent-soft text-sm font-semibold text-accent"
            aria-hidden="true">1</span
          >
          <h3 class="text-sm font-semibold text-ink">Добавьте бренд и сайт</h3>
          <p class="mt-2 text-sm leading-5 text-muted">Укажите, чей бренд нужно отслеживать.</p>
        </li>
        <li>
          <span
            class="mb-3 grid size-8 place-items-center rounded-full bg-accent-soft text-sm font-semibold text-accent"
            aria-hidden="true">2</span
          >
          <h3 class="text-sm font-semibold text-ink">Подготовьте запросы</h3>
          <p class="mt-2 text-sm leading-5 text-muted">
            Получите предложения автоматически или добавьте свои запросы.
          </p>
        </li>
        <li>
          <span
            class="mb-3 grid size-8 place-items-center rounded-full bg-accent-soft text-sm font-semibold text-accent"
            aria-hidden="true">3</span
          >
          <h3 class="text-sm font-semibold text-ink">Получите первый отчёт</h3>
          <p class="mt-2 text-sm leading-5 text-muted">
            Выберите модели и запустите замер видимости и тональности.
          </p>
        </li>
      </ol>
      <a
        href="/projects/new"
        class="mt-6 inline-flex rounded-xl bg-accent px-5 py-3 text-sm font-semibold text-white"
        >Создать проект</a
      >
    </div>{/if}
  {#if cursor}<button
      class="mt-6 rounded-lg border border-line bg-white px-5 py-2 text-sm"
      disabled={busy === 'more'}
      onclick={more}>Показать ещё</button
    >{/if}
  {#if deleteId}<ConfirmDialog
      title="Удалить проект?"
      description="Проект и все его замеры будут удалены."
      busy={!!busy}
      onConfirm={remove}
      onClose={() => (deleteId = null)}
    />{/if}
</main>
