<script lang="ts">
  import { untrack } from 'svelte';
  import type { PublicProvider } from '$lib/types';

  type Data = { providers: PublicProvider[]; loadError: string };
  let { data }: { data: Data } = $props();
  let connections = $state<PublicProvider[]>(untrack(() => data.providers));
  let editing = $state<string | null>(null);
  let name = $state('');
  let endpoint = $state('');
  let model = $state('');
  let scope = $state('GIGACHAT_API_PERS');
  let apiKey = $state('');
  let busy = $state(false);
  let error = $state(untrack(() => data.loadError));
  let notice = $state('');
  let preset = $derived(editing === 'gigachat' || editing === 'deepseek');

  function resetForm() {
    editing = null;
    name = '';
    endpoint = '';
    model = '';
    scope = 'GIGACHAT_API_PERS';
    apiKey = '';
    error = '';
  }

  function edit(connection: PublicProvider) {
    editing = connection.id;
    name = connection.name;
    endpoint = connection.endpoint ?? '';
    model = connection.model;
    scope = connection.scope ?? 'GIGACHAT_API_PERS';
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
    const payload: Record<string, string> = editing === 'gigachat'
      ? { scope }
      : editing === 'deepseek'
        ? {}
        : { name: name.trim(), kind: 'openai', endpoint: endpoint.trim(), model: model.trim() };
    if (key) payload.api_key = key;
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
    const isPreset = connection.id === 'gigachat' || connection.id === 'deepseek';
    if (!confirm(isPreset
      ? `Удалить сохранённый ключ «${connection.name}»? Ключ из переменной среды может сохранить подключение активным.`
      : `Удалить подключение «${connection.name}» и его ключ?`)) return;
    busy = true;
    error = '';
    notice = '';
    try {
      const response = await fetch(`/api/providers/${encodeURIComponent(connection.id)}`, { method: 'DELETE' });
      const value = await readJson(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось удалить подключение'));
      if (editing === connection.id) resetForm();
      await refresh();
      notice = isPreset ? 'Сохранённый ключ сброшен' : 'Подключение удалено';
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Не удалось удалить подключение';
    } finally { busy = false; }
  }
</script>

<svelte:head><title>ИИ-трекинг · Настройки API</title></svelte:head>

<main class="mx-auto max-w-7xl px-4 pb-12 sm:px-6 lg:px-8">
  <section class="max-w-3xl py-12 sm:py-16">
    <p class="mb-4 text-xs font-extrabold tracking-[0.19em] text-emerald-700 uppercase">Модели и ключи</p>
    <h1 class="text-4xl leading-tight font-bold tracking-tight text-slate-900 sm:text-6xl">Подключения API</h1>
    <p class="mt-5 text-base leading-7 text-slate-600 sm:text-lg">Настройте GigaChat, DeepSeek или добавьте OpenAI-совместимую модель. Ключи сохраняет Python в системном хранилище и не показывает после сохранения.</p>
  </section>

  {#if error}<p role="alert" class="mb-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>{/if}
  {#if notice}<p role="status" class="mb-6 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</p>{/if}

  <div class="grid items-start gap-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(330px,0.95fr)]">
    <section class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8" aria-labelledby="connections-title">
      <div class="mb-6 flex items-start gap-3"><span class="step-mark">01</span><div><h2 id="connections-title" class="text-xl font-bold">Доступные подключения</h2><p class="text-sm text-slate-500">Ключ можно заменить или сбросить в любой момент</p></div></div>
      {#if connections.length}
        <div class="space-y-3">
          {#each connections as connection (connection.id)}
            <article class="rounded-xl border border-slate-200 p-4 sm:p-5">
              <div class="flex flex-wrap items-start justify-between gap-3"><div><h3 class="text-lg font-bold text-slate-900">{connection.name}</h3><p class="mt-1 text-sm text-slate-600">{connection.model}</p></div><span class:hit-badge={connection.configured} class:miss-badge={!connection.configured} class="rounded-full px-3 py-1 text-xs font-bold">{connection.configured ? 'Готово к проверке' : 'Нужен API-ключ'}</span></div>
              {#if connection.endpoint}<p class="mt-3 break-all text-xs text-slate-500">{connection.endpoint}</p>{/if}
              <div class="mt-4 flex flex-wrap gap-3 text-sm font-semibold">
                <button type="button" class="text-emerald-700 hover:underline" disabled={busy} onclick={() => edit(connection)} aria-label={`Настроить ${connection.name}`}>Настроить</button>
                {#if connection.id === 'gigachat' || connection.id === 'deepseek'}
                  {#if connection.configured}<button type="button" class="text-slate-500 hover:underline" disabled={busy} onclick={() => remove(connection)} aria-label={`Сбросить ключ ${connection.name}`}>Сбросить ключ</button>{/if}
                {:else}
                  <button type="button" class="text-red-600 hover:underline" disabled={busy} onclick={() => remove(connection)} aria-label={`Удалить ${connection.name}`}>Удалить</button>
                {/if}
              </div>
            </article>
          {/each}
        </div>
      {:else}
        <p class="rounded-xl bg-slate-50 p-5 text-sm text-slate-600">Подключения пока не загружены. Проверьте Python API и обновите страницу.</p>
      {/if}
    </section>

    <section class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8" aria-labelledby="form-title">
      <div class="mb-6 flex items-start gap-3"><span class="step-mark">02</span><div><h2 id="form-title" class="text-xl font-bold">{editing ? `Настроить ${name}` : 'Добавить подключение'}</h2><p class="text-sm text-slate-500">OpenAI Chat Completions API</p></div></div>
      <form onsubmit={save} novalidate class="space-y-5">
        <div><label class="field-label" for="connection-name">Название подключения</label><input id="connection-name" class="field-input" type="text" maxlength="100" bind:value={name} disabled={preset} placeholder="Например, Моя модель" /></div>
        <div><label class="field-label" for="endpoint">Адрес API</label><input id="endpoint" class="field-input" type="url" maxlength="2048" bind:value={endpoint} disabled={preset} placeholder="https://api.example.com/v1/chat/completions" /><p class="field-help">Публичный HTTPS-адрес, заканчивающийся на /chat/completions. Ключ передаётся этому API.</p></div>
        <div><label class="field-label" for="model">Модель</label><input id="model" class="field-input" type="text" maxlength="100" bind:value={model} disabled={preset} placeholder="Название модели в API" /></div>
        {#if editing === 'gigachat'}<div><label class="field-label" for="scope">Область доступа GigaChat</label><select id="scope" class="field-input" bind:value={scope}><option value="GIGACHAT_API_PERS">Персональный</option><option value="GIGACHAT_API_B2B">Бизнес</option><option value="GIGACHAT_API_CORP">Корпоративный</option></select></div>{/if}
        <div><label class="field-label" for="api-key">API-ключ</label><input id="api-key" class="field-input" type="password" autocomplete="new-password" bind:value={apiKey} placeholder={editing ? 'Оставьте пустым, чтобы сохранить прежний' : 'Введите ключ'} /><p class="field-help">При редактировании пустое поле оставляет сохранённый ключ. После сохранения ключ здесь не отображается.</p></div>
        <div class="flex flex-wrap gap-3"><button type="submit" class="rounded-xl bg-emerald-700 px-5 py-3 font-bold text-white hover:bg-emerald-800 disabled:opacity-60" disabled={busy}>{busy ? 'Сохраняем…' : 'Сохранить подключение'}</button>{#if editing}<button type="button" class="rounded-xl border border-slate-200 px-5 py-3 font-semibold text-slate-600" onclick={resetForm} disabled={busy}>Отмена</button>{/if}</div>
      </form>
    </section>
  </div>
  <aside class="mt-6 rounded-xl bg-emerald-50 p-5 text-sm leading-6 text-emerald-950">Встроенное подключение можно вернуть к ключу из переменной среды: сбросьте сохранённый ключ. Подключения и ключи хранятся локально на этом компьютере.</aside>
</main>
