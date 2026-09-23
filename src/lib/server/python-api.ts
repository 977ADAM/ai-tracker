import type { ApiPath } from '$lib/types';

const DEFAULT_API_ORIGIN = 'http://127.0.0.1:8000';
const MAX_BODY_BYTES = 64 * 1024;

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } });
}

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid API response');
  return value as Record<string, unknown>;
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

function validPath(path: ApiPath): boolean {
  if (path === '/api/providers' || path === '/api/check') return true;
  if (!path.startsWith('/api/providers/')) return false;
  try { return providerPath(decodeURIComponent(path.slice('/api/providers/'.length))) === path; }
  catch { return false; }
}

export function publicProvider(value: unknown): Record<string, unknown> {
  const item = record(value);
  const allowed = ['id', 'name', 'kind', 'endpoint', 'model', 'scope', 'configured'] as const;
  return Object.fromEntries(allowed.filter((key) => key in item).map((key) => [key, item[key]]));
}

export function publicCheck(value: unknown): Record<string, unknown> {
  const item = record(value);
  if (!Array.isArray(item.checks)) throw new Error('Invalid checks');
  return {
    brand: item.brand,
    domain: item.domain,
    checks: item.checks.map((raw) => {
      const group = record(raw);
      const summary = record(group.summary);
      if (!Array.isArray(group.results)) throw new Error('Invalid results');
      return {
        provider_id: group.provider_id,
        provider_name: group.provider_name,
        summary: { successful: summary.successful, failed: summary.failed, mentioned: summary.mentioned },
        results: group.results.map((rawResult) => {
          const result = record(rawResult);
          return { prompt: result.prompt, answer: result.answer, mentioned: result.mentioned, error: result.error };
        })
      };
    })
  };
}

export async function pythonApi(path: ApiPath, init: RequestInit = {}): Promise<Response> {
  if (!validPath(path)) throw new Error('Invalid Python API path');
  const signal = init.signal ?? (path === '/api/check' ? undefined : AbortSignal.timeout(10_000));
  return fetch(`${apiOrigin()}${path}`, { ...init, signal, redirect: 'manual' });
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
    if (path.startsWith('/api/providers/') && method === 'DELETE') return json({ deleted: record(value).deleted === true }, upstream.status);
    if (path.startsWith('/api/providers') && method !== 'DELETE') return json(publicProvider(value), upstream.status);
    if (path === '/api/check') return json(publicCheck(value), upstream.status);
    throw new Error('Unknown response');
  } catch {
    return json({ detail: 'Некорректный ответ Python API' }, 502);
  }
}
