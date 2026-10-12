import type {
  ApiPath,
  PublicProvider,
  SettingsProvider,
  YandexSearchSettings,
  SeoSettings,
  SeoSettingsTest,
  SeoSource,
} from '$lib/types';

const DEFAULT_API_ORIGIN = 'http://127.0.0.1:8000';
const MAX_BODY_BYTES = 64 * 1024;
/** The shared request budget; a real LLM call does not fit into it. */
export const DEFAULT_TIMEOUT_MS = 10_000;
/** `POST /api/seo/settings/test` waits for one real chat completion. */
export const SEO_SETTINGS_TEST_TIMEOUT_MS = 120_000;

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
  });
}

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value))
    throw new Error('Invalid API response');
  return value as Record<string, unknown>;
}

function requiredString(value: unknown): string {
  if (typeof value !== 'string' || !value) throw new Error('Invalid API response');
  return value;
}

function optionalString(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== 'string') throw new Error('Invalid API response');
  return value;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[]): T {
  if (typeof value !== 'string' || !allowed.includes(value as T))
    throw new Error('Invalid API response');
  return value as T;
}

function requiredBoolean(value: unknown): boolean {
  if (typeof value !== 'boolean') throw new Error('Invalid API response');
  return value;
}

function optionalBoolean(value: unknown): boolean | null {
  if (value === null || value === undefined) return null;
  return requiredBoolean(value);
}

/** Hosts the BFF may call without being told: the API of a local run. */
const DEFAULT_API_HOSTS = ['127.0.0.1', 'localhost'];

/**
 * The hosts the BFF is allowed to reach: loopback plus the names the deployment
 * lists in `AI_TRACKER_API_HOSTS`. A container reaches the API by its compose
 * service name instead of a loopback address, and an explicit list keeps the
 * rule "never call an arbitrary host from the server" intact.
 */
function apiHosts(): string[] {
  const configured = (process.env.AI_TRACKER_API_HOSTS || '')
    .split(',')
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
  return [...DEFAULT_API_HOSTS, ...configured];
}

export function apiOrigin(): string {
  const url = new URL(process.env.AI_TRACKER_API_URL || DEFAULT_API_ORIGIN);
  if (
    url.protocol !== 'http:' ||
    !apiHosts().includes(url.hostname) ||
    url.username ||
    url.password ||
    url.pathname !== '/' ||
    url.search ||
    url.hash
  ) {
    throw new Error('Invalid Python API origin');
  }
  return url.origin;
}

/**
 * Whether a state-changing request comes from the interface itself.
 *
 * The browser sends `Origin` and `Host` together, and they name the same address
 * exactly when the request is same-origin — whatever spelling the user opened.
 * `localhost:3000` and `127.0.0.1:3000` are different origins to the browser but
 * the same server, and `ORIGIN` can only ever be one of them, so the comparison
 * is on the address the browser really called. A request without an `Origin`
 * header (a plain client, a healthcheck) is not a cross-site request.
 */
export function sameOriginRequest(request: Request): boolean {
  const origin = request.headers.get('origin');
  if (!origin) return true;
  let host: string;
  try {
    host = new URL(origin).host;
  } catch {
    return false;
  }
  return host === (request.headers.get('host') || new URL(request.url).host);
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
  // The service-LLM settings of the measurements and project generation.
  if (
    path === '/api/seo/settings' ||
    path === '/api/seo/settings/credentials' ||
    path === '/api/seo/settings/test'
  )
    return true;
  if (path === '/api/config') return true;
  if (path === '/api/providers' || path === '/api/providers/settings') return true;
  if (path === '/api/search/settings' || path === '/api/search/settings/credentials') return true;
  if (path.startsWith('/api/providers/settings/')) {
    try {
      return (
        settingsProviderPath(decodeURIComponent(path.slice('/api/providers/settings/'.length))) ===
        path
      );
    } catch {
      return false;
    }
  }
  if (!path.startsWith('/api/providers/')) return false;
  try {
    return providerPath(decodeURIComponent(path.slice('/api/providers/'.length))) === path;
  } catch {
    return false;
  }
}

