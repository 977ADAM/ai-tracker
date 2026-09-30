<script lang="ts">
  import { untrack } from 'svelte';
  import type { FormConfig, PublicProvider } from '$lib/types';
  import { estimateUpper, MAX_CONNECTIONS, parseServices, validateSeoForm } from '$lib/seo-form';
  import type { SeoFormInput } from '$lib/seo-form';

  let { providers, form, disabled = false, error = '', onSubmit, onError = () => {} }:
    { providers: PublicProvider[]; form: FormConfig | null; disabled?: boolean; error?: string;
      onSubmit: (input: SeoFormInput) => void | Promise<void>; onError?: (message: string) => void } = $props();

  const field = 'block min-h-11 w-full rounded-xl border border-line bg-canvas/50 px-4 py-3 text-sm text-ink outline-none focus:border-accent disabled:opacity-60';
  const label = 'mb-2 block text-sm font-semibold text-ink';
  const hint = 'mt-2 text-xs leading-5 text-muted';

  function defaultConnections(): string[] {
    const defaults = form?.default_provider_ids ?? [];
    const available = new Set(providers.filter((provider) => provider.configured).map((provider) => provider.id));
    return defaults.filter((id) => available.has(id)).slice(0, MAX_CONNECTIONS);
  }

  let url = $state('');
  let sphere = $state('');
  let seed1 = $state('');
  let seed2 = $state('');
  let seed3 = $state('');
  let servicesText = $state('');
  // The default connections are read once: a later configuration refresh must
  // not silently change the model list of a form the user already edited.
  let selected = $state<string[]>(untrack(defaultConnections));
  let busy = $state(false);
  let problem = $state('');

  const seeds = $derived([seed1, seed2, seed3]);
  const selectedConnections = $derived(providers.filter((provider) => selected.includes(provider.id)));
  const upper = $derived(estimateUpper(selectedConnections.length));
  const blocked = $derived(disabled || !form);

  function toggleConnection(id: string) {
    if (selected.includes(id)) selected = selected.filter((value) => value !== id);
    else if (selected.length < MAX_CONNECTIONS) selected = [...selected, id];
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    problem = '';
    const input: SeoFormInput = {
      url, sphere, seeds, services: parseServices(servicesText), connectionIds: selected
    };
    const found = validateSeoForm(input);
    if (found) { problem = found; onError(found); return; }
    busy = true;
    try {
      await onSubmit(input);
    } catch (cause) {
      // The page owns the server message; a missing one falls back to a safe sentence.
      problem = cause instanceof Error && cause.message
        ? cause.message : 'Не удалось запустить анализ. Попробуйте ещё раз.';
      onError(problem);
    } finally {
      busy = false;
    }
  }
</script>

