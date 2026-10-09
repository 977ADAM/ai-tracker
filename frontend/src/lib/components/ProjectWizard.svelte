<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { resolve } from '$app/paths';
  import { goto } from '$app/navigation';
  import type { Project, ProjectInput, ProjectQuery, Competitor } from '$lib/project-types';
  import type { PublicProvider } from '$lib/types';
  import { projectRequest } from '$lib/project-client';
  let {
    initial = null,
    providers = [],
  }: { initial?: Project | null; providers?: PublicProvider[] } = $props();
  let id = $state<string | null>(untrack(() => initial?.id ?? null));
  let name = $state(untrack(() => initial?.name ?? ''));
  let brand = $state(untrack(() => initial?.brand ?? ''));
  let site = $state(untrack(() => initial?.site_url ?? ''));
  let description = $state(untrack(() => initial?.brand_description ?? ''));
  let aliases = $state(untrack(() => initial?.brand_aliases?.join('\n') ?? ''));
  let queries = $state<ProjectQuery[]>(
    untrack(() => initial?.queries.map((q) => ({ ...q })) ?? []),
  );
  let competitors = $state<Competitor[]>(
    untrack(() => initial?.competitors.map((c) => ({ ...c })) ?? []),
  );
  let ids = $state<string[]>(untrack(() => initial?.connection_ids.slice() ?? []));
  let yandex = $state(untrack(() => initial?.yandex_enabled ?? false));
  let region = $state(untrack(() => initial?.yandex_region ?? 213));
  let step = $state(
    untrack(() =>
      !initial
        ? 1
        : !initial.brand_description
          ? 2
          : !initial.queries.length
            ? 3
            : !initial.connection_ids.length
              ? 5
              : 6,
    ),
  );
  let reached = $state(untrack(() => step));
  let busy = $state(false),
    generating = $state(false),
    error = $state('');
  let dialog: HTMLDialogElement;
  const labels = ['Бренд и сайт', 'Описание', 'Промпты', 'Конкуренты', 'Нейросети', 'Запуск'];
  const categories = [
    ['commercial', 'Коммерческий'],
    ['informational', 'Информационный'],
    ['comparative', 'Сравнительный'],
    ['recommendation', 'Рекомендовательный'],
  ];
  const input =
    'mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-3 text-sm text-slate-700 outline-none focus:border-lime-500 focus:ring-1 focus:ring-lime-500';
  let estimate = $derived(queries.length * ids.length);
  onMount(() => {
    dialog.showModal();
    if (step === 2 && !description) void generate('description');
    else if (step === 3 && !queries.length) void generate('queries');
  });
  async function leave() {
    await goto(id ? resolve('/projects/[id]', { id }) : resolve('/'));
  }
  function payload(): ProjectInput {
    return {
      name: name || brand,
      brand,
      site_url: site,
      brand_description: description,
      brand_aliases: aliases
        .split('\n')
        .map((a) => a.trim())
        .filter(Boolean),
      queries,
      competitors,
      connection_ids: ids,
      yandex_enabled: yandex,
      yandex_region: region,
    };
  }
  async function save() {
    const p = await projectRequest<Project>(
      id ? `/api/projects/${id}` : '/api/projects',
      id ? 'PUT' : 'POST',
      payload(),
    );
    id = p.id;
    name = p.name;
  }
  async function pause() {
    if (busy || generating) return;
    busy = true;
    error = '';
    try {
      if (id) await save();
      await leave();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Не удалось сохранить черновик';
    } finally {
      busy = false;
    }
  }
  function validate() {
    if (step === 1 && (!brand.trim() || !/^https?:\/\//.test(site)))
      throw new Error('Укажите бренд и адрес сайта со схемой https://');
    if (step === 2 && !description.trim()) throw new Error('Добавьте описание бренда');
    if (step === 3 && (!queries.length || queries.some((q) => !q.text.trim())))
      throw new Error('Добавьте хотя бы один заполненный промпт');
    if (step === 5 && !ids.length) throw new Error('Выберите хотя бы одну нейросеть');
  }
  async function generate(kind: 'description' | 'queries' | 'competitors') {
    if (!id || generating) return;
    generating = true;
    error = '';
    try {
      const value = await projectRequest<{
        kind: string;
        proposal: {
          brand_description?: string;
          brand_aliases?: string[];
          queries?: ProjectQuery[];
          competitors?: Competitor[];
        };
      }>(`/api/projects/${id}/generate`, 'POST', { kind });
      if (kind === 'description') {
        description = value.proposal.brand_description ?? '';
        aliases = value.proposal.brand_aliases?.join('\n') ?? '';
      } else if (kind === 'queries') queries = value.proposal.queries ?? [];
      else competitors = value.proposal.competitors ?? [];
    } catch (e) {
      error =
        (e instanceof Error ? e.message : 'Не удалось создать предложение') +
        '. Можно заполнить поля вручную.';
    } finally {
      generating = false;
    }
  }
  async function next() {
    if (busy || generating) return;
    error = '';
    busy = true;
    try {
      validate();
      await save();
      step++;
      reached = Math.max(reached, step);
      if (step === 2 && !description) await generate('description');
      else if (step === 3 && !queries.length) await generate('queries');
      else if (step === 4 && !competitors.length) await generate('competitors');
    } catch (e) {
      error = e instanceof Error ? e.message : 'Не удалось сохранить шаг';
    } finally {
      busy = false;
    }
  }
  async function start() {
    if (!id || busy || generating) return;
    error = '';
    busy = true;
    try {
      await save();
      await projectRequest(`/api/projects/${id}/measurements`, 'POST');
      await goto(resolve('/projects/[id]', { id }));
    } catch (e) {
      error = e instanceof Error ? e.message : 'Не удалось запустить замер';
    } finally {
      busy = false;
    }
  }
  function back() {
    if (!busy && !generating) {
      step = Math.max(1, step - 1);
      error = '';
    }
  }
</script>

<dialog
  bind:this={dialog}
  oncancel={(e) => {
    e.preventDefault();
    void leave();
  }}
  class="m-auto max-h-[95vh] w-[calc(100%_-_1rem)] max-w-4xl rounded-xl border-0 bg-white p-0 text-slate-700 shadow-2xl backdrop:bg-black/40"
  aria-labelledby="wizard-title"
>
  <div class="flex items-center justify-between gap-4 px-5 pt-6 sm:px-7">
    <h1 id="wizard-title" class="text-lg font-bold">Создание проекта в Трекере ИИ</h1>
    <button
      aria-label="Закрыть мастер"
      class="size-8 rounded-lg text-2xl text-slate-400 hover:bg-slate-100"
      onclick={leave}>×</button
    >
  </div>
  <div class="px-5 pt-6 sm:px-7">
    <nav
      aria-label="Шаги создания проекта"
      class="flex gap-2 overflow-x-auto rounded-full bg-slate-100 px-3 py-2"
    >
      {#each labels as label, i (label)}<button
          disabled={i + 1 > reached || busy || generating}
          onclick={() => {
            step = i + 1;
            error = '';
          }}
          aria-current={step === i + 1 ? 'step' : undefined}
          class={`flex shrink-0 items-center gap-2 rounded-full px-2 py-1 text-xs ${step === i + 1 ? 'bg-lime-600 font-semibold text-white' : i + 1 < step ? 'text-lime-600' : 'text-slate-500'}`}
          ><span
            class={`grid size-5 place-items-center rounded-full border ${i + 1 < step ? 'border-lime-600 bg-lime-600 text-white' : 'border-current'}`}
            >{i + 1 < step ? '✓' : i + 1}</span
          >{label}</button
        >{#if i < 5}<span class="my-auto text-slate-300" aria-hidden="true">›</span>{/if}{/each}
    </nav>
  </div>
  <div class="min-h-80 px-5 py-6 sm:px-7">
    <h2 class="text-2xl font-semibold tracking-tight">{labels[step - 1]}</h2>
    {#if error}<p role="alert" class="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">
        {error}
      </p>{/if}
    {#if generating}<p role="status" class="mt-4 rounded-lg bg-lime-50 p-3 text-sm text-lime-700">
        Читаем сайт и готовим предложения…
      </p>{/if}
    {#if step === 1}<p class="mt-4 text-sm text-slate-500">
        Укажите бренд и сайт. Остальные настройки добавим внутри проекта.
      </p>
      <div class="mt-7 space-y-5">
        <label class="block text-sm text-slate-500"
          >Название бренда <span class="text-red-400">*</span><input
            aria-label="Название бренда"
            bind:value={brand}
            maxlength="100"
            required
            class={input}
            placeholder="Например, Додопицца"
          /></label
        ><label class="block text-sm text-slate-500"
          >Сайт <span class="text-red-400">*</span><input
            aria-label="Сайт"
            bind:value={site}
            type="url"
            maxlength="2048"
            required
            class={input}
            placeholder="https://example.ru"
          /></label
        >
      </div>
    {:else if step === 2}<p class="mt-4 max-w-2xl text-sm leading-relaxed text-slate-500">
        Добавьте описание бренда и варианты его названия — синонимы и сокращения.<br />Так проверка
        упоминаний будет точнее.
      </p>
      <div class="mt-7 space-y-5">
        <label class="block text-sm text-slate-400"
          ><span class="flex justify-between"
            ><span>Описание бренда <span class="text-red-400">*</span></span><span class="text-xs"
              >{description.length} / 500</span
            ></span
          ><textarea
            bind:value={description}
            maxlength="500"
            rows="3"
            class={input}
            placeholder="Введите описание бренда"></textarea></label
        >
        <p class="-mt-3 text-xs text-slate-500">
          Пример: Международная сеть пиццерий. Пицца и доставка — основной продукт.
        </p>
        <label class="block text-sm text-slate-400"
          >Варианты названия бренда: синонимы/сокращения<textarea
            bind:value={aliases}
            rows="3"
            class={input}
            placeholder="Введите варианты названия бренда, каждый с новой строки"></textarea></label
        >
        <p class="-mt-3 text-xs text-slate-500">Пример:<br />Додошка<br />dodo</p>
      </div>
      <div class="mt-7 flex justify-end">
        <button
          disabled={busy || generating}
          onclick={() => generate('description')}
          class="rounded-lg bg-slate-400 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50"
          >✧ Сгенерировать заново</button
        >
      </div>
    {:else if step === 3}<p class="mt-4 text-sm text-slate-500">
        Проверьте промпты. Этот набор сохранится в проекте и будет повторяться при каждом замере.
      </p>
      <div class="mt-6 flex flex-wrap justify-between gap-3">
        <span class="text-xs text-slate-400">{queries.length} / 20 · до 400 символов и 40 слов</span
        ><button
          disabled={generating || queries.length >= 20}
          class="text-sm text-lime-600"
          onclick={() => (queries = [...queries, { text: '', category: null }])}
          >+ Добавить промпт</button
        >
      </div>
      <div class="mt-4 space-y-3">
        {#each queries as q, i (q)}<div class="flex flex-wrap items-center gap-2">
            <textarea
              aria-label={`Промпт ${i + 1}`}
              bind:value={q.text}
              rows="2"
              maxlength="400"
              class="min-w-48 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
              placeholder="Введите запрос"></textarea><select
              aria-label={`Категория промпта ${i + 1}`}
              bind:value={q.category}
              class="rounded-lg border border-slate-300 px-2 py-2 text-xs"
              ><option value={null}>Без категории</option>{#each categories as c (c[0])}<option
                  value={c[0]}>{c[1]}</option
                >{/each}</select
            ><button
              aria-label={`Удалить промпт ${i + 1}`}
              class="size-8 text-xl text-slate-400"
              onclick={() => (queries = queries.filter((_, n) => n !== i))}>×</button
            >
          </div>{/each}
      </div>
      <div class="mt-7 flex justify-end">
        <button
          disabled={busy || generating}
          onclick={() => generate('queries')}
          class="rounded-lg bg-slate-400 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50"
          >✧ Сгенерировать заново</button
        >
      </div>
    {:else if step === 4}<p class="mt-4 text-sm text-slate-500">
        Предложения модели — проверьте бренды и сайты конкурентов. Этот шаг можно оставить пустым.
      </p>
      <div class="mt-6 flex justify-between gap-3">
        <span class="text-xs text-slate-400">{competitors.length} / 10</span><button
          disabled={generating || competitors.length >= 10}
          class="text-sm text-lime-600"
          onclick={() => (competitors = [...competitors, { brand: '', site_url: '' }])}
          >+ Добавить конкурента</button
        >
      </div>
      <div class="mt-4 space-y-3">
        {#each competitors as c, i (c)}<div class="flex flex-wrap items-center gap-2">
            <input
              aria-label={`Бренд конкурента ${i + 1}`}
              bind:value={c.brand}
              maxlength="100"
              placeholder="Бренд"
              class="min-w-32 flex-1 rounded-lg border border-slate-300 px-3 py-3 text-sm"
            /><input
              aria-label={`Сайт конкурента ${i + 1}`}
              bind:value={c.site_url}
              type="url"
              placeholder="https://competitor.ru"
              class="min-w-40 flex-1 rounded-lg border border-slate-300 px-3 py-3 text-sm"
            /><button
              aria-label={`Удалить конкурента ${i + 1}`}
              class="size-8 text-xl text-slate-400"
              onclick={() => (competitors = competitors.filter((_, n) => n !== i))}>×</button
            >
          </div>{/each}
      </div>
      <div class="mt-7 flex justify-end">
        <button
          disabled={busy || generating}
          onclick={() => generate('competitors')}
          class="rounded-lg bg-slate-400 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50"
          >✧ Сгенерировать заново</button
        >
      </div>
    {:else if step === 5}<p class="mt-4 text-sm text-slate-500">
        Выберите до пяти моделей. Каждый промпт будет отправлен каждой выбранной нейросети.
      </p>
      <div class="mt-6 grid gap-3 sm:grid-cols-2">
        {#each providers as p (p.id)}<label
            class="flex items-center gap-3 rounded-lg border border-slate-200 p-4 text-sm"
            ><input
              type="checkbox"
              value={p.id}
              bind:group={ids}
              disabled={ids.length >= 5 && !ids.includes(p.id)}
              class="accent-lime-600"
            /><span
              >{p.name}<span class="mt-1 block text-xs text-slate-400"
                >{p.configured
                  ? p.answer_mode === 'deepseek_web'
                    ? 'Веб-поиск и источники'
                    : 'Текстовый ответ'
                  : 'Ключ не задан'}</span
              ></span
            ></label
          >{/each}
      </div>
      {#if !providers.length}<p class="mt-4 text-sm text-slate-500">
          Добавьте подключения в общих настройках API. Черновик проекта уже сохранён.
        </p>{/if}{#each ids.filter((id) => !providers.some((p) => p.id === id)) as missing (missing)}<label
          class="mt-3 block text-sm text-red-600"
          ><input type="checkbox" value={missing} bind:group={ids} /> Удалённая модель — снимите выбор</label
        >{/each}<button class="mt-5 text-sm text-lime-600 underline" onclick={pause}
        >Закрыть мастер и открыть проект</button
      >
    {:else}<p class="mt-4 text-sm text-slate-500">
        Проверьте параметры. Замер начнётся только после нажатия кнопки.
      </p>
      <dl class="mt-6 grid gap-4 rounded-xl bg-slate-50 p-5 text-sm sm:grid-cols-2">
        <div>
          <dt class="text-slate-400">Бренд и сайт</dt>
          <dd class="mt-1 font-medium">{brand} · {site}</dd>
        </div>
        <div>
          <dt class="text-slate-400">Промпты / конкуренты / нейросети</dt>
          <dd class="mt-1 font-medium">{queries.length} / {competitors.length} / {ids.length}</dd>
        </div>
        <div class="sm:col-span-2">
          <dt class="text-slate-400">Описание</dt>
          <dd class="mt-1">{description}</dd>
        </div>
        <div class="sm:col-span-2">
          <dt class="text-slate-400">Варианты названия</dt>
          <dd class="mt-1">{aliases.split('\n').filter(Boolean).join(', ') || 'Не заданы'}</dd>
        </div>
      </dl>
      <label class="mt-6 flex items-center gap-3 text-sm"
        ><input type="checkbox" bind:checked={yandex} class="accent-lime-600" />Также проверить
        выдачу Яндекса</label
      >{#if yandex}<label class="mt-4 block text-sm"
          >Регион<select bind:value={region} class={input}
            ><option value={213}>Москва</option><option value={1}>Москва и область</option><option
              value={2}>Санкт-Петербург</option
            ><option value={54}>Екатеринбург</option><option value={65}>Новосибирск</option><option
              value={43}>Казань</option
            ><option value={47}>Нижний Новгород</option><option value={39}>Ростов-на-Дону</option
            ><option value={35}>Краснодар</option><option value={239}>Сочи</option><option
              value={172}>Уфа</option
            ><option value={28}>Махачкала</option><option value={1106}>Грозный</option><option
              value={225}>Россия</option
            ></select
          ></label
        >{/if}
      <p class="mt-5 rounded-lg bg-lime-50 p-4 text-sm">
        На замер: <strong>{estimate} ответов моделей</strong>, до {estimate} оценок тональности{yandex
          ? `, ${queries.length} поисков Яндекса`
          : ''}.
      </p>
    {/if}
  </div>
  <footer
    class="mx-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 py-4 sm:mx-7"
  >
    <div class="flex gap-3">
      <button
        aria-label="Назад"
        disabled={step === 1 || busy || generating}
        onclick={back}
        class="rounded-lg border border-slate-300 px-4 py-3 text-slate-400 disabled:opacity-40"
        >‹</button
      >{#if step < 6}<button
          disabled={busy || generating}
          onclick={next}
          class="rounded-lg bg-lime-600 px-6 py-3 text-sm font-semibold text-white disabled:opacity-50"
          >✓ Далее</button
        >{:else}<button
          disabled={busy || generating}
          onclick={start}
          class="rounded-lg bg-lime-600 px-6 py-3 text-sm font-semibold text-white disabled:opacity-50"
          >Запустить замер</button
        >{/if}
    </div>
    <button disabled={busy || generating} onclick={pause} class="text-xs text-slate-400"
      >{id ? 'Продолжить позже' : 'Отмена'}</button
    >
  </footer>
</dialog>
