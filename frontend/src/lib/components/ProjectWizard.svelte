<script lang="ts">
  import PromptSetup from './PromptSetup.svelte';
  import { normalizeSiteInput, parseCompetitorInput } from '$lib/project-setup';
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
  let site = $state(untrack(() => initial?.site_url.replace(/^https?:\/\//, '') ?? ''));
  let subdomains = $state(untrack(() => initial?.include_subdomains ?? false));
  let competitorInput = $state('');
  let promptValid = $state(true);
  let importing = $state(false);
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
  const input =
    'mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-3 text-sm text-slate-700 outline-none focus:border-lime-500 focus:ring-1 focus:ring-lime-500';
  let estimate = $derived(queries.length * ids.length);
  let selectable = $derived(providers.slice(0, 5).map((p) => p.id));
  let allSelected = $derived(selectable.length > 0 && selectable.every((id) => ids.includes(id)));
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
      site_url: normalizeSiteInput(site),
      include_subdomains: subdomains,
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
    if (busy || generating || importing) return;
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
    if (step === 1) {
      if (!brand.trim()) throw new Error('Укажите бренд');
      normalizeSiteInput(site);
    }
    if (step === 3 && !promptValid) throw new Error('Исправьте список промптов');
    if (step === 2 && !description.trim()) throw new Error('Добавьте описание бренда');
    if (step === 3 && (!queries.length || queries.some((q) => !q.text.trim())))
      throw new Error('Добавьте хотя бы один заполненный промпт');
    if (step === 5 && !ids.length) throw new Error('Выберите хотя бы одну нейросеть');
  }
  async function generate(kind: 'description' | 'queries' | 'competitors', count = 10) {
    if (!id || generating || importing) return;
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
      }>(`/api/projects/${id}/generate`, 'POST', { kind, count });
      if (kind === 'description') {
        description = value.proposal.brand_description ?? '';
        aliases = value.proposal.brand_aliases?.join('\n') ?? '';
      } else if (kind === 'queries') {
        queries = value.proposal.queries ?? [];
        promptValid = true;
      } else competitors = value.proposal.competitors ?? [];
    } catch (e) {
      error =
        (e instanceof Error ? e.message : 'Не удалось создать предложение') +
        '. Можно заполнить поля вручную.';
    } finally {
      generating = false;
    }
  }
  async function next() {
    if (busy || generating || importing) return;
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
    if (!id || busy || generating || importing) return;
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
  function addCompetitor() {
    error = '';
    try {
      const c = parseCompetitorInput(competitorInput);
      if (
        competitors.some(
          (r) =>
            r.brand.toLocaleLowerCase() === c.brand.toLocaleLowerCase() &&
            r.site_url === c.site_url,
        )
      )
        throw new Error('Этот конкурент уже добавлен');
      if (competitors.length >= 10) throw new Error('Добавьте не более 10 конкурентов');
      competitors = [...competitors, c];
      competitorInput = '';
    } catch (e) {
      error = e instanceof Error ? e.message : 'Некорректный конкурент';
    }
  }
  function selectAll() {
    ids = allSelected ? [] : selectable.slice();
  }
  function savedHost() {
    try {
      return new URL(normalizeSiteInput(site)).hostname.replace(/^www\./, '');
    } catch {
      return site.trim();
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
  class="wizard-dialog m-auto max-h-[95vh] w-[calc(100%_-_1rem)] max-w-4xl rounded-xl border-0 bg-white p-0 text-slate-700 shadow-2xl backdrop:bg-black/40"
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
          disabled={i + 1 > reached || busy || generating || importing}
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
  <div class="min-h-0 flex-1 overflow-y-auto px-5 py-6 sm:px-7">
    <h2 class={`text-2xl font-semibold tracking-tight ${step === 5 ? 'sr-only' : ''}`}>
      {step === 4 ? 'Бренды конкурентов' : labels[step - 1]}
    </h2>
    {#if error}<p role="alert" class="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">
        {error}
      </p>{/if}
    {#if generating}<p role="status" class="mt-4 rounded-lg bg-lime-50 p-3 text-sm text-lime-700">
        Читаем сайт и готовим предложения…
      </p>{/if}
    {#if step === 1}<p class="mt-4 text-sm text-slate-500">
        Укажите название бренда для поиска упоминаний, а сайт — для проверки цитируемости в ИИ.
      </p>
      <div class="mt-7 space-y-5">
        <label class="block text-sm text-slate-400"
          ><span class="flex justify-between"
            ><span>Бренд <span class="text-red-400">*</span></span><span class="text-xs"
              >{brand.length} / 100</span
            ></span
          ><input
            aria-label="Название бренда"
            bind:value={brand}
            maxlength="100"
            required
            class={input}
            placeholder="Например, додо или додопицца"
          /></label
        >
        <p class="-mt-3 text-xs text-slate-500">Пример: додо или додопицца</p>
        <label class="block text-sm text-slate-400"
          ><span class="flex justify-between"
            ><span>Сайт</span><span class="text-xs">{site.length} / 2048</span></span
          ><input
            aria-label="Сайт"
            bind:value={site}
            maxlength="2048"
            class={input}
            placeholder="dodopizza.ru"
          /></label
        >
        <p class="-mt-3 text-xs text-slate-500">
          Сохраним как {savedHost() || 'example.ru'}, {subdomains ? 'с учётом' : 'без учёта'} поддоменов
        </p>
        <label class="flex items-center gap-3 text-sm text-slate-500"
          ><input
            type="checkbox"
            bind:checked={subdomains}
            class="size-5 accent-lime-600"
          />Учитывать поддомены сайта</label
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
          disabled={busy || generating || importing}
          onclick={() => generate('description')}
          class="rounded-lg bg-slate-400 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50"
          >✧ Сгенерировать заново</button
        >
      </div>
    {:else if step === 3}<PromptSetup
        bind:uploading={importing}
        bind:queries
        bind:valid={promptValid}
        {generating}
        onGenerate={(count) => generate('queries', count)}
      />
    {:else if step === 4}<p class="mt-4 text-sm text-slate-500">
        Выберите конкурентов, чтобы видеть их упоминания по вашим промптам и сравнить видимость
        брендов.
      </p>
      <div class="mt-12">
        <label class="block text-sm"
          ><span class="flex justify-between"
            ><span>Бренд</span><span class="text-xs text-slate-400"
              >{competitorInput.length} / 100</span
            ></span
          >
          <div class="mt-2 flex gap-4">
            <input
              aria-label="Бренд или сайт конкурента"
              bind:value={competitorInput}
              maxlength="100"
              class="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-3 text-sm outline-none focus:border-lime-500"
              placeholder="Введите бренд или сайт конкурента"
            /><button
              disabled={!competitorInput.trim() || competitors.length >= 10}
              onclick={addCompetitor}
              class="rounded-lg bg-slate-400 px-5 py-3 text-sm font-semibold text-white disabled:opacity-40"
              >＋ Добавить</button
            >
          </div></label
        >
        <p class="mt-2 text-xs text-slate-400">
          Например, бренд конкурента или competitor.ru. Сайт необязателен для проверки упоминаний.
        </p>
      </div>
      <div class="mt-5 flex flex-wrap gap-2">
        {#each competitors as c, i (c)}<span
            class="inline-flex items-center gap-3 rounded-lg bg-slate-100 px-3 py-2 text-sm"
            >{c.brand}{#if c.site_url}<span class="text-xs text-slate-400"
                >{c.site_url.replace(/^https?:\/\//, '')}</span
              >{/if}<button
              aria-label={`Удалить конкурента ${i + 1}`}
              onclick={() => (competitors = competitors.filter((_, n) => n !== i))}
              class="text-lg text-slate-400">×</button
            ></span
          >{/each}
      </div>
      <div class="mt-6 flex justify-end">
        <button
          disabled={busy || generating || importing}
          onclick={() => generate('competitors')}
          class="rounded-lg bg-slate-400 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50"
          >✧ Сгенерировать заново</button
        >
      </div>
    {:else if step === 5}<p class="text-sm text-slate-500">
        Выберите нейросети, в которых хотите проверить упоминания и цитируемость по промптам. До
        пяти моделей.
      </p>
      <div class="mt-6 overflow-x-auto">
        <table class="w-full text-sm">
          <thead
            ><tr class="border-b border-slate-200"
              ><th class="py-4 text-left"
                ><label class="inline-flex items-center gap-4"
                  ><input
                    type="checkbox"
                    aria-label="Выбрать все нейросети"
                    checked={allSelected}
                    onchange={selectAll}
                    disabled={!providers.length}
                    class="model-toggle"
                  />{providers.length > 5 ? 'Все (до 5)' : 'Все'}</label
                ></th
              ><th class="px-3 py-4 text-center text-xs font-normal text-slate-400"
                >Вызовы API:<br /><strong class="mt-1 block">1 промпт</strong></th
              ><th class="px-3 py-4 text-center text-xs font-normal text-slate-400"
                >Все промпты<br /><strong class="mt-1 block">({queries.length})</strong></th
              ></tr
            ></thead
          ><tbody
            >{#each providers as p (p.id)}<tr class="border-b border-slate-200"
                ><td class="py-4"
                  ><label class="flex items-center gap-3"
                    ><input
                      type="checkbox"
                      aria-label={p.name}
                      value={p.id}
                      bind:group={ids}
                      disabled={ids.length >= 5 && !ids.includes(p.id)}
                      class="model-toggle"
                    /><span
                      class="grid size-6 shrink-0 place-items-center rounded-full bg-blue-50 text-xs font-semibold text-blue-500"
                      aria-hidden="true">{p.name.slice(0, 1)}</span
                    ><span
                      >{p.name}{#if p.answer_mode === 'deepseek_web'}<span
                          class="ml-1 text-slate-400"
                          title="Веб-поиск и источники">◎</span
                        >{/if}{#if !p.configured}<span class="mt-1 block text-xs text-amber-600"
                          >Ключ не задан</span
                        >{/if}</span
                    ></label
                  ></td
                ><td class="px-3 py-4 text-center text-slate-500">1</td><td
                  class="px-3 py-4 text-center font-semibold text-slate-500">{queries.length}</td
                ></tr
              >{/each}</tbody
          >
        </table>
      </div>
      <p class="mt-4 text-xs text-slate-400">
        Выбрано {ids.length} из {providers.length} нейросетей · В проекте {queries.length} промптов ·
        За проверку: {estimate} вызовов
      </p>
      {#if !providers.length}<p class="mt-4 text-sm text-slate-500">
          Добавьте подключения в общих настройках API. Черновик сохранён.
        </p>{/if}{#each ids.filter((id) => !providers.some((p) => p.id === id)) as missing (missing)}<label
          class="mt-3 block text-sm text-red-600"
          ><input type="checkbox" value={missing} bind:group={ids} /> Удалённая модель — снимите выбор</label
        >{/each}
    {:else}<p class="mt-4 text-sm text-slate-500">
        Проверьте настройки проекта и запустите первую проверку.
      </p>
      <div class="mt-8 space-y-2 text-xs">
        <div class="grid gap-3 rounded-lg bg-slate-100 px-5 py-4 sm:grid-cols-3">
          <span>Бренд: <strong>{brand}</strong></span><span
            >Сайт: <strong>{savedHost()}</strong></span
          ><span>Кол-во конкурентов: <strong>{competitors.length}</strong></span>
        </div>
        <div class="flex flex-wrap gap-2">
          <span class="rounded-lg bg-slate-100 px-5 py-4"
            >Выбрано: <strong>{ids.length} из {providers.length} нейросетей</strong></span
          ><span class="rounded-lg bg-slate-100 px-5 py-4"
            >В проекте: <strong>{queries.length} промптов</strong></span
          ><span class="rounded-lg bg-lime-50 px-5 py-4"
            >За проверку: <strong>{estimate} вызовов</strong></span
          >
        </div>
      </div>
      <p class="mt-4 text-xs text-slate-400">
        До {estimate} дополнительных вызовов служебной модели для оценки тональности.
      </p>
      <details class="mt-6 text-sm text-slate-500">
        <summary class="cursor-pointer">Дополнительно: выдача Яндекса</summary><label
          class="mt-4 flex items-center gap-3"
          ><input type="checkbox" bind:checked={yandex} class="size-5 accent-lime-600" />Также
          проверить выдачу Яндекса</label
        >{#if yandex}<label class="mt-3 block"
            >Регион<select bind:value={region} class={input}
              ><option value={213}>Москва</option><option value={1}>Москва и область</option><option
                value={2}>Санкт-Петербург</option
              ><option value={54}>Екатеринбург</option><option value={65}>Новосибирск</option
              ><option value={43}>Казань</option><option value={47}>Нижний Новгород</option><option
                value={39}>Ростов-на-Дону</option
              ><option value={35}>Краснодар</option><option value={239}>Сочи</option><option
                value={172}>Уфа</option
              ><option value={28}>Махачкала</option><option value={1106}>Грозный</option><option
                value={225}>Россия</option
              ></select
            ></label
          >
          <p class="mt-2 text-xs">Дополнительно {queries.length} поисков.</p>{/if}
      </details>
    {/if}
  </div>
  <footer
    class="mx-5 flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-slate-200 py-4 sm:mx-7"
  >
    <div class="flex flex-wrap gap-3">
      {#if step > 1}<button
          aria-label="Назад"
          disabled={busy || generating || importing}
          onclick={back}
          class="rounded-lg border border-slate-300 px-4 py-3 text-slate-400 disabled:opacity-40"
          >‹</button
        >{/if}{#if step < 6}<button
          disabled={busy || generating || importing}
          onclick={next}
          class="rounded-lg bg-lime-600 px-6 py-3 text-sm font-semibold text-white disabled:opacity-50"
          >✓ Далее</button
        >{:else}<button
          disabled={busy || generating || importing}
          onclick={pause}
          class="rounded-lg border border-lime-600 px-6 py-3 text-sm font-medium text-lime-600"
          >Создать проект ›</button
        ><button
          disabled={busy || generating || importing}
          onclick={start}
          class="rounded-lg bg-lime-600 px-6 py-3 text-sm font-semibold text-white disabled:opacity-50"
          >↻ Создать и запустить проверку</button
        >{/if}
    </div>
    {#if step < 6}<button
        disabled={busy || generating || importing}
        onclick={pause}
        class="text-xs text-slate-400">{id ? 'Продолжить позже' : 'Отмена'}</button
      >{/if}
  </footer>
</dialog>

<style>
  .wizard-dialog[open] {
    display: flex;
    flex-direction: column;
    height: min(820px, 95dvh);
  }
  .model-toggle {
    appearance: none;
    width: 32px;
    height: 18px;
    position: relative;
    border-radius: 999px;
    background: #cbd5e1;
    cursor: pointer;
    flex-shrink: 0;
  }
  .model-toggle::before {
    content: '';
    position: absolute;
    width: 14px;
    height: 14px;
    left: 2px;
    top: 2px;
    border-radius: 50%;
    background: white;
    transition: transform 0.15s;
  }
  .model-toggle:checked {
    background: #65a30d;
  }
  .model-toggle:checked::before {
    transform: translateX(14px);
  }
  .model-toggle:focus-visible {
    outline: 2px solid #65a30d;
    outline-offset: 3px;
  }
  .model-toggle:disabled {
    opacity: 0.4;
    cursor: default;
  }
</style>
