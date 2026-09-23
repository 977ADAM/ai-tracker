<script lang="ts">
  import { untrack } from 'svelte';
  import type { FormConfig, PublicProvider } from '$lib/types';

  type Data = { providers: PublicProvider[]; form?: FormConfig | null; loadError: string };
  let { data }: { data: Data } = $props();
  let connections = $state<PublicProvider[]>(untrack(() => data.providers));
  let editing = $state<string | null>(null);
  let name = $state('');
  let endpoint = $state('');
  let model = $state('');
  let scope = $state(untrack(() => data.form?.scope_options[0]?.value ?? ''));
  let apiKey = $state('');
  let busy = $state(false);
  let error = $state(untrack(() => data.loadError));
  let notice = $state('');
  let active = $derived(connections.find((connection) => connection.id === editing));
  let editableFields = $derived(active?.editable_fields ?? data.form?.new_provider_fields ?? []);

  function resetForm() {
    editing = null;
    name = '';
    endpoint = '';
    model = '';
    scope = data.form?.scope_options[0]?.value ?? '';
    apiKey = '';
    error = '';
  }

  function edit(connection: PublicProvider) {
    editing = connection.id;
    name = connection.name;
    endpoint = connection.endpoint ?? '';
    model = connection.model;
    scope = connection.scope ?? data.form?.scope_options[0]?.value ?? '';
    apiKey = '';
    error = '';
    notice = '';
  }

  async function readJson(response: Response): Promise<unknown> {
    try { return await response.json(); }
    catch { throw new Error('Некорректный ответ сервиса'); }
  }

  function detail(value: unknown, fallback: string): string {
    if (value && typeof value === 'object' && 'detail' in value && typeof value.detail === 'string') return value.detail;
    return fallback;
  }

  async function refresh() {
    const response = await fetch('/api/providers');
    const value = await readJson(response);
    if (!response.ok || !Array.isArray(value)) throw new Error(detail(value, 'Не удалось загрузить подключения'));
    connections = value as PublicProvider[];
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    notice = '';
    const key = apiKey.trim();
    apiKey = '';
    const values: Record<string, string> = { name, endpoint, model, scope, api_key: key };
    const payload = Object.fromEntries(editableFields.filter((field) => field !== 'api_key' || key).map((field) => [field, values[field]]));
    busy = true;
    try {
      const response = await fetch(editing ? `/api/providers/${encodeURIComponent(editing)}` : '/api/providers', {
        method: editing ? 'PUT' : 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload)
      });
      const value = await readJson(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось сохранить подключение'));
      await refresh();
      resetForm();
      notice = 'Подключение сохранено';
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Не удалось сохранить подключение';
    } finally { busy = false; }
  }

  async function remove(connection: PublicProvider) {
    if (!confirm(connection.delete_prompt)) return;
    busy = true;
    error = '';
    notice = '';
    try {
      const response = await fetch(`/api/providers/${encodeURIComponent(connection.id)}`, { method: 'DELETE' });
      const value = await readJson(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось удалить подключение'));
      if (editing === connection.id) resetForm();
      await refresh();
      notice = connection.delete_success;
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Не удалось удалить подключение';
    } finally { busy = false; }
  }
</script>

<svelte:head><title>ИИ-трекинг · Настройки API</title></svelte:head>

<main class="mx-auto max-w-[1920px] px-4 pb-16 sm:px-6 lg:px-8">
  <nav aria-label="Хлебные крошки" class="flex items-center gap-2 py-6 text-xs font-medium text-muted">
    <a href="/" class="hover:text-accent focus-visible:outline-2 focus-visible:outline-accent">Проверка</a>
    <span aria-hidden="true">/</span>
    <span class="text-ink">Настройки API</span>
  </nav>

  <section class="rounded-3xl border border-line bg-white px-6 py-9 shadow-sm sm:px-10 sm:py-11">
    <p class="text-xs font-bold tracking-[0.16em] text-accent uppercase">Управление моделями</p>
    <h1 class="mt-4 text-3xl font-bold tracking-tight sm:text-4xl">Подключения API</h1>
    <p class="mt-4 max-w-3xl text-sm leading-7 text-muted sm:text-base">Настройте GigaChat, DeepSeek или добавьте OpenAI-совместимую модель. Ключи сохраняет Python в системном хранилище и не показывает после сохранения.</p>
  </section>

  {#if error}<p role="alert" class="mt-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</p>{/if}
  {#if notice}<p role="status" class="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</p>{/if}

  <div class="mt-8 grid items-start gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(340px,0.9fr)]">
    <section class="overflow-hidden rounded-3xl border border-line bg-white shadow-sm" aria-labelledby="connections-title">
      <div class="border-b border-line px-6 py-5 sm:px-8">
        <p class="text-xs font-bold tracking-[0.14em] text-accent uppercase">Шаг 1 · Выберите модель</p>
        <h2 id="connections-title" class="mt-1 text-xl font-bold tracking-tight sm:text-2xl">Доступные подключения</h2>
        <p class="mt-1 text-sm text-muted">Ключ можно заменить или сбросить в любой момент.</p>
      </div>
      {#if connections.length}
        <div class="divide-y divide-line">
          {#each connections as connection (connection.id)}
            <article class="px-6 py-5 sm:px-8">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div class="min-w-0"><h3 class="text-lg font-bold">{connection.name}</h3><p class="mt-1 text-sm text-muted">{connection.model}</p></div>
                <span class={`rounded-full px-3 py-1 text-xs font-semibold ${connection.configured ? 'bg-accent-soft text-accent-dark' : 'bg-amber-50 text-amber-800'}`}>{connection.status_label}</span>
              </div>
              {#if connection.endpoint}<p class="mt-3 break-all rounded-lg bg-canvas px-3 py-2 text-xs text-muted">{connection.endpoint}</p>{/if}
              <div class="mt-4 flex flex-wrap gap-4 text-sm font-semibold">
                <button type="button" class="rounded-sm text-accent hover:text-accent-dark hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50" disabled={busy} onclick={() => edit(connection)} aria-label={`Настроить ${connection.name}`}>Настроить</button>
                {#if (connection.can_reset && connection.configured) || connection.can_delete}<button type="button" class="rounded-sm text-rose-700 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-600 disabled:opacity-50" disabled={busy} onclick={() => remove(connection)} aria-label={`${connection.delete_label} ${connection.name}`}>{connection.delete_label}</button>{/if}
              </div>
            </article>
          {/each}
        </div>
      {:else}
        <p class="px-6 py-8 text-sm text-muted sm:px-8">Подключения пока не загружены. Проверьте Python API и обновите страницу.</p>
      {/if}
    </section>

    <section class="overflow-hidden rounded-3xl border border-line bg-white shadow-sm" aria-labelledby="form-title">
      <div class="border-b border-line px-6 py-5 sm:px-8">
        <p class="text-xs font-bold tracking-[0.14em] text-accent uppercase">Шаг 2 · Параметры доступа</p>
        <h2 id="form-title" class="mt-1 text-xl font-bold tracking-tight sm:text-2xl">{editing ? `Настроить ${name}` : 'Добавить подключение'}</h2>
        <p class="mt-1 text-sm text-muted">OpenAI Chat Completions API</p>
      </div>
      <form onsubmit={save} novalidate class="space-y-5 px-6 py-7 sm:px-8">
        <div>
          <label class="mb-2 block text-sm font-semibold" for="connection-name">Название подключения</label>
          <input id="connection-name" class="block w-full rounded-xl border border-line bg-canvas/50 px-4 py-3 text-sm text-ink outline-none transition placeholder:text-muted/70 focus:border-accent focus:bg-white focus:ring-4 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500" type="text" bind:value={name} disabled={!editableFields.includes('name')} placeholder="Например, Моя модель" />
        </div>
        <div>
          <label class="mb-2 block text-sm font-semibold" for="endpoint">Адрес API</label>
          <input id="endpoint" class="block w-full rounded-xl border border-line bg-canvas/50 px-4 py-3 text-sm text-ink outline-none transition placeholder:text-muted/70 focus:border-accent focus:bg-white focus:ring-4 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500" type="url" bind:value={endpoint} disabled={!editableFields.includes('endpoint')} placeholder="https://api.example.com/v1/chat/completions" />
          <p class="mt-2 text-xs leading-5 text-muted">Публичный HTTPS-адрес, заканчивающийся на /chat/completions. Ключ передаётся этому API.</p>
        </div>
        <div>
          <label class="mb-2 block text-sm font-semibold" for="model">Модель</label>
          <input id="model" class="block w-full rounded-xl border border-line bg-canvas/50 px-4 py-3 text-sm text-ink outline-none transition placeholder:text-muted/70 focus:border-accent focus:bg-white focus:ring-4 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500" type="text" bind:value={model} disabled={!editableFields.includes('model')} placeholder="Название модели в API" />
        </div>
        {#if editableFields.includes('scope')}
          <div>
            <label class="mb-2 block text-sm font-semibold" for="scope">Область доступа GigaChat</label>
            <select id="scope" class="block w-full rounded-xl border border-line bg-canvas/50 px-4 py-3 text-sm text-ink outline-none transition focus:border-accent focus:bg-white focus:ring-4 focus:ring-accent/15" bind:value={scope}>{#each data.form?.scope_options ?? [] as option}<option value={option.value}>{option.label}</option>{/each}</select>
          </div>
        {/if}
        <div>
          <label class="mb-2 block text-sm font-semibold" for="api-key">API-ключ</label>
          <input id="api-key" class="block w-full rounded-xl border border-line bg-canvas/50 px-4 py-3 text-sm text-ink outline-none transition placeholder:text-muted/70 focus:border-accent focus:bg-white focus:ring-4 focus:ring-accent/15" type="password" autocomplete="new-password" bind:value={apiKey} placeholder={editing ? 'Оставьте пустым, чтобы сохранить прежний' : 'Введите ключ'} />
          <p class="mt-2 text-xs leading-5 text-muted">При редактировании пустое поле оставляет сохранённый ключ. После сохранения ключ здесь не отображается.</p>
        </div>
        <div class="flex flex-wrap gap-3 border-t border-line pt-5">
          <button type="submit" class="min-h-11 rounded-xl bg-accent px-5 py-3 text-sm font-bold text-white transition hover:bg-accent-dark focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60" disabled={busy || !data.form}>{busy ? 'Сохраняем…' : 'Сохранить подключение'}</button>
          {#if editing}<button type="button" class="min-h-11 rounded-xl border border-line px-5 py-3 text-sm font-semibold text-muted transition hover:bg-canvas focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent" onclick={resetForm} disabled={busy}>Отмена</button>{/if}
        </div>
      </form>
    </section>
  </div>

  <aside class="mt-8 rounded-2xl border border-line bg-accent-soft px-6 py-5 text-sm leading-6 text-ink">Встроенное подключение можно вернуть к ключу из переменной среды: сбросьте сохранённый ключ. Подключения и ключи хранятся локально на этом компьютере.</aside>
</main>