/**
 * The configuration document: the directory it comes from, whether anything is
 * stored there, and the JSON text with the providers, the search settings, and
 * the SEO settings. A key is never part of it — the keyring holds those.
 */
export function publicConfig(value: unknown): {
  directory: string;
  exists: boolean;
  content: string | null;
} {
  const item = record(value);
  const exists = item.exists;
  if (typeof exists !== 'boolean') throw new Error('Invalid configuration');
  const content = item.content;
  if (exists) {
    if (typeof content !== 'string' || content.length === 0)
      throw new Error('Invalid configuration');
    return { directory: requiredString(item.directory), exists, content };
  }
  if (content !== null) throw new Error('Invalid configuration');
  return { directory: requiredString(item.directory), exists, content: null };
}

export function publicSettingsProvider(value: unknown): SettingsProvider {
  const item = record(value);
  if (!Array.isArray(item.models)) throw new Error('Invalid settings provider');
  if (typeof item.configured !== 'boolean') throw new Error('Invalid settings provider');
  return {
    id: requiredString(item.id),
    name: requiredString(item.name),
    kind: requiredString(item.kind),
    endpoint: requiredString(item.endpoint),
    configured: item.configured,
    models: item.models.map((raw) => {
      const model = record(raw);
      return {
        id: requiredString(model.id),
        model: requiredString(model.model),
        name: requiredString(model.name),
      };
    }),
  };
}

export function publicProvider(value: unknown): Record<string, unknown> {
  const item = record(value);
  const allowed = [
    'id',
    'name',
    'kind',
    'endpoint',
    'model',
    'configured',
    'answer_mode',
    'editable_fields',
    'can_reset',
    'can_delete',
    'status_label',
    'delete_label',
    'delete_prompt',
    'delete_success',
  ] as const;
  return Object.fromEntries(allowed.filter((key) => key in item).map((key) => [key, item[key]]));
}

export function publicSearchSettings(value: unknown): { yandex: YandexSearchSettings } {
  const item = record(record(value).yandex);
  if (
    typeof item.enabled !== 'boolean' ||
    typeof item.has_api_key !== 'boolean' ||
    (item.folder_id !== null && typeof item.folder_id !== 'string')
  )
    throw new Error('Invalid search settings');
  return {
    yandex: {
      enabled: item.enabled,
      folder_id: item.folder_id,
      has_api_key: item.has_api_key,
      api_key_source: oneOf(item.api_key_source, ['ui', 'env', 'none'] as const),
      folder_id_source: oneOf(item.folder_id_source, ['ui', 'env', 'none'] as const),
    },
  };
}

const SEO_SOURCES: readonly SeoSource[] = ['ui', 'env', 'none'];

/**
 * Project the public service-LLM settings.
 *
 * Only the six public fields are copied: a returned `api_key`, an upstream
 * echo, or any future backend field is dropped instead of being forwarded.
 */
export function publicSeoSettings(value: unknown): SeoSettings {
  const item = record(value);
  return {
    endpoint: optionalString(item.endpoint),
    model: optionalString(item.model),
    has_api_key: requiredBoolean(item.has_api_key),
    endpoint_source: oneOf(item.endpoint_source, SEO_SOURCES),
    model_source: oneOf(item.model_source, SEO_SOURCES),
    api_key_source: oneOf(item.api_key_source, SEO_SOURCES),
  };
}

/** The availability probe answers with a safe result and never with a key. */
export function publicSeoSettingsTest(value: unknown): SeoSettingsTest {
  const item = record(value);
  return {
    ok: requiredBoolean(item.ok),
    model: optionalString(item.model),
    error: optionalString(item.error),
    // Omitted when the probe failed or the model cannot call tools at all.
    tools: optionalBoolean(item.tools),
  };
}

/**
 * The request budget for one upstream path.
 *
 * The SEO connection test waits for a real LLM completion; every other call
 * keeps the short shared budget.
 */
export function apiTimeoutMs(path: ApiPath): number | undefined {
  if (path === '/api/seo/settings/test') return SEO_SETTINGS_TEST_TIMEOUT_MS;
  return DEFAULT_TIMEOUT_MS;
}

