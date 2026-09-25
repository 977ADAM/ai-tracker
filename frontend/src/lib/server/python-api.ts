import type {
  ApiPath, FormConfig, PublicProvider, SearchCreated, SearchRegion, SearchRow, SearchRowStatus,
  SearchSnapshot, SettingsProvider, RunCreated, RunHistoryPage, RunSnapshot, RunSummaryRow,
  RunModelRow, RunSearchRow
} from '$lib/types';

const DEFAULT_API_ORIGIN = 'http://127.0.0.1:8000';
const MAX_BODY_BYTES = 64 * 1024;
const MAX_CSV_BYTES = 5 * 1024 * 1024;

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

function stringValue(value: unknown): string {
  if (typeof value !== 'string') throw new Error('Invalid API response');
  return value;
}

function strings(value: unknown): string[] {
  if (!Array.isArray(value)) throw new Error('Invalid API response');
  return value.map(stringValue);
}

function integers(value: unknown): number[] {
  if (!Array.isArray(value)) throw new Error('Invalid API response');
  return value.map(requiredInteger);
}

function requiredInteger(value: unknown): number {
  if (typeof value !== 'number' || !Number.isInteger(value)) throw new Error('Invalid API response');
  return value;
}

function optionalString(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== 'string') throw new Error('Invalid API response');
  return value;
}

function optionalInteger(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  return requiredInteger(value);
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[]): T {
  if (typeof value !== 'string' || !allowed.includes(value as T)) throw new Error('Invalid API response');
  return value as T;
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

export function searchPath(id: string): ApiPath {
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(id)) throw new Error('Invalid search ID');
  return `/api/search/${encodeURIComponent(id)}`;
}

export function runPath(id: string): ApiPath {
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(id)) throw new Error('Invalid run ID');
  return `/api/runs/${encodeURIComponent(id)}`;
}

export function runExportPath(id: string): ApiPath {
  return `${runPath(id)}/export.csv` as ApiPath;
}

export function runListPath(cursor: string | null): ApiPath {
  if (cursor === null) return '/api/runs';
  if (!/^[A-Za-z0-9_-]{1,256}$/.test(cursor)) throw new Error('Invalid cursor');
  return `/api/runs?cursor=${cursor}`;
}

function validPath(path: ApiPath): boolean {
  if (path === '/api/runs') return true;
  if (path.startsWith('/api/runs?cursor=')) {
    try { return runListPath(path.slice('/api/runs?cursor='.length)) === path; }
    catch { return false; }
  }
  if (path.startsWith('/api/runs/')) {
    const suffix = path.slice('/api/runs/'.length);
    if (suffix.endsWith('/export.csv')) {
      try { return runExportPath(suffix.slice(0, -'/export.csv'.length)) === path; }
      catch { return false; }
    }
    try { return runPath(suffix) === path; }
    catch { return false; }
  }
  if (path === '/api/providers' || path === '/api/check' || path === '/api/form' || path === '/api/providers/settings') return true;
  // The static catalog comes before the dynamic job route, exactly as in Python.
  if (path === '/api/search' || path === '/api/search/regions') return true;
  if (path.startsWith('/api/search/')) {
    try { return searchPath(decodeURIComponent(path.slice('/api/search/'.length))) === path; }
    catch { return false; }
  }
  if (path.startsWith('/api/providers/settings/')) {
    try { return settingsProviderPath(decodeURIComponent(path.slice('/api/providers/settings/'.length))) === path; }
    catch { return false; }
  }
  if (!path.startsWith('/api/providers/')) return false;
  try { return providerPath(decodeURIComponent(path.slice('/api/providers/'.length))) === path; }
  catch { return false; }
}

const RUN_STATUSES = ['pending', 'done', 'interrupted'] as const;
const MODEL_RUN_STATUSES = ['pending', 'mentioned', 'absent', 'error', 'interrupted'] as const;
const SEARCH_RUN_STATUSES = ['submitting', 'waiting', 'found', 'absent', 'error', 'interrupted'] as const;

export function publicRunCreated(value: unknown): RunCreated {
  const item = record(value);
  const id = requiredString(item.id);
  runPath(id);
  return { id, status: oneOf(item.status, RUN_STATUSES) };
}

function runModelRow(value: unknown): RunModelRow {
  const row = record(value);
  const mentioned = row.mentioned;
  if (mentioned !== null && typeof mentioned !== 'boolean') throw new Error('Invalid model row');
  return {
    provider_id: requiredString(row.provider_id), prompt_index: requiredInteger(row.prompt_index),
    provider_name: requiredString(row.provider_name), prompt: requiredString(row.prompt),
    status: oneOf(row.status, MODEL_RUN_STATUSES), answer: optionalString(row.answer),
    mentioned: mentioned as boolean | null, error: optionalString(row.error)
  };
}

