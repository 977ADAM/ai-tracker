<script lang="ts">
  import { invalidateAll } from '$app/navigation';
  import type { SettingsProvider } from '$lib/types';

  type PanelData = { settingsProviders?: SettingsProvider[]; loadError: string };
  let { data }: { data: PanelData } = $props();

  type DraftModel = { id: string | null; model: string; name: string };
  type Draft = { name: string; endpoint: string; apiKey: string; models: DraftModel[]; advanced: boolean };
  type Kind = 'error' | 'notice';
  /** `form: true` belongs to the creation card; otherwise it belongs to a provider. */
  type Feedback = { kind: Kind; text: string; providerId: string | null; form: boolean };

  const SETTINGS_PATH = '/api/providers/settings';

  const field = 'block w-full min-h-11 rounded-lg border border-shell-line bg-shell-inset px-3.5 py-2.5 text-sm text-shell-ink outline-none transition placeholder:text-shell-muted/80 focus:border-shell-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shell-accent disabled:opacity-60';
  const label = 'mb-2 block text-xs font-semibold text-shell-ink';
  const hint = 'mt-2 text-xs leading-5 text-shell-muted';
  const quiet = 'min-h-11 rounded-lg px-4 py-2.5 text-sm font-semibold text-shell-muted transition hover:bg-white/5 hover:text-shell-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shell-accent disabled:opacity-50';
  const primary = 'min-h-11 rounded-lg bg-shell-ink px-5 py-2.5 text-sm font-bold text-shell-card transition hover:bg-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shell-accent disabled:opacity-60';

  function emptyModel(): DraftModel {
    return { id: null, model: '', name: '' };
  }

  function emptyDraft(): Draft {
    return { name: '', endpoint: '', apiKey: '', models: [emptyModel()], advanced: false };
  }

  let providers = $derived(data.settingsProviders ?? []);
  let editing = $state<string | null>(null);
  let creating = $state(false);
  let draft = $state<Draft>(emptyDraft());
  let busy = $state(false);
  let feedback = $state<Feedback | null>(null);

  let onCard = $derived(feedback !== null && !feedback.form);
  let detached = $derived(
    onCard && !providers.some((provider) => provider.id === feedback!.providerId) ? feedback : null
  );
  let attached = $derived(onCard && !detached ? feedback : null);

  function modelCountLabel(count: number): string {
    const tens = count % 100;
    const ones = count % 10;
    if (ones === 1 && tens !== 11) return `${count} модель`;
    if (ones >= 2 && ones <= 4 && (tens < 12 || tens > 14)) return `${count} модели`;
    return `${count} моделей`;
  }

  function readJson(response: Response): Promise<unknown> {
    return response.json().catch(() => {
      throw new Error('Некорректный ответ сервиса');
    });
  }

  function detail(value: unknown, fallback: string): string {
    if (value && typeof value === 'object' && 'detail' in value && typeof value.detail === 'string') return value.detail;
    return fallback;
  }

  function startEdit(provider: SettingsProvider) {
    creating = false;
    editing = provider.id;
    feedback = null;
    draft = {
      name: provider.name,
      endpoint: provider.endpoint,
      apiKey: '',
      models: provider.models.map((model) => ({ id: model.id, model: model.model, name: model.name })),
      advanced: false
    };
  }

  function startCreate() {
    editing = null;
    creating = true;
    feedback = null;
    draft = { ...emptyDraft(), advanced: true };
  }

  function closeDraft() {
    editing = null;
    creating = false;
    draft = emptyDraft();
    feedback = null;
  }

  function addModel() {
    draft.models = [...draft.models, emptyModel()];
  }

  function removeModel(index: number) {
    // A provider must always keep at least one model.
    if (draft.models.length < 2) return;
    draft.models = draft.models.filter((_, position) => position !== index);
  }

  function payload(): Record<string, unknown> {
    const models = draft.models.map((row) => {
      const entry: Record<string, string> = { model: row.model.trim(), name: row.name.trim() };
      if (row.id) entry.id = row.id;
      return entry;
    });
    const body: Record<string, unknown> = { name: draft.name.trim(), endpoint: draft.endpoint.trim(), models };
    // An omitted key means "keep the one already stored".
    const key = draft.apiKey.trim();
    if (key) body.api_key = key;
    return body;
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    const isCreate = creating;
    const target = editing;
    const fallback = isCreate ? 'Не удалось добавить провайдера' : 'Не удалось сохранить провайдера';
    busy = true;
    feedback = null;
    try {
      const body = payload();
      draft.apiKey = '';
      const response = await fetch(isCreate ? SETTINGS_PATH : `${SETTINGS_PATH}/${encodeURIComponent(target ?? '')}`, {
        method: isCreate ? 'POST' : 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body)
      });
      const value = await readJson(response);
      if (!response.ok) throw new Error(detail(value, fallback));
      const saved = value as SettingsProvider;
      closeDraft();
      feedback = {
        kind: 'notice',
        text: isCreate ? 'Провайдер добавлен' : 'Провайдер сохранён',
        providerId: saved?.id ?? target ?? null,
        form: false
      };
      await invalidateAll();
    } catch (cause) {
      feedback = {
        kind: 'error',
        text: cause instanceof Error ? cause.message : fallback,
        providerId: target,
        form: isCreate
      };
    } finally {
      busy = false;
    }
  }

  async function removeProvider(provider: SettingsProvider) {
    if (!confirm(`Удалить провайдера «${provider.name}», его ключ и все его модели?`)) return;
    busy = true;
    feedback = null;
    try {
      const response = await fetch(`${SETTINGS_PATH}/${encodeURIComponent(provider.id)}`, { method: 'DELETE' });
      const value = await readJson(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось удалить провайдера'));
      closeDraft();
      feedback = { kind: 'notice', text: 'Провайдер удалён', providerId: provider.id, form: false };
      await invalidateAll();
    } catch (cause) {
      feedback = {
        kind: 'error',
        text: cause instanceof Error ? cause.message : 'Не удалось удалить провайдера',
        providerId: provider.id,
        form: false
      };
    } finally {
      busy = false;
    }
  }
</script>

{#snippet feedbackBox(where: 'banner' | 'card' | 'form', providerId: string | null)}
  {@const shown = where === 'card' ? attached : where === 'form' ? (feedback?.form ? feedback : null) : detached}
  {#if shown && (where !== 'card' || shown.providerId === providerId)}
    {#if shown.kind === 'error'}
      <p role="alert" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm leading-6 text-rose-100">{shown.text}</p>
    {:else}
      <p role="status" class="rounded-lg border border-shell-accent/40 bg-shell-accent/10 px-4 py-3 text-sm leading-6 text-emerald-100">{shown.text}</p>
    {/if}
  {/if}
{/snippet}

{#snippet modelRows()}
  <div data-models class="mt-3">
    <div class="space-y-2">
      {#each draft.models as row, index (index)}
        <!-- A phone stacks the two fields; a wider pane puts them side by side.
             `minmax(0, 1fr)` and `min-w-0` keep a long model ID from widening
             the dialog instead of shrinking its own column. -->
        <div
          data-model-row
          class="grid grid-cols-[minmax(0,1fr)_2.75rem] items-center gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_2.75rem]"
        >
          <input
            aria-label="ID модели"
            class={`${field} col-span-2 min-w-0 bg-shell-field sm:col-span-1`}
            bind:value={row.model}
            placeholder="ID модели в API"
          />
          <input
            aria-label="Название модели"
            class={`${field} min-w-0`}
            bind:value={row.name}
            placeholder="Название в интерфейсе"
          />
          <button
            type="button"
            class="grid size-11 shrink-0 place-items-center rounded-lg text-shell-muted transition hover:bg-white/5 hover:text-rose-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shell-accent disabled:opacity-40"
            aria-label="Удалить модель"
            disabled={busy || draft.models.length < 2}
            onclick={() => removeModel(index)}
          >
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" class="size-5" aria-hidden="true">
              <path d="M3.5 5.5h13M8 5.5V4a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1.5M6 5.5l.7 9a1 1 0 0 0 1 .9h4.6a1 1 0 0 0 1-.9l.7-9" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
        </div>
      {/each}
    </div>
    <button type="button" class={`${quiet} mt-3 border border-shell-line`} disabled={busy} onclick={addModel}>
      <span aria-hidden="true">+</span> Добавить модель
    </button>
  </div>
{/snippet}

<h3 class="text-xl font-bold tracking-tight text-shell-ink">Модели</h3>
<p class="mt-2 text-sm leading-6 text-shell-muted">
  Введите ключи API, чтобы использовать модели этих провайдеров.
</p>

{#if data.loadError && providers.length === 0}
  <p role="alert" class="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm leading-6 text-rose-100">{data.loadError}</p>
{:else}
  <div class="mt-6 space-y-3">
    {#if detached}
      {@render feedbackBox('banner', null)}
    {/if}

    {#each providers as provider (provider.id)}
      <article class="rounded-xl border border-shell-line bg-shell-card" data-provider={provider.id} aria-labelledby={`provider-name-${provider.id}`}>
        <div class="flex items-center gap-3 px-5 py-4">
          <h4 id={`provider-name-${provider.id}`} class="min-w-0 truncate text-sm font-semibold text-shell-ink">{provider.name}</h4>
          <span
            role="img"
            class={`size-2 shrink-0 rounded-full ${provider.configured ? 'bg-shell-accent' : 'bg-amber-400'}`}
            aria-label={provider.configured ? 'Настроен' : 'Ключ не задан'}
          ></span>
          {#if editing !== provider.id}
            <button type="button" class={`${quiet} ml-auto border border-shell-line`} disabled={busy} onclick={() => startEdit(provider)}>Настроить</button>
          {/if}
        </div>

        {#if attached && attached.providerId === provider.id}
          <div class="px-5 pb-4">{@render feedbackBox('card', provider.id)}</div>
        {/if}

        {#if editing === provider.id}
          <form class="mx-3 mb-3 rounded-xl bg-shell px-5 py-5" data-editor novalidate onsubmit={save}>
            <p class="flex flex-wrap items-baseline gap-x-2 text-sm">
              <span class="font-semibold text-shell-ink">{provider.name}</span>
              <span class="text-shell-muted">{modelCountLabel(draft.models.length)}</span>
            </p>

            <div class="mt-5">
              <label class={label} for={`key-${provider.id}`}>API-ключ</label>
              <input
                id={`key-${provider.id}`}
                class={field}
                type="password"
                autocomplete="new-password"
                bind:value={draft.apiKey}
                placeholder={provider.configured ? 'Ключ сохранён — введите новое значение, чтобы заменить' : 'Введите ключ'}
              />
              <p class={hint}>Пустое поле оставляет сохранённый ключ. Ключ не показывается после сохранения.</p>
            </div>

            <div class="mt-4 flex justify-start">
              <button
                type="button"
                class="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-2 text-sm font-semibold text-shell-muted transition hover:text-shell-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shell-accent"
                aria-expanded={draft.advanced}
                onclick={() => (draft.advanced = !draft.advanced)}
              >
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" class={`size-4 transition-transform ${draft.advanced ? 'rotate-90' : ''}`} aria-hidden="true">
                  <path d="M7.5 5l5 5-5 5" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
                Дополнительные настройки
              </button>
            </div>

            {#if draft.advanced}
              <div class="mt-2 space-y-5 border-t border-shell-line pt-5">
                <div>
                  <label class={label} for={`name-${provider.id}`}>Название провайдера</label>
                  <input id={`name-${provider.id}`} class={field} bind:value={draft.name} placeholder="Например, Моя модель" />
                </div>
                <div>
                  <label class={label} for={`endpoint-${provider.id}`}>Адрес API</label>
                  <input id={`endpoint-${provider.id}`} class={field} type="url" bind:value={draft.endpoint} placeholder="https://api.example.com/v1/chat/completions" />
                  <p class={hint}>Публичный HTTPS-адрес, заканчивающийся на /chat/completions. Ключ передаётся этому API.</p>
                </div>
                <div class="border-t border-shell-line pt-5">
                  <p class="text-xs font-semibold text-shell-ink">Модели</p>
                  <p class={hint}>ID модели из API и её название в интерфейсе.</p>
                  {@render modelRows()}
                </div>
              </div>
            {/if}

            <div class="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-shell-line pt-5">
              <button
                type="button"
                class="min-h-11 rounded-lg px-3 text-sm font-semibold text-rose-300 transition hover:bg-rose-500/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-400 disabled:opacity-50"
                disabled={busy}
                onclick={() => removeProvider(provider)}
              >Удалить провайдера</button>
              <div class="flex flex-wrap justify-end gap-3">
                <button type="button" class={`${quiet} border border-shell-line`} disabled={busy} onclick={closeDraft}>Отмена</button>
                <button type="submit" class={primary} disabled={busy}>{busy ? 'Сохраняем…' : 'Применить'}</button>
              </div>
            </div>
          </form>
        {/if}
      </article>
    {/each}

    {#if creating}
      <article class="rounded-xl border border-shell-line bg-shell-card" aria-labelledby="settings-create-title">
        <h4 id="settings-create-title" class="px-5 pt-4 pb-1 text-sm font-semibold text-shell-ink">Новый провайдер</h4>
        <form class="px-5 pb-5" novalidate onsubmit={save}>
          <div class="rounded-xl bg-shell px-5 py-5">
            {#if feedback?.form}
              <div class="mb-5">{@render feedbackBox('form', null)}</div>
            {/if}

            <div class="space-y-5">
              <div>
                <label class={label} for="create-name">Название провайдера</label>
                <input id="create-name" class={field} bind:value={draft.name} placeholder="Например, Моя модель" />
              </div>
              <div>
                <label class={label} for="create-endpoint">Адрес API</label>
                <input id="create-endpoint" class={field} type="url" bind:value={draft.endpoint} placeholder="https://api.example.com/v1/chat/completions" />
                <p class={hint}>Публичный HTTPS-адрес, заканчивающийся на /chat/completions. Ключ передаётся этому API.</p>
              </div>
              <div>
                <label class={label} for="create-key">API-ключ</label>
                <input id="create-key" class={field} type="password" autocomplete="new-password" bind:value={draft.apiKey} placeholder="Введите ключ" />
                <p class={hint}>Ключ хранится в системном хранилище и не показывается после сохранения.</p>
              </div>
              <div class="border-t border-shell-line pt-5">
                <p class="text-xs font-semibold text-shell-ink">Модели</p>
                <p class={hint}>ID модели из API и её название в интерфейсе.</p>
                {@render modelRows()}
              </div>
            </div>

            <div class="mt-5 flex flex-wrap justify-end gap-3 border-t border-shell-line pt-5">
              <button type="button" class={`${quiet} border border-shell-line`} disabled={busy} onclick={closeDraft}>Отмена</button>
              <button type="submit" class={primary} disabled={busy}>{busy ? 'Создаём…' : 'Создать'}</button>
            </div>
          </div>
        </form>
      </article>
    {/if}

    {#if providers.length === 0 && !creating}
      <p class="rounded-xl border border-dashed border-shell-line px-5 py-8 text-center text-sm text-shell-muted">
        Провайдеры пока не добавлены. Добавьте первый, чтобы выбрать его модели при проверке.
      </p>
    {/if}

    {#if !creating}
      <button
        type="button"
        class="flex min-h-12 w-full items-center justify-center gap-2 rounded-xl border border-dashed border-shell-line px-5 py-3.5 text-sm font-semibold text-shell-muted transition hover:border-shell-muted hover:text-shell-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shell-accent disabled:opacity-50"
        disabled={busy}
        onclick={startCreate}
      >
        <span aria-hidden="true">+</span> Добавить провайдера
      </button>
    {/if}
  </div>
{/if}
