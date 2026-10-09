<script lang="ts">
  import { untrack } from 'svelte';
  import { resolve } from '$app/paths';
  import { goto } from '$app/navigation';
  import type { Project, ProjectInput } from '$lib/project-types';
  import type { PublicProvider } from '$lib/types';
  import { projectRequest } from '$lib/project-client';
  let {
    initial = null,
    providers = [],
  }: { initial?: Project | null; providers?: PublicProvider[] } = $props();
  let name = $state(untrack(() => initial?.name ?? ''));
  let brand = $state(untrack(() => initial?.brand ?? ''));
  let site = $state(untrack(() => initial?.site_url ?? ''));
  let queries = $state(untrack(() => initial?.queries.map((q) => ({ ...q })) ?? []));
  let competitors = $state(untrack(() => initial?.competitors.map((c) => ({ ...c })) ?? []));
  let ids = $state<string[]>(untrack(() => initial?.connection_ids.slice() ?? []));
  let yandex = $state(untrack(() => initial?.yandex_enabled ?? false));
  let region = $state(untrack(() => initial?.yandex_region ?? 213));
  let subdomains = $state(untrack(() => initial?.include_subdomains ?? true));
  let description = $state(untrack(() => initial?.brand_description ?? ''));
  let aliases = $state(untrack(() => initial?.brand_aliases?.join('\n') ?? ''));
  let saving = $state(false);
  let error = $state('');
  let fieldErrors = $state<Record<string, string>>({});
  const inputClass =
    'mt-2 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent-soft';
  const categories = [
    ['commercial', 'Коммерческий'],
    ['informational', 'Информационный'],
    ['comparative', 'Сравнительный'],
    ['recommendation', 'Рекомендовательный'],
  ];
  const regions = [
    [213, 'Москва'],
    [1, 'Москва и область'],
    [2, 'Санкт-Петербург'],
    [54, 'Екатеринбург'],
    [65, 'Новосибирск'],
    [43, 'Казань'],
    [47, 'Нижний Новгород'],
    [39, 'Ростов-на-Дону'],
    [35, 'Краснодар'],
    [239, 'Сочи'],
    [172, 'Уфа'],
    [28, 'Махачкала'],
    [1106, 'Грозный'],
    [225, 'Россия'],
  ] as const;
  async function save(e: SubmitEvent) {
    e.preventDefault();
    if (saving) return;
    fieldErrors = {};
    error = '';
    if (initial && !name.trim()) fieldErrors.name = 'Укажите название';
    if (!brand.trim()) fieldErrors.brand = 'Укажите бренд';
    if (!/^https?:\/\//.test(site)) fieldErrors.site = 'Укажите адрес со схемой https://';
    if (queries.some((q) => !q.text.trim())) fieldErrors.queries = 'Заполните все запросы';
    if (new Set(queries.map((q) => q.text.trim().toLocaleLowerCase())).size !== queries.length)
      fieldErrors.queries = 'Запросы должны различаться';
    if (Object.keys(fieldErrors).length) return;
    saving = true;
    try {
      const payload: ProjectInput = {
        name: initial ? name : brand,
        brand,
        brand_description: description,
        brand_aliases: aliases
          .split('\n')
          .map((a) => a.trim())
          .filter(Boolean),
        site_url: site,
        include_subdomains: subdomains,
        queries: initial ? queries : [],
        competitors: initial ? competitors : [],
        connection_ids: initial ? ids : [],
        yandex_enabled: initial ? yandex : false,
        yandex_region: region,
      };
      const p = await projectRequest<Project>(
        initial ? `/api/projects/${initial.id}` : '/api/projects',
        initial ? 'PUT' : 'POST',
        payload,
      );
      await goto(resolve('/projects/[id]', { id: p.id }));
    } catch (e) {
      error = e instanceof Error ? e.message : 'Не удалось сохранить проект';
    } finally {
      saving = false;
    }
  }
</script>

<form onsubmit={save} class="space-y-8 rounded-2xl border border-line bg-white p-5 sm:p-8">
  {#if error}<p role="alert" class="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>{/if}
  <section>
    <h2 class="text-lg font-semibold">Основное</h2>
    <div class="mt-4 grid gap-5 sm:grid-cols-2">
      {#if initial}<label class="text-sm font-medium"
          >Название проекта<input
            class={inputClass}
            bind:value={name}
            maxlength="100"
            required
            aria-invalid={!!fieldErrors.name}
          />{#if fieldErrors.name}<span class="text-xs text-red-600">{fieldErrors.name}</span
            >{/if}</label
        >{/if}<label class="text-sm font-medium"
        >Название бренда<input
          class={inputClass}
          bind:value={brand}
          maxlength="100"
          required
          aria-invalid={!!fieldErrors.brand}
        />{#if fieldErrors.brand}<span class="text-xs text-red-600">{fieldErrors.brand}</span
          >{/if}</label
      ><label class="text-sm font-medium sm:col-span-2"
        >Сайт<input
          class={inputClass}
          bind:value={site}
          type="url"
          placeholder="https://example.ru"
          maxlength="2048"
          required
          aria-invalid={!!fieldErrors.site}
        />{#if fieldErrors.site}<span class="text-xs text-red-600">{fieldErrors.site}</span
          >{/if}</label
      >
    </div>
  </section>
  {#if initial}
    <label class="flex gap-3 text-sm"
      ><input type="checkbox" bind:checked={subdomains} />Учитывать поддомены сайта</label
    >
    <section>
      <h2 class="text-lg font-semibold">Описание и варианты названия</h2>
      <label class="mt-4 block text-sm"
        >Описание бренда<textarea
          class={inputClass}
          bind:value={description}
          maxlength="500"
          rows="3"></textarea></label
      ><label class="mt-4 block text-sm"
        >Варианты названия бренда<textarea
          class={inputClass}
          bind:value={aliases}
          rows="3"
          placeholder="Каждый вариант с новой строки"></textarea></label
      >
    </section>
    <section>
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-semibold">
          Запросы <span class="text-sm font-normal text-muted">{queries.length} / 20</span>
        </h2>
        <button
          type="button"
          disabled={queries.length >= 20}
          class="text-sm font-medium text-accent disabled:opacity-40"
          onclick={() => (queries = [...queries, { text: '', category: null }])}
          >+ Добавить запрос</button
        >
      </div>
      <p class="mt-2 text-xs text-muted">
        Сохраняются в проекте и повторяются при каждом замере. До 400 символов и 40 слов.
      </p>
      {#if fieldErrors.queries}<p role="alert" class="mt-2 text-sm text-red-600">
          {fieldErrors.queries}
        </p>{/if}
      <div class="mt-4 space-y-3">
        {#each queries as q, i (q)}<div class="flex flex-wrap items-center gap-2">
            <input
              aria-label={`Запрос ${i + 1}`}
              bind:value={q.text}
              class="min-w-48 flex-1 rounded-lg border border-line px-3 py-2.5 text-sm"
              maxlength="400"
              required
            /><select
              aria-label={`Категория запроса ${i + 1}`}
              bind:value={q.category}
              class="rounded-lg border border-line px-2 py-2.5 text-xs"
              ><option value={null}>Без категории</option>{#each categories as c (c)}<option
                  value={c[0]}>{c[1]}</option
                >{/each}</select
            ><button
              type="button"
              aria-label={`Удалить запрос ${i + 1}`}
              disabled={false}
              class="size-9 rounded-lg text-muted hover:bg-canvas disabled:opacity-30"
              onclick={() => (queries = queries.filter((_, n) => n !== i))}>×</button
            >
          </div>{/each}
      </div>
    </section>
    <section>
      <h2 class="text-lg font-semibold">
        Модели <span class="text-sm font-normal text-muted">{ids.length} / 5</span>
      </h2>
      <p class="mt-2 text-xs text-muted">
        Каждый запрос отправляется каждой выбранной модели. Подключения — в «Настройках API».
      </p>
      {#if fieldErrors.models}<p role="alert" class="mt-2 text-sm text-red-600">
          {fieldErrors.models}
        </p>{/if}
      <div class="mt-4 grid gap-2 sm:grid-cols-2">
        {#each providers as p (p)}<label
            class="flex items-center gap-3 rounded-lg border border-line p-3 text-sm"
            ><input
              type="checkbox"
              value={p.id}
              bind:group={ids}
              disabled={ids.length >= 5 && !ids.includes(p.id)}
              class="accent-accent"
            /><span
              >{p.name}<span class="ml-2 text-xs text-muted"
                >{p.answer_mode === 'deepseek_web' ? 'Веб-поиск' : 'Текст'}</span
              ></span
            ></label
          >{/each}{#each ids.filter((id) => !providers.some((p) => p.id === id)) as id (id)}<label
            class="rounded-lg border border-red-200 p-3 text-sm text-red-700"
            ><input type="checkbox" value={id} bind:group={ids} /> Удалённая модель — снимите выбор</label
          >{/each}
      </div>
      {#if !providers.length}<p class="mt-3 text-sm text-muted">
          Сначала добавьте модели в настройках API.
        </p>{/if}
    </section>
    <section>
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-semibold">
          Конкуренты <span class="text-sm font-normal text-muted">{competitors.length} / 10</span>
        </h2>
        <button
          type="button"
          disabled={competitors.length >= 10}
          class="text-sm font-medium text-accent"
          onclick={() => (competitors = [...competitors, { brand: '', site_url: '' }])}
          >+ Добавить</button
        >
      </div>
      <div class="mt-4 space-y-3">
        {#each competitors as c, i (c)}<div class="flex flex-wrap gap-2">
            <input
              aria-label={`Бренд конкурента ${i + 1}`}
              bind:value={c.brand}
              placeholder="Бренд"
              maxlength="100"
              required
              class="min-w-32 flex-1 rounded-lg border border-line px-3 py-2 text-sm"
            /><input
              aria-label={`Сайт конкурента ${i + 1}`}
              bind:value={c.site_url}
              type="url"
              placeholder="https://competitor.ru"
              class="min-w-40 flex-1 rounded-lg border border-line px-3 py-2 text-sm"
            /><button
              type="button"
              aria-label={`Удалить конкурента ${i + 1}`}
              class="size-9 text-muted"
              onclick={() => (competitors = competitors.filter((_, n) => n !== i))}>×</button
            >
          </div>{/each}
      </div>
    </section>
    <section class="rounded-xl bg-canvas p-4">
      <label class="flex items-center gap-3 text-sm font-medium"
        ><input type="checkbox" bind:checked={yandex} class="accent-accent" />Проверять выдачу
        Яндекса</label
      >{#if yandex}<label class="mt-3 block text-xs"
          >Регион<select bind:value={region} class={inputClass}
            >{#each regions as r (r)}<option value={r[0]}>{r[1]}</option>{/each}</select
          ></label
        >{/if}
      <p class="mt-3 text-xs text-muted">
        На замер: {queries.length * ids.length} ответов моделей, до {queries.length * ids.length} оценок
        тональности{yandex ? `, ${queries.length} поисков Яндекса` : ''}. Сохранение не запускает
        замер.
      </p>
    </section>
  {/if}
  <div class="flex gap-3 border-t border-line pt-5">
    <button
      type="submit"
      disabled={saving}
      class="rounded-xl bg-accent px-5 py-3 text-sm font-semibold text-white disabled:opacity-50"
      >{saving ? 'Сохраняем…' : initial ? 'Сохранить проект' : 'Создать проект'}</button
    ><a
      href={initial ? `/projects/${initial.id}` : '/'}
      class="rounded-xl border border-line px-5 py-3 text-sm">Отмена</a
    >
  </div>
</form>
