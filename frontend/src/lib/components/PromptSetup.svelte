<script lang="ts">
  import { onDestroy } from 'svelte';
  import type { ProjectQuery } from '$lib/project-types';
  import { parseQueryList, readFileBase64 } from '$lib/project-setup';
  import { projectRequest } from '$lib/project-client';
  let {
    queries = $bindable([]),
    valid = $bindable(true),
    generating = false,
    uploading = $bindable(false),
    onGenerate,
  }: {
    queries: ProjectQuery[];
    valid?: boolean;
    generating?: boolean;
    uploading?: boolean;
    onGenerate: (count: number) => void;
  } = $props();
  let tab = $state<'generation' | 'list'>('generation'),
    text = $state(''),
    error = $state(''),
    newGroup = $state(''),
    extras = $state<string[]>([]),
    menu = $state(false);
  let metadata = $state<ProjectQuery[]>([]);
  let disposed = false;
  onDestroy(() => (disposed = true));
  $effect(() => {
    if (tab === 'generation') valid = true;
  });
  let groups = $derived([
    ...new Set([...extras, ...queries.map((q) => q.group).filter((g): g is string => !!g)]),
  ]);
  async function upload(event: Event) {
    const input = event.target as HTMLInputElement,
      file = input.files?.[0];
    input.value = '';
    if (!file) return;
    uploading = true;
    error = '';
    try {
      const result = await projectRequest<{ queries: ProjectQuery[] }>(
        '/api/projects/import-prompts',
        'POST',
        { filename: file.name, content: await readFileBase64(file) },
      );
      if (disposed) return;
      queries = result.queries;
      metadata = queries.map((q) => ({ ...q }));
      valid = true;
      text = queries.map((q) => q.text).join('\n');
    } catch (e) {
      error = e instanceof Error ? e.message : 'Не удалось импортировать файл';
    } finally {
      uploading = false;
    }
  }
  function switchTab(value: 'generation' | 'list') {
    error = '';
    if (value === 'list') {
      text = queries.map((q) => q.text).join('\n');
      metadata = queries.map((q) => ({ ...q }));
    } else if (tab === 'list') {
      try {
        queries = parseQueryList(text, metadata);
      } catch (e) {
        error = e instanceof Error ? e.message : 'Некорректный список';
        return;
      }
    }
    tab = value;
  }
  function editList() {
    try {
      queries = parseQueryList(text, metadata);
      valid = true;
      error = '';
    } catch (e) {
      valid = false;
      error = e instanceof Error ? e.message : 'Некорректный список';
    }
  }
  function addGroup() {
    const name = newGroup.trim();
    if (!name) return;
    extras = [...extras, name];
    newGroup = '';
    if (queries.length && queries[queries.length - 1].group == null)
      queries[queries.length - 1].group = name;
  }
  function add() {
    queries = [...queries, { text: '', category: null, group: null }];
  }
  function generate(count: number) {
    menu = false;
    error = '';
    onGenerate(count);
  }
</script>

<p class="mt-4 text-sm leading-relaxed text-slate-500">
  Введите или сгенерируйте автоматически промпты для проверки упоминаний и цитируемости.<br
  />Распределяйте их в группы по продуктам или сценариям.
</p>
<div
  role="tablist"
  aria-label="Способ добавления промптов"
  class="mt-8 flex border-b-2 border-slate-200"
>
  <button
    role="tab"
    aria-selected={tab === 'generation'}
    onclick={() => switchTab('generation')}
    class={`border-b-2 px-5 py-3 text-sm font-semibold ${tab === 'generation' ? 'border-lime-600 text-lime-600' : 'border-transparent text-slate-500'}`}
    >Генерация</button
  ><button
    role="tab"
    aria-selected={tab === 'list'}
    onclick={() => switchTab('list')}
    class={`border-b-2 px-5 py-3 text-sm font-semibold ${tab === 'list' ? 'border-lime-600 text-lime-600' : 'border-transparent text-slate-500'}`}
    >Из списка</button
  >
