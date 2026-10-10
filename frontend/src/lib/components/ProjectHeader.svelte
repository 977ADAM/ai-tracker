<script lang="ts">
  import type { Project } from '$lib/project-types';
  let {
    project,
    view = $bindable('mentions'),
    ready = false,
    active = false,
    busy = false,
    onStart,
    onRename,
  }: {
    project: Pick<Project, 'id' | 'name' | 'brand'>;
    view?: 'mentions' | 'sources';
    ready?: boolean;
    active?: boolean;
    busy?: boolean;
    onStart: () => void;
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
  class="mb-6 flex min-w-0 items-center gap-3 rounded-lg bg-slate-50 px-3 py-3 text-xs text-slate-500"
>
  <a href="/" aria-label="Главная" class="hover:text-accent">⌂</a><span aria-hidden="true">›</span
  ><a href="/" aria-label="Проекты" class="shrink-0 hover:text-accent">Трекер ИИ</a><span
    aria-hidden="true">›</span
  ><span aria-current="page" class="truncate text-slate-600">{project.name}</span>
</nav>
<header class="rounded-2xl border border-line bg-white px-4 py-5 sm:px-6">
  <div class="flex flex-wrap items-start justify-between gap-4">
    <div class="min-w-0 flex-[1_1_280px]">
      {#if editing}<form onsubmit={rename} class="flex flex-wrap items-center gap-2">
          <input
            aria-label="Название проекта"
            bind:value={name}
            maxlength="100"
            required
            class="min-w-40 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-base"
          /><button
            disabled={busy}
            class="rounded-lg bg-accent px-3 py-2 text-xs font-medium text-white">Сохранить</button
          ><button type="button" onclick={() => (editing = false)} class="text-xs text-slate-500"
            >Отмена</button
          >
        </form>
        {#if error}<p role="alert" class="mt-2 text-xs text-red-600">{error}</p>{/if}{:else}<div
          class="flex min-w-0 items-start gap-2"
        >
          <h1
            class="min-w-0 text-2xl font-semibold tracking-tight break-words text-ink"
            title={project.name}
          >
            {project.name}
          </h1>
          <button
            aria-label="Изменить название проекта"
            disabled={busy}
            onclick={edit}
            class="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg text-lg text-slate-500 hover:bg-accent-soft hover:text-accent focus-visible:outline-2 focus-visible:outline-accent"
            >✎</button
          >
        </div>{/if}
      <p class="mt-2 text-sm text-slate-500">Бренд: <strong>«{project.brand}»</strong></p>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <button
        aria-label="Запустить замер"
        title="Запустить новый замер"
        disabled={busy || active || !ready}
        onclick={onStart}
        class="inline-flex items-center gap-2 rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-accent-dark focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
        ><span aria-hidden="true">↻</span>Запустить замер</button
      ><a
        href={`/projects/${project.id}/settings`}
        class="inline-flex items-center gap-2 rounded-xl border border-line px-4 py-2.5 text-sm text-muted hover:bg-canvas focus-visible:outline-2 focus-visible:outline-accent"
        ><span aria-hidden="true">☷</span>Настройки</a
      >
    </div>
  </div>
  <div
    role="group"
    aria-label="Разделы отчёта"
    class="mt-5 flex flex-wrap items-center gap-2 border-t border-line pt-4"
  >
    <button
      aria-pressed={view === 'mentions'}
      onclick={() => (view = 'mentions')}
      class={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition focus-visible:outline-2 focus-visible:outline-accent ${view === 'mentions' ? 'bg-accent-soft text-accent' : 'text-muted hover:bg-canvas'}`}
      ><span aria-hidden="true">▦</span>Все упоминания</button
    ><button
      aria-pressed={view === 'sources'}
      onclick={() => (view = 'sources')}
      class={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition focus-visible:outline-2 focus-visible:outline-accent ${view === 'sources' ? 'bg-accent-soft text-accent' : 'text-muted hover:bg-canvas'}`}
      ><span aria-hidden="true">↗</span>Источники упоминаний</button
    >
  </div>
</header>