export async function pythonApi(path: ApiPath, init: RequestInit = {}): Promise<Response> {
  if (!validPath(path)) throw new Error('Invalid Python API path');
  const timeout = apiTimeoutMs(path);
  const signal = init.signal ?? (timeout === undefined ? undefined : AbortSignal.timeout(timeout));
  return fetch(`${apiOrigin()}${path}`, { ...init, signal, redirect: 'manual' });
}

export async function loadPageData(): Promise<{
  providers: PublicProvider[];
  settingsProviders: SettingsProvider[];
  searchSettings: YandexSearchSettings | null;
  searchSettingsError: string;
  seoSettings: SeoSettings | null;
  seoSettingsError: string;
  loadError: string;
}> {
  // The search and service-LLM settings are independent requests: a failure
  // there must not stop the model list, and vice versa.
  const { settings: searchSettings, error: searchSettingsError } = await loadSearchSettings();
  const { settings: seoSettings, error: seoSettingsError } = await loadSeoSettings();
  try {
    const [providerResponse, settingsResponse] = await Promise.all([
      pythonApi('/api/providers'),
      pythonApi('/api/providers/settings'),
    ]);
    if (
      !providerResponse.ok ||
      !settingsResponse.ok ||
      !/^application\/json(?:\s*;|$)/i.test(providerResponse.headers.get('content-type') || '') ||
      !/^application\/json(?:\s*;|$)/i.test(settingsResponse.headers.get('content-type') || '')
    )
      throw new Error('Invalid API response');
    const providers: unknown = await providerResponse.json();
    const settingsProviders: unknown = await settingsResponse.json();
    if (!Array.isArray(providers) || !Array.isArray(settingsProviders))
      throw new Error('Invalid providers');
    return {
      providers: providers.map((item) => publicProvider(item) as PublicProvider),
      settingsProviders: settingsProviders.map(publicSettingsProvider),
      searchSettings,
      searchSettingsError,
      seoSettings,
      seoSettingsError,
      loadError: '',
    };
  } catch {
    return {
      providers: [],
      settingsProviders: [],
      searchSettings,
      searchSettingsError,
      seoSettings,
      seoSettingsError,
      loadError: 'Python API недоступен. Проверьте, запущены ли оба сервиса.',
    };
  }
}

async function loadSeoSettings(): Promise<{ settings: SeoSettings | null; error: string }> {
  try {
    const response = await pythonApi('/api/seo/settings');
    if (
      !response.ok ||
      !/^application\/json(?:\s*;|$)/i.test(response.headers.get('content-type') || '')
    )
      throw new Error('Invalid SEO settings');
    return { settings: publicSeoSettings(await response.json()), error: '' };
  } catch {
    return { settings: null, error: 'Настройки служебной LLM недоступны' };
  }
}

async function loadSearchSettings(): Promise<{
  settings: YandexSearchSettings | null;
  error: string;
}> {
  try {
    const response = await pythonApi('/api/search/settings');
    if (
      !response.ok ||
      !/^application\/json(?:\s*;|$)/i.test(response.headers.get('content-type') || '')
    )
      throw new Error('Invalid search settings');
    return { settings: publicSearchSettings(await response.json()).yandex, error: '' };
  } catch {
    return { settings: null, error: 'Настройки поисковых систем недоступны' };
  }
}

