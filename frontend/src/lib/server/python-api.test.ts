import { afterEach, describe, expect, it, vi } from 'vitest';
import { providerPath, proxyJson } from './python-api';

const base = 'http://127.0.0.1:5173';
function request(path: string, method = 'GET', payload?: unknown, headers: Record<string, string> = {}) {
  return new Request(`${base}${path}`, {
    method,
    headers: payload === undefined ? headers : { 'content-type': 'application/json', ...headers },
    body: payload === undefined ? undefined : JSON.stringify(payload)
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  delete process.env.AI_TRACKER_API_URL;
});

describe('Python API bridge', () => {
  it('returns only public provider fields', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([
      { id: 'deepseek', name: 'DeepSeek', kind: 'openai', endpoint: 'https://api.deepseek.com/chat/completions', model: 'deepseek-flash', configured: true, api_key: 'private' }
    ]), { headers: { 'content-type': 'application/json' } }));
    const response = await proxyJson(request('/api/providers'), '/api/providers', 'GET');
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual([{ id: 'deepseek', name: 'DeepSeek', kind: 'openai', endpoint: 'https://api.deepseek.com/chat/completions', model: 'deepseek-flash', configured: true }]);
    expect(spy.mock.calls[0][0]).toBe('http://127.0.0.1:8000/api/providers');
  });

  it('forwards a key update but does not return a key', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ id: 'deepseek', name: 'DeepSeek', kind: 'openai', model: 'deepseek-flash', configured: true, api_key: 'private' }), { headers: { 'content-type': 'application/json' } }));
    const response = await proxyJson(request('/api/providers/deepseek', 'PUT', { api_key: 'private' }), '/api/providers/deepseek', 'PUT');
    expect(response.status).toBe(200);
    expect(JSON.stringify(await response.json())).not.toContain('private');
    expect(spy.mock.calls[0][1]?.method).toBe('PUT');
    expect(spy.mock.calls[0][1]?.body).toBe('{"api_key":"private"}');
  });

  it('rejects cross-origin writes before any key is sent', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'));
    const response = await proxyJson(request('/api/providers/deepseek', 'PUT', { api_key: 'secret' }, { origin: 'https://other.example' }), '/api/providers/deepseek', 'PUT');
    expect(response.status).toBe(403);
    expect(spy).not.toHaveBeenCalled();
  });

  it('rejects a non-JSON or oversized body before forwarding', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'));
    const wrongType = new Request(`${base}/api/check`, { method: 'POST', headers: { 'content-type': 'text/plain' }, body: '{}' });
    expect((await proxyJson(wrongType, '/api/check', 'POST')).status).toBe(415);
    const tooLarge = request('/api/check', 'POST', { prompts: ['x'.repeat(70_000)] });
    expect((await proxyJson(tooLarge, '/api/check', 'POST')).status).toBe(413);
    expect(spy).not.toHaveBeenCalled();
  });

  it('rejects arbitrary upstream paths and non-loopback configuration', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'));
    expect(() => providerPath('../check')).toThrow();
    process.env.AI_TRACKER_API_URL = 'https://example.com';
    const response = await proxyJson(request('/api/providers'), '/api/providers', 'GET');
    expect(response.status).toBe(502);
    expect(spy).not.toHaveBeenCalled();
  });

  it('returns safe 502 for unavailable or malformed Python API', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new Error('secret internal path')).mockResolvedValueOnce(new Response('<html>bad</html>', { headers: { 'content-type': 'text/html' } }));
    const unavailable = await proxyJson(request('/api/providers'), '/api/providers', 'GET');
    expect(unavailable.status).toBe(502);
    expect(await unavailable.text()).not.toContain('secret internal path');
    const malformed = await proxyJson(request('/api/providers'), '/api/providers', 'GET');
    expect(malformed.status).toBe(502);
  });

  it('bounds settings calls without truncating a long check', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response('[]', { headers: { 'content-type': 'application/json' } })).mockResolvedValueOnce(new Response(JSON.stringify({ brand: 'x', domain: '', checks: [] }), { headers: { 'content-type': 'application/json' } }));
    await proxyJson(request('/api/providers'), '/api/providers', 'GET');
    await proxyJson(request('/api/check', 'POST', { brand: 'x', prompts: ['q'], provider_ids: ['deepseek'] }), '/api/check', 'POST');
    expect(spy.mock.calls[0][1]?.signal).toBeInstanceOf(AbortSignal);
    expect(spy.mock.calls[1][1]?.signal).toBeUndefined();
  });

  it('keeps grouped results and upstream validation status without secret fields', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ brand: 'Ромашка', domain: '', checks: [{ provider_id: 'deepseek', provider_name: 'DeepSeek', summary: { successful: 1, failed: 0, mentioned: 1 }, results: [{ prompt: 'Вопрос', answer: 'Ромашка', mentioned: true, error: null, api_key: 'leak' }] }], api_key: 'leak' }), { headers: { 'content-type': 'application/json' } })).mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Некорректный запрос' }), { status: 400, headers: { 'content-type': 'application/json' } }));
    const good = await proxyJson(request('/api/check', 'POST', { brand: 'Ромашка', prompts: ['Вопрос'], provider_ids: ['deepseek'] }), '/api/check', 'POST');
    const body = await good.json();
    expect(body.checks[0].results[0].answer).toBe('Ромашка');
    expect(JSON.stringify(body)).not.toContain('leak');
    const bad = await proxyJson(request('/api/check', 'POST', { brand: '' }), '/api/check', 'POST');
    expect(bad.status).toBe(400);
    expect(await bad.json()).toEqual({ detail: 'Некорректный запрос' });
  });
});