</div>
{#if error}<p role="alert" class="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">
    {error}
  </p>{/if}
{#if tab === 'generation'}
  <div class="mt-5 space-y-4">
    {#each queries as q, i (q)}<div>
        <label class="block text-sm text-slate-400"
          ><span class="flex justify-between"
            ><span>Промпт {i + 1}</span><span class="text-xs">{q.text.length} / 400</span></span
          ><textarea
            aria-label={`Промпт ${i + 1}`}
            bind:value={q.text}
            rows="3"
            maxlength="400"
            class="mt-2 w-full rounded-lg border border-slate-300 px-3 py-3 text-sm text-slate-700 outline-none focus:border-lime-500"
            placeholder="Введите текст промпта или сгенерируйте по сайту"></textarea></label
        >
        <div class="flex items-center gap-2 rounded-b-lg bg-slate-100 p-2 text-sm text-slate-500">
          <span>Группы:</span><select
            aria-label={`Группа промпта ${i + 1}`}
            bind:value={q.group}
            class="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2"
            ><option value={null}>Выберите группу</option>{#each groups as group (group)}<option
                value={group}>{group}</option
              >{/each}</select
          ><button
            aria-label={`Удалить промпт ${i + 1}`}
            class="size-8 text-xl text-slate-400"
            onclick={() => (queries = queries.filter((_, n) => n !== i))}>×</button
          >
        </div>
      </div>{/each}
  </div>
  <div class="mt-4 flex flex-wrap items-center gap-2">
    <input
      aria-label="Новая группа промптов"
      bind:value={newGroup}
      maxlength="100"
      class="min-w-32 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
      placeholder="Новая группа: продукт или сценарий"
    /><button
      disabled={!newGroup.trim()}
      class="rounded-lg border border-slate-300 px-3 py-2 text-xs text-slate-500"
      onclick={addGroup}>Добавить группу</button
    >
  </div>
  <div class="mt-6 flex flex-wrap items-center justify-between gap-3">
    <button
      disabled={queries.length >= 20 || generating}
      class="rounded-lg border border-lime-600 px-5 py-3 text-sm text-lime-600 disabled:opacity-40"
      onclick={add}>Добавить ещё</button
    >
    <div class="relative flex gap-1">
      <button
        disabled={generating}
        onclick={() => generate(10)}
        class="rounded-lg bg-slate-400 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50"
        >✧ Сгенерировать</button
      ><button
        aria-label="Количество промптов для генерации"
        aria-expanded={menu}
        disabled={generating}
        onclick={() => (menu = !menu)}
        class="rounded-lg bg-slate-400 px-4 py-3 text-white">⌄</button
      >{#if menu}<div
          class="absolute top-full right-0 z-10 mt-2 w-48 rounded-lg border border-slate-200 bg-white p-1 shadow-lg"
        >
          {#each [5, 10, 20] as count (count)}<button
              class="block w-full rounded px-3 py-2 text-left text-sm hover:bg-slate-50"
              onclick={() => generate(count)}>Сгенерировать {count}</button
            >{/each}
        </div>{/if}
    </div>
  </div>
{:else}
  <div class="mt-5 flex flex-wrap items-start gap-4">
    <label class="cursor-pointer rounded-lg bg-slate-400 px-5 py-3 text-sm font-semibold text-white"
      >↑ {uploading ? 'Загружаем…' : 'Загрузить файлом'}<input
        aria-label="Загрузить промпты файлом"
        type="file"
        accept=".txt,.csv,.xlsx"
        disabled={uploading}
        onchange={upload}
        class="sr-only"
      /></label
    >
    <div class="flex-1 text-xs leading-relaxed text-slate-400">
      <p>Загрузите TXT, CSV или XLSX, каждый промпт с новой строки.</p>
      <p>Для групп используйте CSV или XLSX с колонками «Промпт» и «Группа». До 256 КБ.</p>
      <p class="mt-1">
        Примеры файлов: <a href="/templates/prompts.txt" download class="ml-2 text-blue-600"
          >▧ txt</a
        ><a href="/templates/prompts.csv" download class="ml-2 text-blue-600">▧ csv</a><a
          href="/templates/prompts.xlsx"
          download
          class="ml-2 text-blue-600">▧ xlsx</a
        >
      </p>
    </div>
  </div>
  <label class="mt-6 block text-sm text-slate-400"
    ><span class="flex justify-between"
      ><span>Список промптов, каждый с новой строки</span><span class="text-xs"
        >{queries.length} / 20</span
      ></span
    ><textarea
      aria-label="Список промптов"
      aria-invalid={!valid}
      bind:value={text}
      oninput={editList}
      rows="8"
      class="mt-2 w-full rounded-lg border border-slate-300 px-3 py-3 text-sm text-slate-700 outline-none focus:border-lime-500"
    ></textarea></label
  >
  <p class="mt-2 text-xs text-slate-400">
    Максимальная длина одного промпта — 400 символов, до 40 слов.
  </p>
  {#if groups.length}<p class="mt-3 text-xs text-slate-500">
      Группы из файла: {groups.join(', ')}
    </p>{/if}
{/if}