function runSearchRow(value: unknown): RunSearchRow {
  const row = record(value);
  return {
    search_index: requiredInteger(row.search_index), prompt_index: requiredInteger(row.prompt_index),
    region_index: requiredInteger(row.region_index), prompt: requiredString(row.prompt),
    region_id: requiredInteger(row.region_id), region_name: requiredString(row.region_name),
    status: oneOf(row.status, SEARCH_RUN_STATUSES), position: optionalInteger(row.position),
    url: optionalString(row.url), error: optionalString(row.error)
  };
}

function runSummaryRow(value: unknown): RunSummaryRow {
  const row = record(value);
  return {
    prompt: stringValue(row.prompt), source: stringValue(row.source),
    language: stringValue(row.language), region: stringValue(row.region),
    ai_answer: stringValue(row.ai_answer), site_found: stringValue(row.site_found),
    position: stringValue(row.position), brand_found: stringValue(row.brand_found),
    status: stringValue(row.status)
  };
}

export function publicRunSnapshot(value: unknown): RunSnapshot {
  const item = record(value);
  const id = requiredString(item.id);
  runPath(id);
  if (!Array.isArray(item.models) || !Array.isArray(item.search) || !Array.isArray(item.summary_rows))
    throw new Error('Invalid run snapshot');
  return {
    id, created_at: requiredString(item.created_at), finished_at: optionalString(item.finished_at),
    status: oneOf(item.status, RUN_STATUSES), brand: stringValue(item.brand), domain: stringValue(item.domain),
    prompts: strings(item.prompts), provider_ids: strings(item.provider_ids), regions: integers(item.regions),
    models: item.models.map(runModelRow), search: item.search.map(runSearchRow),
    summary_rows: item.summary_rows.map(runSummaryRow)
  };
}