<section class="mt-8 overflow-hidden rounded-3xl border border-line bg-white shadow-sm" aria-labelledby="seo-form-title">
  <form onsubmit={submit} novalidate class="space-y-7 px-6 py-7 sm:px-8">
    <h2 id="seo-form-title" class="text-2xl font-bold tracking-tight">Параметры анализа</h2>

    <fieldset class="grid gap-6 lg:grid-cols-2">
      <legend class="sr-only">Сайт и ключевые запросы</legend>

      <div class="lg:col-span-2">
        <label for="seo-url" class={label}>
          Адрес главной страницы
          <span class="text-rose-600">*</span>
        </label>
        <input id="seo-url" type="url" class={field} placeholder="https://example.ru" bind:value={url} disabled={blocked || busy} />
        <p class={hint}>Схема обязательна: анализ обходит только этот хост и его поддомены.</p>
      </div>

      <div class="lg:col-span-2">
        <label for="seo-sphere" class={label}>
          Сфера бизнеса
          <span class="text-rose-600">*</span>
        </label>
        <input id="seo-sphere" type="text" class={field} placeholder="Доставка цветов и подарков" bind:value={sphere} disabled={blocked || busy} />
      </div>

      <div class="lg:col-span-2 grid gap-4 sm:grid-cols-3">
        <div>
          <label for="seo-seed-1" class={label}>Первый ключевой запрос <span class="text-rose-600">*</span></label>
          <input id="seo-seed-1" type="text" class={field} bind:value={seed1} disabled={blocked || busy} />
        </div>
        <div>
          <label for="seo-seed-2" class={label}>Второй ключевой запрос <span class="text-rose-600">*</span></label>
          <input id="seo-seed-2" type="text" class={field} bind:value={seed2} disabled={blocked || busy} />
        </div>
        <div>
          <label for="seo-seed-3" class={label}>Третий ключевой запрос <span class="text-rose-600">*</span></label>
          <input id="seo-seed-3" type="text" class={field} bind:value={seed3} disabled={blocked || busy} />
        </div>
        <p class={`${hint} sm:col-span-3`}>Три разных запроса: по ним в Яндексе ищутся конкуренты.</p>
      </div>

      <div class="lg:col-span-2">
        <label for="seo-services" class={label}>
          Услуги
          <span class="text-rose-600">*</span>
        </label>
        <textarea
          id="seo-services"
          class={`${field} min-h-40 resize-y leading-6`}
          bind:value={servicesText}
          disabled={blocked || busy}
        ></textarea>
        <p class={hint}>По одной услуге в строке. Не меньше одной; введённые услуги остаются первыми в списке.</p>
      </div>
    </fieldset>

    <fieldset class="border-t border-line pt-6">
      <legend class="mb-3 text-sm font-semibold text-ink">Модели для проверки</legend>
      <p class="mb-4 max-w-3xl text-xs leading-5 text-muted">
        Ответы выбранных моделей проверяются на упоминание названия компании и её домена. От одного до {MAX_CONNECTIONS} подключений.
      </p>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {#each providers as provider (provider.id)}
          <label class:opacity-60={!provider.configured} class="flex cursor-pointer items-start gap-3 rounded-xl border border-line bg-white px-4 py-3 hover:border-accent/50">
            <input
              type="checkbox"
              class="mt-1 size-4 accent-accent"
              checked={selected.includes(provider.id)}
              disabled={!provider.configured || blocked || busy}
              onchange={() => toggleConnection(provider.id)}
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

    <div class="border-t border-line pt-6" aria-label="Оценка вызовов">
      <p class="text-sm leading-6 text-ink">
        Верхняя оценка: не больше
        <span class="font-semibold" data-estimate-search>{upper.searchUpper}</span>
        поисковых запросов в Яндекс (3 ключевых + до {upper.generatedLimit} сгенерированных) и не больше
        <span class="font-semibold" data-estimate-model>{upper.modelUpper}</span>
        запросов к моделям за прогон, независимо от числа подключений.
      </p>
      <ul class="mt-3 space-y-1 text-xs leading-5 text-muted" aria-label="Предупреждения о прогоне">
        <li>Прогон ведут агенты: супервизор передаёт работу специалистам, и число шагов зависит от модели — эта часть в оценку выше не входит и заранее не тарифицируется.</li>
        <li>Служебные шаги — обход сайта, поиск конкурентов, генерация запросов и текст выводов — используют отдельно настроенную LLM.</li>
        <li>Прогон создаёт платные вызовы: тарифы Яндекса и моделей различаются.</li>
        <li>Поиск Яндекса работает в отложенном режиме, поэтому прогон может занять от минут до часов.</li>
      </ul>
    </div>

    {#if problem || error}
      <p role="alert" class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
        {problem || error}
      </p>
    {/if}

    <div class="flex flex-wrap items-center justify-between gap-4 border-t border-line pt-6">
      <p class="max-w-xl text-xs leading-5 text-muted">
        Один шаг: заполните форму и запустите анализ. Результат сохранится в SEO-истории.
      </p>
      <button
        type="submit"
        disabled={busy || blocked}
        class="inline-flex min-h-12 items-center gap-3 rounded-xl bg-accent px-6 py-3 text-sm font-bold text-white disabled:opacity-60"
      >
        {busy ? 'Запускаем…' : 'Запустить анализ'}
        <span aria-hidden="true">↗</span>
      </button>
    </div>
  </form>
</section>
