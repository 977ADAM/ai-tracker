<script lang="ts">
  import { base } from '$app/paths';
  import { invalidateAll } from '$app/navigation';
  import type { SeoSettings, SeoSource } from '$lib/types';

  let { settings, loadError }: { settings: SeoSettings | null; loadError: string } = $props();

  let current = $state<SeoSettings | null>(null);
  let endpoint = $state('');
  let model = $state('');
  let apiKey = $state('');
  let busy = $state(false);
  let feedback = $state<{ kind: 'error' | 'notice'; text: string } | null>(null);

  $effect(() => {
    current = settings;
    endpoint = settings?.endpoint ?? '';
    model = settings?.model ?? '';
  });

  const field = 'block min-h-11 w-full rounded-lg border border-shell-line bg-shell-inset px-3.5 py-2.5 text-sm text-shell-ink outline-none placeholder:text-shell-muted/80 focus:border-shell-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shell-accent disabled:opacity-60';
  const label = 'mb-2 block text-xs font-semibold text-shell-ink';
  const hint = 'mt-2 text-xs leading-5 text-shell-muted';

  function sourceLabel(source: SeoSource): string {
    if (source === 'ui') return 'из интерфейса';
    if (source === 'env') return 'из окружения';
    return 'не задан';
  }

  function apply(next: SeoSettings) {
    current = next;
    endpoint = next.endpoint ?? '';
    model = next.model ?? '';
  }

  async function publicState(response: Response): Promise<SeoSettings> {
    if (!response.ok) throw new Error('request failed');
    const value: unknown = await response.json();
    if (!value || typeof value !== 'object' || !('has_api_key' in value)) throw new Error('invalid response');
    return value as SeoSettings;
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!current || busy || loadError) return;
    const body: { endpoint: string; model: string; api_key?: string } = {
      endpoint: endpoint.trim(),
      model: model.trim()
    };
    // An empty field keeps the stored key; the key itself is never sent back.
    const newKey = apiKey.trim();
    if (newKey) body.api_key = newKey;
    busy = true;
    feedback = null;
    try {
      const response = await fetch(`${base}/api/seo/settings`, {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body)
      });
      apply(await publicState(response));
      apiKey = '';
      await invalidateAll();
      feedback = { kind: 'notice', text: 'Настройки служебной LLM сохранены' };
    } catch {
      feedback = { kind: 'error', text: 'Не удалось сохранить настройки служебной LLM. Попробуйте ещё раз.' };
    } finally {
      busy = false;
    }
  }

  async function testConnection() {
    if (!current || busy || loadError) return;
    busy = true;
    feedback = null;
    try {
      const response = await fetch(`${base}/api/seo/settings/test`, { method: 'POST' });
      if (!response.ok) throw new Error('request failed');
      const value = (await response.json()) as { ok?: unknown; model?: unknown; error?: unknown; tools?: unknown };
      // The SEO run needs tool calling, so the probe result always names it.
      const tools = value.tools === true
        ? 'Инструменты: поддерживаются.'
        : 'Инструменты: не поддерживаются.';
      if (value.ok === true) {
        const model = typeof value.model === 'string' && value.model ? `: ${value.model}` : '';
        feedback = { kind: 'notice', text: `Подключение работает${model}. ${tools}` };
      } else {
        const reason = typeof value.error === 'string' && value.error
          ? value.error
          : 'Не удалось подключиться к служебной LLM';
        feedback = { kind: 'error', text: `${reason} ${tools}` };
      }
    } catch {
      feedback = { kind: 'error', text: 'Не удалось проверить подключение. Попробуйте ещё раз.' };
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
      const response = await fetch(`${base}/api/seo/settings/credentials`, { method: 'DELETE' });
      apply(await publicState(response));
      await invalidateAll();
      feedback = { kind: 'notice', text: 'Ключ удалён, значения возвращены к переменным окружения' };
    } catch {
      feedback = { kind: 'error', text: 'Не удалось сбросить ключ. Попробуйте ещё раз.' };
    } finally {
      busy = false;
    }
  }
