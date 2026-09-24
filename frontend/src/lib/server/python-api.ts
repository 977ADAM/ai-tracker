import type { ApiPath, FormConfig, PublicProvider, SettingsProvider } from '$lib/types';

const DEFAULT_API_ORIGIN = 'http://127.0.0.1:8000';
const MAX_BODY_BYTES = 64 * 1024;

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } });
}

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid API response');
  return value as Record<string, unknown>;
}

function requiredString(value: unknown): string {
  if (typeof value !== 'string' || !value) throw new Error('Invalid API response');
  return value;
}

function apiOrigin(): string {
  const url = new URL(process.env.AI_TRACKER_API_URL || DEFAULT_API_ORIGIN);
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(url.hostname) ||
      url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Invalid Python API origin');
  }
  return url.origin;
}

export function providerPath(id: string): ApiPath {
  if (!/^[A-Za-z0-9-]{1,64}$/.test(id)) throw new Error('Invalid provider ID');
  return `/api/providers/${encodeURIComponent(id)}`;
}

export function settingsProviderPath(id: string): ApiPath {
  if (!/^[A-Za-z0-9-]{1,64}$/.test(id)) throw new Error('Invalid provider ID');
  return `/api/providers/settings/${encodeURIComponent(id)}`;
}

function validPath(path: ApiPath): boolean {
  if (path === '/api/providers' || path === '/api/check' || path === '/api/form' || path === '/api/providers/settings') return true;
  if (path.startsWith('/api/providers/settings/')) {
    try { return settingsProviderPath(decodeURIComponent(path.slice('/api/providers/settings/'.length))) === path; }
    catch { return false; }
  }
  if (!path.startsWith('/api/providers/')) return false;
  try { return providerPath(decodeURIComponent(path.slice('/api/providers/'.length))) === path; }
  catch { return false; }
}

export function publicConfigurationFile(value: unknown): { path: string; exists: boolean; content: string | null } {
  const item = record(value);
  const exists = item.exists;
  if (typeof exists !== 'boolean') throw new Error('Invalid configuration file');
  const content = item.content;
  if (exists) {
    if (typeof content !== 'string') throw new Error('Invalid configuration file');
    return { path: requiredString(item.path), exists, content };
  }
  if (content !== null) throw new Error('Invalid configuration file');
  return { path: requiredString(item.path), exists, content: null };
}

export function publicSettingsProvider(value: unknown): SettingsProvider {
  const item = record(value);
  if (!Array.isArray(item.models)) throw new Error('Invalid settings provider');
  if (typeof item.configured !== 'boolean') throw new Error('Invalid settings provider');
  return {
    id: requiredString(item.id), name: requiredString(item.name), kind: requiredString(item.kind),
    endpoint: requiredString(item.endpoint), configured: item.configured,
    models: item.models.map((raw) => {
      const model = record(raw);
      return { id: requiredString(model.id), model: requiredString(model.model), name: requiredString(model.name) };
    })
  };
}

export function publicProvider(value: unknown): Record<string, unknown> {
  const item = record(value);
  const allowed = ['id', 'name', 'kind', 'endpoint', 'model', 'scope', 'configured', 'editable_fields', 'can_reset', 'can_delete', 'status_label', 'delete_label', 'delete_prompt', 'delete_success'] as const;
  return Object.fromEntries(allowed.filter((key) => key in item).map((key) => [key, item[key]]));
}

export function publicCheck(value: unknown): Record<string, unknown> {
  const item = record(value);
  if (!Array.isArray(item.checks) || !Array.isArray(item.rows)) throw new Error('Invalid checks');
  const summary = record(item.summary);
  const publicResult = (raw: unknown) => {
    const result = record(raw);
    return { prompt: result.prompt, answer: result.answer, mentioned: result.mentioned, error: result.error, status: result.status };
  };
  return {
    brand: item.brand,
    domain: item.domain,
    summary: { successful: summary.successful, failed: summary.failed, mentioned: summary.mentioned, mention_percent: summary.mention_percent,
      visibility_label: summary.visibility_label, mentions_label: summary.mentions_label, errors_label: summary.errors_label },
    rows: item.rows.map((raw) => ({ ...publicResult(raw), provider_name: record(raw).provider_name })),
    checks: item.checks.map((raw) => {
      const group = record(raw);
      const summary = record(group.summary);
      if (!Array.isArray(group.results)) throw new Error('Invalid results');
      return {
        provider_id: group.provider_id,
        provider_name: group.provider_name,
        summary: { successful: summary.successful, failed: summary.failed, mentioned: summary.mentioned },
        results: group.results.map(publicResult)
      };
    })
  };
}

export function publicForm(value: unknown): Record<string, unknown> {
  const item = record(value);
  const limits = record(item.limits);
  if (!Array.isArray(item.scope_options) || !Array.isArray(item.new_provider_fields) || !Array.isArray(item.default_provider_ids)) throw new Error('Invalid form');
  return { limits: { max_prompts: limits.max_prompts, max_providers: limits.max_providers, max_prompt_length: limits.max_prompt_length,
    max_brand_length: limits.max_brand_length, max_domain_length: limits.max_domain_length },
    new_provider_fields: item.new_provider_fields, default_provider_ids: item.default_provider_ids, scope_options: item.scope_options.map((option) => {
      const entry = record(option);
      return { value: entry.value, label: entry.label };
    }) };
}

