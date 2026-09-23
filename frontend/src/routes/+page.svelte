<script lang="ts">
  import { untrack } from 'svelte';
  import type { CheckResponse, PublicProvider } from '$lib/types';

  type Data = { providers: PublicProvider[]; loadError: string };
  let { data }: { data: Data } = $props();

  const initial = untrack(() => data.providers.find((provider) => provider.id === 'gigachat' && provider.configured)
    ?? data.providers.find((provider) => provider.configured));
  let selected = $state<string[]>(initial ? [initial.id] : []);
  let brand = $state('');
  let domain = $state('');
  let promptsText = $state('');
  let prompts = $derived(promptsText.split(/\r?\n/).map((prompt) => prompt.trim()).filter(Boolean));
  let loading = $state(false);
  let error = $state(untrack(() => data.loadError));
  let report = $state<CheckResponse | null>(null);

  function toggleProvider(id: string) {
    selected = selected.includes(id) ? selected.filter((value) => value !== id) : [...selected, id];
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    if (!selected.length || selected.length > 5) { error = 'Выберите от 1 до 5 настроенных моделей'; return; }
    if (!brand.trim()) { error = 'Укажите название бренда'; return; }
    if (!prompts.length || prompts.length > 20) { error = 'Укажите от 1 до 20 вопросов'; return; }
    if (prompts.some((prompt) => prompt.length > 500)) { error = 'Каждый вопрос должен быть не длиннее 500 символов'; return; }
    loading = true;
    report = null;
    try {
      const response = await fetch('/api/check', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ brand: brand.trim(), domain: domain.trim(), prompts, provider_ids: selected })
      });
      const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : 'Не удалось выполнить проверку');
      report = value as CheckResponse;
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Не удалось выполнить проверку';
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head><title>ИИ-трекинг · Проверка бренда</title></svelte:head>