</script>

<h3 class="text-xl font-bold tracking-tight text-shell-ink">Служебная LLM</h3>
<p class="mt-2 text-sm leading-6 text-shell-muted">Модель, которая извлекает данные сайта, генерирует запросы и собирает отчёт. Используется только для SEO-анализа.</p>

{#if loadError}
  <p role="alert" class="mt-5 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm leading-6 text-rose-100">{loadError}</p>
{/if}

<article class="mt-6 rounded-xl border border-shell-line bg-shell-card" aria-labelledby="seo-settings-title">
  <div class="border-b border-shell-line px-5 py-4">
    <h4 id="seo-settings-title" class="text-base font-semibold text-shell-ink">Подключение</h4>
  </div>
  <form class="space-y-5 px-5 py-5" onsubmit={save}>
    <div>
      <label for="seo-endpoint" class={label}>Адрес (OpenAI Chat Completions)</label>
      <input id="seo-endpoint" type="text" class={field} bind:value={endpoint} disabled={busy || !current || !!loadError} placeholder="https://api.example.com/v1/chat/completions" />
      <p class={hint}>Удалённый адрес должен использовать HTTPS; HTTP разрешён только для loopback. Пустое поле оставляет сохранённый адрес без изменений.</p>
    </div>

    <div>
      <label for="seo-model" class={label}>Модель</label>
      <input id="seo-model" type="text" class={field} bind:value={model} disabled={busy || !current || !!loadError} placeholder="Название модели" />
      <p class={hint}>Пустое поле оставляет сохранённую модель без изменений.</p>
    </div>

    <div>
      <label for="seo-api-key" class={label}>Новый API-ключ</label>
      <input id="seo-api-key" type="password" autocomplete="new-password" class={field} bind:value={apiKey} disabled={busy || !current || !!loadError} placeholder="Введите новый ключ" />
      <p class={hint}>Пустое поле оставляет сохранённый ключ без изменений. Ключ не показывается после сохранения и никогда не возвращается на клиент.</p>
    </div>

    {#if current}
      <div class="rounded-lg bg-shell px-4 py-3 text-sm leading-6 text-shell-muted" aria-label="Состояние подключения">
        <p class="font-semibold text-shell-ink">{current.has_api_key && current.endpoint && current.model ? 'Подключение настроено' : 'Для работы нужны адрес, модель и API-ключ'}</p>
        <p>Ключ {current.has_api_key ? 'задан' : 'не задан'} — {sourceLabel(current.api_key_source)}</p>
        <p>Адрес: {sourceLabel(current.endpoint_source)}</p>
        <p>Модель: {sourceLabel(current.model_source)}</p>
      </div>
    {/if}

    {#if feedback}
      <p role={feedback.kind === 'error' ? 'alert' : 'status'} class={feedback.kind === 'error' ? 'rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-100' : 'rounded-lg border border-shell-accent/40 bg-shell-accent/10 px-4 py-3 text-sm text-emerald-100'}>{feedback.text}</p>
    {/if}

    <div class="flex flex-wrap items-center justify-between gap-3 border-t border-shell-line pt-5">
      <div class="flex flex-wrap items-center gap-2">
        <button type="button" class="min-h-11 rounded-lg border border-shell-line px-4 text-sm font-semibold text-shell-ink hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shell-accent disabled:opacity-50" disabled={busy || !current || !!loadError} onclick={testConnection}>Проверить подключение</button>
        <button type="button" class="min-h-11 rounded-lg px-3 text-sm font-semibold text-rose-300 hover:bg-rose-500/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-400 disabled:opacity-50" disabled={busy || !current || !!loadError} onclick={resetCredentials}>Сбросить учётные данные</button>
      </div>
      <button type="submit" class="min-h-11 rounded-lg bg-shell-ink px-5 py-2.5 text-sm font-bold text-shell-card hover:bg-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shell-accent disabled:opacity-60" disabled={busy || !current || !!loadError}>{busy ? 'Сохраняем…' : 'Сохранить настройки'}</button>
    </div>
  </form>
</article>