export async function pythonApi(path: ApiPath, init: RequestInit = {}): Promise<Response> {
  if (!validPath(path)) throw new Error('Invalid Python API path');
  const signal = init.signal ?? (path === '/api/check' ? undefined : AbortSignal.timeout(10_000));
  return fetch(`${apiOrigin()}${path}`, { ...init, signal, redirect: 'manual' });
}

export async function loadPageData(): Promise<{ providers: PublicProvider[]; settingsProviders: SettingsProvider[]; form: FormConfig | null; loadError: string }> {
  try {
    const [providerResponse, formResponse, settingsResponse] = await Promise.all([pythonApi('/api/providers'), pythonApi('/api/form'), pythonApi('/api/providers/settings')]);
    if (!providerResponse.ok || !formResponse.ok || !settingsResponse.ok ||
        !/^application\/json(?:\s*;|$)/i.test(providerResponse.headers.get('content-type') || '') ||
        !/^application\/json(?:\s*;|$)/i.test(formResponse.headers.get('content-type') || '') ||
        !/^application\/json(?:\s*;|$)/i.test(settingsResponse.headers.get('content-type') || '')) throw new Error('Invalid API response');
    const providers: unknown = await providerResponse.json();
    const settingsProviders: unknown = await settingsResponse.json();
    if (!Array.isArray(providers) || !Array.isArray(settingsProviders)) throw new Error('Invalid providers');
    return { providers: providers.map((item) => publicProvider(item) as PublicProvider), settingsProviders: settingsProviders.map(publicSettingsProvider), form: publicForm(await formResponse.json()) as FormConfig, loadError: '' };
  } catch {
    return { providers: [], settingsProviders: [], form: null, loadError: 'Python API недоступен. Проверьте, запущены ли оба сервиса.' };
  }
}

export async function proxyJson(request: Request, path: ApiPath, method: string): Promise<Response> {
  if (!validPath(path)) return json({ detail: 'Некорректное подключение' }, 400);
  if (!['GET', 'POST', 'PUT', 'DELETE'].includes(method)) return json({ detail: 'Недопустимый метод' }, 405);
  let body: string | undefined;
  if (method !== 'GET') {
    const origin = request.headers.get('origin');
    if (origin && origin !== new URL(request.url).origin) return json({ detail: 'Недопустимый источник запроса' }, 403);
    const declared = request.headers.get('content-length');
    if (declared && Number(declared) > MAX_BODY_BYTES) return json({ detail: 'Запрос слишком большой' }, 413);
    if (method === 'DELETE') {
      if (await request.text()) return json({ detail: 'Удаление не принимает тело запроса' }, 400);
    } else {
      if (!/^application\/json(?:\s*;|$)/i.test(request.headers.get('content-type') || '')) return json({ detail: 'Ожидается JSON' }, 415);
      body = await request.text();
      if (new TextEncoder().encode(body).byteLength > MAX_BODY_BYTES) return json({ detail: 'Запрос слишком большой' }, 413);
      try { JSON.parse(body); }
      catch { return json({ detail: 'Некорректный JSON' }, 400); }
    }
  }
  let upstream: Response;
  try {
    upstream = await pythonApi(path, { method, headers: body === undefined ? undefined : { 'content-type': 'application/json' }, body });
  } catch {
    return json({ detail: 'Python API недоступен' }, 502);
  }
  if (!/^application\/json(?:\s*;|$)/i.test(upstream.headers.get('content-type') || '')) return json({ detail: 'Некорректный ответ Python API' }, 502);
  try {
    const value: unknown = await upstream.json();
    if (!upstream.ok) {
      const detail = record(value).detail;
      return json({ detail: typeof detail === 'string' ? detail : 'Ошибка Python API' }, upstream.status);
    }
    if (path === '/api/providers' && method === 'GET') {
      if (!Array.isArray(value)) throw new Error('Invalid providers');
      return json(value.map(publicProvider), upstream.status);
    }
    if (path === '/api/providers/settings' && method === 'GET') {
      if (!Array.isArray(value)) throw new Error('Invalid settings providers');
      return json(value.map(publicSettingsProvider), upstream.status);
    }
    if (path === '/api/providers/settings/file' && method === 'GET') return json(publicConfigurationFile(value), upstream.status);
    if (path.startsWith('/api/providers/settings/') && method === 'DELETE') return json({ deleted: record(value).deleted === true }, upstream.status);
    if (path.startsWith('/api/providers/settings') && method !== 'DELETE') return json(publicSettingsProvider(value), upstream.status);
    if (path === '/api/form' && method === 'GET') return json(publicForm(value), upstream.status);
    if (path.startsWith('/api/providers/') && method === 'DELETE') return json({ deleted: record(value).deleted === true }, upstream.status);
    if (path.startsWith('/api/providers') && method !== 'DELETE') return json(publicProvider(value), upstream.status);
    if (path === '/api/check') return json(publicCheck(value), upstream.status);
    throw new Error('Unknown response');
  } catch {
    return json({ detail: 'Некорректный ответ Python API' }, 502);
  }
}