export async function proxyJson(
  request: Request,
  path: ApiPath,
  method: string,
): Promise<Response> {
  if (!validPath(path)) return json({ detail: 'Некорректное подключение' }, 400);
  if (!['GET', 'POST', 'PUT', 'DELETE'].includes(method))
    return json({ detail: 'Недопустимый метод' }, 405);
  const searchSettingsPath =
    path === '/api/search/settings' || path === '/api/search/settings/credentials';
  if (
    searchSettingsPath &&
    !(path === '/api/search/settings' ? ['GET', 'PUT'].includes(method) : method === 'DELETE')
  )
    return json({ detail: 'Недопустимый метод' }, 405);
  const seoSettingsPath =
    path === '/api/seo/settings' ||
    path === '/api/seo/settings/credentials' ||
    path === '/api/seo/settings/test';
  if (seoSettingsPath) {
    const allowed =
      path === '/api/seo/settings'
        ? ['GET', 'PUT']
        : path === '/api/seo/settings/credentials'
          ? ['DELETE']
          : ['POST'];
    if (!allowed.includes(method)) return json({ detail: 'Недопустимый метод' }, 405);
  }
  // The connection probe is a bodyless POST: it carries no payload and triggers
  // one upstream chat call.
  const bodylessPost = path === '/api/seo/settings/test';
  let body: string | undefined;
  if (method !== 'GET') {
    if (!sameOriginRequest(request)) return json({ detail: 'Недопустимый источник запроса' }, 403);
    const declared = request.headers.get('content-length');
    if (declared && Number(declared) > MAX_BODY_BYTES)
      return json({ detail: 'Запрос слишком большой' }, 413);
    if (method === 'DELETE') {
      if (await request.text()) return json({ detail: 'Удаление не принимает тело запроса' }, 400);
    } else if (!bodylessPost) {
      if (!/^application\/json(?:\s*;|$)/i.test(request.headers.get('content-type') || ''))
        return json({ detail: 'Ожидается JSON' }, 415);
      body = await request.text();
      if (new TextEncoder().encode(body).byteLength > MAX_BODY_BYTES)
        return json({ detail: 'Запрос слишком большой' }, 413);
      try {
        JSON.parse(body);
      } catch {
        return json({ detail: 'Некорректный JSON' }, 400);
      }
    }
  }
  let upstream: Response;
  try {
    upstream = await pythonApi(path, {
      method,
      headers: body === undefined ? undefined : { 'content-type': 'application/json' },
      body,
    });
  } catch {
    return json({ detail: 'Python API недоступен' }, 502);
  }
  if (method === 'DELETE' && upstream.status === 204 && !searchSettingsPath && !seoSettingsPath)
    return new Response(null, { status: 204, headers: { 'cache-control': 'no-store' } });
  if (!/^application\/json(?:\s*;|$)/i.test(upstream.headers.get('content-type') || ''))
    return json({ detail: 'Некорректный ответ Python API' }, 502);
  try {
    const value: unknown = await upstream.json();
    if (!upstream.ok) {
      if (searchSettingsPath)
        return json({ detail: 'Ошибка настроек поисковой системы' }, upstream.status);
      if (seoSettingsPath)
        return json({ detail: 'Ошибка настроек служебной LLM' }, upstream.status);
      const detail = record(value).detail;
      return json(
        { detail: typeof detail === 'string' ? detail : 'Ошибка Python API' },
        upstream.status,
      );
    }
    if (path === '/api/seo/settings' || path === '/api/seo/settings/credentials')
      return json(publicSeoSettings(value), upstream.status);
    if (path === '/api/seo/settings/test')
      return json(publicSeoSettingsTest(value), upstream.status);
    if (searchSettingsPath) return json(publicSearchSettings(value), upstream.status);
    if (path === '/api/providers' && method === 'GET') {
      if (!Array.isArray(value)) throw new Error('Invalid providers');
      return json(value.map(publicProvider), upstream.status);
    }
    if (path === '/api/providers/settings' && method === 'GET') {
      if (!Array.isArray(value)) throw new Error('Invalid settings providers');
      return json(value.map(publicSettingsProvider), upstream.status);
    }
    if (path === '/api/config' && method === 'GET')
      return json(publicConfig(value), upstream.status);
    if (path.startsWith('/api/providers/settings/') && method === 'DELETE')
      return json({ deleted: record(value).deleted === true }, upstream.status);
    if (path.startsWith('/api/providers/settings') && method !== 'DELETE')
      return json(publicSettingsProvider(value), upstream.status);
    if (path.startsWith('/api/providers/') && method === 'DELETE')
      return json({ deleted: record(value).deleted === true }, upstream.status);
    if (path.startsWith('/api/providers') && method !== 'DELETE')
      return json(publicProvider(value), upstream.status);
    throw new Error('Unknown response');
  } catch {
    return json({ detail: 'Некорректный ответ Python API' }, 502);
  }
}
