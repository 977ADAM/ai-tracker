<script lang="ts">
  import type { Project } from '$lib/project-types';
  let {
    project,
    view = $bindable('mentions'),
    ready = false,
    active = false,
    busy = false,
    onStart,
    onDelete,
    onRename,
  }: {
    project: Pick<Project, 'id' | 'name' | 'brand'>;
    view?: 'mentions' | 'sources';
    ready?: boolean;
    active?: boolean;
    busy?: boolean;
    onStart: () => void;
    onDelete: () => void;
    onRename: (name: string) => Promise<void>;
  } = $props();
  let editing = $state(false),
    name = $state(''),
    error = $state('');
  async function rename(e: SubmitEvent) {
    e.preventDefault();
    error = '';
    if (!name.trim()) {
      error = 'Укажите название проекта';
      return;
    }
    try {
      await onRename(name.trim());
      editing = false;
    } catch (e) {
      error = e instanceof Error ? e.message : 'Не удалось изменить название';
    }
  }
  function edit() {
    name = project.name;
    editing = true;
    error = '';
  }
</script>

<nav
  aria-label="Хлебные крошки"
  class="mb-6 flex min-w-0 items-center gap-3 rounded-lg bg-slate-50 px-3 py-3 text-xs text-slate-400"
>
  <a href="/" aria-label="Главная" class="hover:text-lime-600">⌂</a><span aria-hidden="true">›</span
  ><a href="/" aria-label="Проекты" class="shrink-0 hover:text-lime-600">Трекер ИИ</a><span
    aria-hidden="true">›</span
  ><span aria-current="page" class="truncate text-slate-600">{project.name}</span>
</nav>
<header
  class="flex flex-wrap items-start justify-between gap-5 rounded-xl bg-white px-4 py-5 sm:px-6"
>
  <div class="min-w-0 flex-1">
    {#if editing}<form onsubmit={rename} class="flex flex-wrap items-center gap-2">
        <input
          aria-label="Название проекта"
          bind:value={name}
          maxlength="100"
          required
          class="min-w-40 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-base"
        /><button
          disabled={busy}
          class="rounded-lg bg-lime-600 px-3 py-2 text-xs font-medium text-white">Сохранить</button
        ><button type="button" onclick={() => (editing = false)} class="text-xs text-slate-400"
          >Отмена</button
        >
      </form>
      {#if error}<p role="alert" class="mt-2 text-xs text-red-600">{error}</p>{/if}{:else}<div
        class="flex min-w-0 items-center gap-2"
      >
        <h1
          class="truncate text-2xl font-medium tracking-tight text-slate-600"
          title={project.name}
        >
          {project.name}
        </h1>
        <button
          aria-label="Изменить название проекта"
          disabled={busy}
          onclick={edit}
          class="grid size-7 shrink-0 place-items-center text-lg text-slate-400 hover:text-lime-600"
          >✎</button
        >
      </div>{/if}
    <p class="mt-2 text-sm text-slate-500">Бренд: <strong>«{project.brand}»</strong></p>
  </div>
  <div class="flex flex-wrap items-center gap-2">
    <button
      aria-pressed={view === 'mentions'}
      onclick={() => (view = 'mentions')}
      class={`inline-flex items-center gap-2 rounded-lg border border-lime-600 px-4 py-2.5 text-xs font-medium text-lime-600 ${view === 'mentions' ? 'bg-lime-50' : 'bg-white'}`}
      ><span aria-hidden="true">▦</span>Все упоминания</button
    ><button
      aria-pressed={view === 'sources'}
      onclick={() => (view = 'sources')}
      class={`inline-flex items-center gap-2 rounded-lg border border-lime-600 px-4 py-2.5 text-xs font-medium text-lime-600 ${view === 'sources' ? 'bg-lime-50' : 'bg-white'}`}
      ><span aria-hidden="true">↗</span>Источники упоминаний</button
    ><button
      aria-label="Обновить"
      title="Запустить новый замер"
      disabled={busy || active || !ready}
      onclick={onStart}
      class="inline-flex items-center gap-2 rounded-lg bg-lime-600 px-5 py-2.5 text-xs font-semibold text-white disabled:opacity-40"
      ><span aria-hidden="true">↻</span>Обновить</button
    ><a
      href={`/projects/${project.id}/settings`}
      class="inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-xs text-slate-500 hover:bg-slate-50"
      ><span aria-hidden="true">☷</span>Настройки</a
    ><button
      aria-label="Удалить проект"
      disabled={busy || active}
      onclick={onDelete}
      class="grid size-9 place-items-center rounded-lg text-red-400 hover:bg-red-50 disabled:opacity-40"
      ><svg
        viewBox="0 0 20 20"
        fill="none"
        stroke="currentColor"
        stroke-width="1.4"
        class="size-4"
        aria-hidden="true"><path d="M4 5h12M7 5V3h6v2M6 5l1 12h6l1-12M9 8v6m3-6v6" /></svg
      ></button
    >
  </div>
</header>
