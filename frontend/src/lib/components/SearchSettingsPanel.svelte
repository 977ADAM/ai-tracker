<script lang="ts">
  import { invalidateAll } from '$app/navigation';
  import type { YandexSearchSettings } from '$lib/types';

  let { settings, loadError }: { settings: YandexSearchSettings | null; loadError: string } = $props();

  let current = $state<YandexSearchSettings | null>(null);
  let enabled = $state(true);
  let folderId = $state('');
  let apiKey = $state('');
  let busy = $state(false);
  let feedback = $state<{ kind: 'error' | 'notice'; text: string } | null>(null);

  $effect(() => {
    current = settings;
    enabled = settings?.enabled ?? true;
    folderId = settings?.folder_id ?? '';
  });

  const field = 'block min-h-11 w-full rounded-lg border border-shell-line bg-shell-inset px-3.5 py-2.5 text-sm text-shell-ink outline-none placeholder:text-shell-muted/80 focus:border-shell-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shell-accent disabled:opacity-60';
  const label = 'mb-2 block text-xs font-semibold text-shell-ink';
  const hint = 'mt-2 text-xs leading-5 text-shell-muted';

  function sourceLabel(source: YandexSearchSettings['api_key_source']): string {
    if (source === 'ui') return 'из интерфейса';
    if (source === 'env') return 'из окружения';
    return 'не задан';
  }

  async function publicState(response: Response): Promise<YandexSearchSettings> {
    if (!response.ok) throw new Error('request failed');
    const value: unknown = await response.json();
    if (!value || typeof value !== 'object' || !('yandex' in value)) throw new Error('invalid response');
    return (value as { yandex: YandexSearchSettings }).yandex;
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!current || busy || loadError) return;
    const body: { enabled: boolean; api_key?: string; folder_id?: string } = { enabled };
    const newKey = apiKey.trim();
    const newFolder = folderId.trim();
    if (newKey) body.api_key = newKey;
    if (newFolder && newFolder !== (current.folder_id ?? '')) body.folder_id = newFolder;
    apiKey = '';
    busy = true;
    feedback = null;
    try {
      const response = await fetch('/api/search/settings', {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body)
      });
      current = await publicState(response);
      enabled = current.enabled;
      folderId = current.folder_id ?? '';
      await invalidateAll();
      feedback = { kind: 'notice', text: 'Настройки Яндекса сохранены' };
    } catch {
      feedback = { kind: 'error', text: 'Не удалось сохранить настройки Яндекса. Попробуйте ещё раз.' };
    } finally {
      busy = false;
    }
  }

  async function resetCredentials() {
    if (!current || busy || loadError) return;
    busy = true;
    feedback = null;
    apiKey = '';
    try {
      const response = await fetch('/api/search/settings/credentials', { method: 'DELETE' });
      current = await publicState(response);
      enabled = current.enabled;
      folderId = current.folder_id ?? '';
      await invalidateAll();
      feedback = { kind: 'notice', text: 'Учётные данные сброшены к значениям окружения' };
    } catch {
      feedback = { kind: 'error', text: 'Не удалось сбросить учётные данные. Попробуйте ещё раз.' };
    } finally {
      busy = false;
    }
  }
</script>

<h3 class="text-xl font-bold tracking-tight text-shell-ink">Поисковые системы</h3>
<p class="mt-2 text-sm leading-6 text-shell-muted">Управляйте доступностью и подключением поисковых систем.</p>

{#if loadError}
  <p role="alert" class="mt-5 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm leading-6 text-rose-100">{loadError}</p>
{/if}

<article class="mt-6 rounded-xl border border-shell-line bg-shell-card" aria-labelledby="yandex-settings-title">
  <div class="border-b border-shell-line px-5 py-4">
    <h4 id="yandex-settings-title" class="text-base font-semibold text-shell-ink">Яндекс</h4>
  </div>
  <form class="space-y-5 px-5 py-5" onsubmit={save}>
    <label class="flex min-h-11 items-center gap-3 text-sm font-medium text-shell-ink">
      <input type="checkbox" bind:checked={enabled} disabled={busy || !current || !!loadError} class="size-5 accent-emerald-400" />
      <span>Яндекс включён</span>
    </label>

    <div>
      <label for="yandex-api-key" class={label}>Новый API-ключ</label>
      <input id="yandex-api-key" type="password" autocomplete="new-password" class={field} bind:value={apiKey} disabled={busy || !current || !!loadError} placeholder="Введите новый ключ" />
      <p class={hint}>Пустое поле оставляет сохранённый ключ без изменений. Ключ не показывается после сохранения.</p>
    </div>

    <div>
      <label for="yandex-folder-id" class={label}>ID каталога</label>
      <input id="yandex-folder-id" type="text" class={field} bind:value={folderId} disabled={busy || !current || !!loadError} placeholder="ID каталога Yandex Cloud" />
      <p class={hint}>Пустое поле оставляет сохранённый ID каталога без изменений.</p>
    </div>

    {#if current}
      <div class="rounded-lg bg-shell px-4 py-3 text-sm leading-6 text-shell-muted" aria-label="Состояние подключения">
        <p class="font-semibold text-shell-ink">{current.has_api_key && current.folder_id ? 'Подключение настроено' : 'Для подключения нужны API-ключ и ID каталога'}</p>
        <p>Ключ {current.has_api_key ? 'задан' : 'не задан'} — {sourceLabel(current.api_key_source)}</p>
        <p>ID каталога: {sourceLabel(current.folder_id_source)}</p>
      </div>
    {/if}

    {#if feedback}
      <p role={feedback.kind === 'error' ? 'alert' : 'status'} class={feedback.kind === 'error' ? 'rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-100' : 'rounded-lg border border-shell-accent/40 bg-shell-accent/10 px-4 py-3 text-sm text-emerald-100'}>{feedback.text}</p>
    {/if}

    <div class="flex flex-wrap items-center justify-between gap-3 border-t border-shell-line pt-5">
      <button type="button" class="min-h-11 rounded-lg px-3 text-sm font-semibold text-rose-300 hover:bg-rose-500/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-400 disabled:opacity-50" disabled={busy || !current || !!loadError} onclick={resetCredentials}>Сбросить учётные данные</button>
      <button type="submit" class="min-h-11 rounded-lg bg-shell-ink px-5 py-2.5 text-sm font-bold text-shell-card hover:bg-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shell-accent disabled:opacity-60" disabled={busy || !current || !!loadError}>{busy ? 'Сохраняем…' : 'Сохранить настройки'}</button>
    </div>
  </form>
</article>