<main class="mx-auto max-w-7xl px-4 pb-12 sm:px-6 lg:px-8">
  <section class="max-w-3xl py-12 sm:py-16">
    <p class="mb-4 text-xs font-extrabold tracking-[0.19em] text-emerald-700 uppercase">Сравнение ответов ИИ</p>
    <h1 class="text-4xl leading-tight font-bold tracking-tight text-slate-900 sm:text-6xl">Узнайте, упоминает ли ИИ ваш бренд</h1>
    <p class="mt-5 text-base leading-7 text-slate-600 sm:text-lg">Задайте вопросы клиентов, выберите модели и посмотрите, где в их ответах встречается название бренда.</p>
  </section>

  <div class="grid items-start gap-6 lg:grid-cols-[minmax(330px,0.9fr)_minmax(0,1.1fr)]">
    <section class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8" aria-labelledby="check-title">
      <div class="mb-7 flex items-start gap-3"><span class="step-mark">01</span><div><h2 id="check-title" class="text-xl font-bold">Настройте проверку</h2><p class="text-sm text-slate-500">До 20 вопросов за запуск</p></div></div>
      <form onsubmit={submit} novalidate class="space-y-6">
        <fieldset>
          <legend class="mb-2 text-sm font-bold text-slate-700">Модели для проверки</legend>
          <div class="grid gap-2">
            {#each data.providers as provider (provider.id)}
              <label class:opacity-60={!provider.configured} class="flex cursor-pointer items-center gap-3 rounded-xl border border-slate-200 px-4 py-3">
                <input type="checkbox" class="accent-emerald-700" checked={selected.includes(provider.id)} disabled={!provider.configured} onchange={() => toggleProvider(provider.id)} />
                <span class="font-semibold">{provider.name}</span>
                <span class="ml-auto text-right text-xs text-slate-500">{provider.configured ? provider.model : 'Нужен API-ключ'}</span>
              </label>
            {/each}
          </div>
          <p class="mt-2 text-xs text-slate-500">Выберите от 1 до 5 моделей. <a class="font-semibold text-emerald-700 underline" href="/settings">Настроить API</a></p>
        </fieldset>
        <div><label for="brand" class="field-label">Название бренда <span class="text-amber-600">*</span></label><input id="brand" class="field-input" type="text" maxlength="100" bind:value={brand} placeholder="Например, Ромашка" /><p class="field-help">Ищем именно это название в тексте ответа</p></div>
        <div><label for="domain" class="field-label">Сайт <span class="font-normal text-slate-400">необязательно</span></label><input id="domain" class="field-input" type="text" maxlength="253" bind:value={domain} placeholder="example.ru" /><p class="field-help">Покажем для контекста; ссылки пока не проверяем</p></div>
        <div><div class="flex justify-between"><label for="prompts" class="field-label">Вопросы клиентов <span class="text-amber-600">*</span></label><span class="text-xs text-slate-500">{prompts.length} / 20</span></div><textarea id="prompts" class="field-input min-h-48 resize-y" bind:value={promptsText} placeholder="Как выбрать сервис доставки цветов?&#10;Где заказать букет сегодня?"></textarea><p class="field-help">Каждый вопрос — с новой строки, до 500 символов</p></div>
        {#if error}<p role="alert" class="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>{/if}
        <button type="submit" disabled={loading} class="w-full rounded-xl bg-emerald-700 px-5 py-4 text-left font-bold text-white hover:bg-emerald-800 disabled:opacity-60">{loading ? 'Проверяем…' : 'Проверить бренд'} <span class="float-right">↗</span></button>
      </form>
    </section>

    <section class="min-h-96 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8" aria-labelledby="report-title">
      <div class="mb-7 flex items-start gap-3"><span class="step-mark">02</span><div><h2 id="report-title" class="text-xl font-bold">Отчёт</h2><p class="text-sm text-slate-500">{report ? `Бренд: ${report.brand}` : 'Результаты появятся здесь'}</p></div></div>
      {#if loading}
        <div class="empty-state"><p class="font-semibold">Спрашиваем модели…</p><p class="mt-2 text-sm text-slate-500">Проверяем вопросы по очереди.</p></div>
      {:else if report}
        <p class="mb-5 text-xs text-slate-500">{report.domain ? `Сайт для контекста: ${report.domain}` : 'Сайт не указан'}</p>
        <div class="space-y-7">
          {#each report.checks as check (check.provider_id)}
            <section class="provider-report space-y-3 border-t border-slate-200 pt-5" aria-label={`Результаты ${check.provider_name}`}>
              <h3 class="text-lg font-bold text-slate-900">{check.provider_name}</h3>
              <p class="text-xs text-slate-600">Упоминаний: {check.summary.mentioned} из {check.summary.successful} успешных · Ошибок: {check.summary.failed}</p>
              {#each check.results as result, index (`${check.provider_id}-${index}`)}
                <article class="rounded-xl border border-slate-200 p-4">
                  <div class="flex flex-wrap items-start justify-between gap-2"><h4 class="text-sm font-semibold">{result.prompt}</h4><span class:error-badge={!!result.error} class:hit-badge={result.mentioned === true} class:miss-badge={result.mentioned === false} class="rounded-full px-2.5 py-1 text-xs font-bold">{result.error ? 'Ошибка' : result.mentioned ? 'Бренд упомянут' : 'Нет упоминания'}</span></div>
                  <p class="mt-4 text-[10px] font-bold tracking-widest text-slate-400 uppercase">{result.error ? 'Причина' : 'Ответ модели'}</p>
                  <p class="mt-1 max-h-60 overflow-auto text-sm leading-6 wrap-anywhere whitespace-pre-wrap text-slate-600">{result.error || result.answer || ''}</p>
                </article>
              {/each}
            </section>
          {/each}
        </div>
      {:else}
        <div class="empty-state"><span class="text-5xl text-emerald-300">◎</span><p class="mt-4 font-semibold">Пока нет проверки</p><p class="mt-2 max-w-xs text-sm text-slate-500">Выберите модели, введите бренд и вопросы, чтобы сравнить ответы.</p></div>
      {/if}
    </section>
  </div>

  <aside class="mt-6 rounded-xl bg-emerald-50 p-5 text-sm text-emerald-950"><strong>Как читать результат</strong><p class="mt-2 leading-6">Это срез на момент проверки через API выбранных моделей. Ответы ИИ могут меняться. Мы не проверяем ссылки, поисковую выдачу или видимость сайта в интернете.</p></aside>
</main>