export function publicRunList(value: unknown): RunHistoryPage {
  const page = record(value);
  if (!Array.isArray(page.items)) throw new Error('Invalid run history');
  const next_cursor = optionalString(page.next_cursor);
  if (next_cursor !== null) runListPath(next_cursor);
  return { items: page.items.map((raw) => {
    const item = record(raw);
    const id = requiredString(item.id);
    runPath(id);
    return { id, created_at: requiredString(item.created_at), status: oneOf(item.status, RUN_STATUSES),
      prompts: strings(item.prompts) };
  }), next_cursor };
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

const JOB_STATUSES = ['pending', 'done'] as const;
const ROW_STATUSES: readonly SearchRowStatus[] = ['submitting', 'waiting', 'found', 'absent', 'error'];

export function publicSearchRegions(value: unknown): SearchRegion[] {
  if (!Array.isArray(value)) throw new Error('Invalid search regions');
  return value.map((raw) => {
    const item = record(raw);
    return { id: requiredInteger(item.id), name: requiredString(item.name) };
  });
}

export function publicSearchCreated(value: unknown): SearchCreated {
  const item = record(value);
  const total = requiredInteger(item.total);
  if (total < 1) throw new Error('Invalid search job');
  return { id: requiredString(item.id), total, status: oneOf(item.status, JOB_STATUSES) };
}

function searchRow(value: unknown): SearchRow {
  const row = record(value);
  return {
    prompt: requiredString(row.prompt),
    region_id: requiredInteger(row.region_id),
    region_name: requiredString(row.region_name),
    status: oneOf(row.status, ROW_STATUSES),
    position: optionalInteger(row.position),
    url: optionalString(row.url),
    error: optionalString(row.error)
  };
}

export function publicSearchSnapshot(value: unknown): SearchSnapshot {
  const item = record(value);
  if (!Array.isArray(item.regions) || !Array.isArray(item.results)) throw new Error('Invalid search snapshot');
  const summary = record(item.summary);
  return {
    id: requiredString(item.id),
    domain: requiredString(item.domain),
    regions: item.regions.map(requiredInteger),
    total: requiredInteger(item.total),
    completed: requiredInteger(item.completed),
    status: oneOf(item.status, JOB_STATUSES),
    summary: {
      successful: requiredInteger(summary.successful),
      found: requiredInteger(summary.found),
      failed: requiredInteger(summary.failed)
    },
    results: item.results.map(searchRow)
  };
}

export function publicForm(value: unknown): Record<string, unknown> {  const item = record(value);
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

export async function loadPageData(): Promise<{ providers: PublicProvider[]; settingsProviders: SettingsProvider[]; form: FormConfig | null; searchRegions: SearchRegion[]; searchRegionError: string; loadError: string }> {
  // The region catalog is an independent request: a failure there must not stop
  // the model list, and vice versa.
  const { regions: searchRegions, error: searchRegionError } = await loadSearchRegions();
  try {
    const [providerResponse, formResponse, settingsResponse] = await Promise.all([pythonApi('/api/providers'), pythonApi('/api/form'), pythonApi('/api/providers/settings')]);
    if (!providerResponse.ok || !formResponse.ok || !settingsResponse.ok ||
        !/^application\/json(?:\s*;|$)/i.test(providerResponse.headers.get('content-type') || '') ||
        !/^application\/json(?:\s*;|$)/i.test(formResponse.headers.get('content-type') || '') ||
        !/^application\/json(?:\s*;|$)/i.test(settingsResponse.headers.get('content-type') || '')) throw new Error('Invalid API response');
    const providers: unknown = await providerResponse.json();
    const settingsProviders: unknown = await settingsResponse.json();
    if (!Array.isArray(providers) || !Array.isArray(settingsProviders)) throw new Error('Invalid providers');
    return { providers: providers.map((item) => publicProvider(item) as PublicProvider), settingsProviders: settingsProviders.map(publicSettingsProvider), form: publicForm(await formResponse.json()) as FormConfig, searchRegions, searchRegionError, loadError: '' };
  } catch {
    return { providers: [], settingsProviders: [], form: null, searchRegions, searchRegionError, loadError: 'Python API недоступен. Проверьте, запущены ли оба сервиса.' };
  }
}

async function loadSearchRegions(): Promise<{ regions: SearchRegion[]; error: string }> {
  try {
    const response = await pythonApi('/api/search/regions');
    if (!response.ok || !/^application\/json(?:\s*;|$)/i.test(response.headers.get('content-type') || '')) throw new Error('Invalid search regions');
    return { regions: publicSearchRegions(await response.json()), error: '' };
  } catch {
    return { regions: [], error: 'Справочник регионов недоступен' };
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
  if (method === 'DELETE' && upstream.status === 204) return new Response(null, { status: 204, headers: { 'cache-control': 'no-store' } });
  if (!/^application\/json(?:\s*;|$)/i.test(upstream.headers.get('content-type') || '')) return json({ detail: 'Некорректный ответ Python API' }, 502);
  try {
    const value: unknown = await upstream.json();
    if (!upstream.ok) {
      const detail = record(value).detail;
      return json({ detail: typeof detail === 'string' ? detail : 'Ошибка Python API' }, upstream.status);
    }
    if (path === '/api/runs' && method === 'POST') return json(publicRunCreated(value), upstream.status);
    if ((path === '/api/runs' || path.startsWith('/api/runs?cursor=')) && method === 'GET') return json(publicRunList(value), upstream.status);
    if (path.startsWith('/api/runs/') && method === 'GET') return json(publicRunSnapshot(value), upstream.status);
    if (path === '/api/search' && method === 'POST') return json(publicSearchCreated(value), upstream.status);
    if (path === '/api/search/regions' && method === 'GET') return json(publicSearchRegions(value), upstream.status);
    if (path.startsWith('/api/search/') && method === 'GET') return json(publicSearchSnapshot(value), upstream.status);
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

export async function proxyCsv(request: Request, path: ApiPath): Promise<Response> {
  if (!validPath(path) || !path.endsWith('/export.csv')) return json({ detail: 'Некорректный прогон' }, 400);
  if (request.method !== 'GET') return json({ detail: 'Недопустимый метод' }, 405);
  let upstream: Response;
  try { upstream = await pythonApi(path); }
  catch { return json({ detail: 'Python API недоступен' }, 502); }
  if (!upstream.ok) {
    if (!/^application\/json(?:\s*;|$)/i.test(upstream.headers.get('content-type') || ''))
      return json({ detail: 'Некорректный ответ Python API' }, 502);
    try {
      const detail = record(await upstream.json()).detail;
      return json({ detail: typeof detail === 'string' ? detail : 'Ошибка Python API' }, upstream.status);
    } catch { return json({ detail: 'Некорректный ответ Python API' }, 502); }
  }
  if (!/^text\/csv(?:\s*;|$)/i.test(upstream.headers.get('content-type') || ''))
    return json({ detail: 'Некорректный ответ Python API' }, 502);
  const declared = upstream.headers.get('content-length');
  if (declared && Number(declared) > MAX_CSV_BYTES) return json({ detail: 'Результат слишком большой' }, 502);
  const body = new Uint8Array(await upstream.arrayBuffer());
  if (body.byteLength > MAX_CSV_BYTES) return json({ detail: 'Результат слишком большой' }, 502);
  const rawFilename = upstream.headers.get('content-disposition') || '';
  const date = /^attachment; filename="ai-serp-results-(\d{4}-\d{2}-\d{2})\.csv"$/.exec(rawFilename)?.[1]
    || new Date().toISOString().slice(0, 10);
  return new Response(body, { status: 200, headers: {
    'content-type': 'text/csv; charset=utf-8', 'cache-control': 'no-store',
    'content-disposition': `attachment; filename="ai-serp-results-${date}.csv"`
  } });
}
