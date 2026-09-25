import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  loadPageData, proxyJson, publicConfigurationFile, publicSearchRegions, publicSearchSnapshot,
  publicSettingsProvider, searchPath, settingsProviderPath
} from './python-api';

afterEach(() => vi.unstubAllGlobals());

describe('provider settings BFF', () => {
  it('removes secrets from provider groups and model rows', () => {
    const projected = publicSettingsProvider({
      id: 'group-1', name: 'Demo', endpoint: 'https://api.example.com/chat/completions',
      kind: 'openai', configured: true, api_key: 'secret',
      models: [{ id: 'model-1', model: 'api-model', name: 'Demo model', api_key: 'secret' }]
    });
    expect(projected).not.toHaveProperty('api_key');
    expect(projected.models).toEqual([{ id: 'model-1', model: 'api-model', name: 'Demo model' }]);
  });

  it('allows only stable provider IDs in settings item paths', () => {
    expect(settingsProviderPath('group-1')).toBe('/api/providers/settings/group-1');
    expect(() => settingsProviderPath('../check')).toThrow();
  });

  it('rejects malformed settings data instead of exposing invented values', () => {
    expect(() => publicSettingsProvider({
      id: 'group-1', name: 'Demo', endpoint: 'https://api.example.com/chat/completions',
      kind: 'openai', configured: true, models: [{ model: 'api-model', name: 'Demo model' }]
    })).toThrow();
  });

  it('returns the configuration file text and drops anything else', () => {
    expect(publicConfigurationFile({
      path: '/tmp/ai-tracker/providers.json', exists: true, content: '{"version":2}\n', api_key: 'secret'
    })).toEqual({ path: '/tmp/ai-tracker/providers.json', exists: true, content: '{"version":2}\n' });
    expect(publicConfigurationFile({
      path: '/tmp/ai-tracker/providers.json', exists: false, content: null
    })).toEqual({ path: '/tmp/ai-tracker/providers.json', exists: false, content: null });
    expect(() => publicConfigurationFile({ path: '/tmp/providers.json', exists: true, content: null })).toThrow();
  });

  it('projects the configuration file from Python without provider fields', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      path: '/tmp/ai-tracker/providers.json', exists: true, content: '{"version":2}\n', api_key: 'secret'
    }), { headers: { 'content-type': 'application/json' } })));
    const response = await proxyJson(
      new Request('http://127.0.0.1:5173/api/providers/settings/file'),
      '/api/providers/settings/file',
      'GET'
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      path: '/tmp/ai-tracker/providers.json', exists: true, content: '{"version":2}\n'
    });
  });

  it('projects settings list responses from Python', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify([{
      id: 'group-1', name: 'Demo', kind: 'openai', endpoint: 'https://api.example.com/chat/completions',
      configured: true, api_key: 'secret', models: [{ id: 'model-1', model: 'api-a', name: 'A' }]
    }]), { headers: { 'content-type': 'application/json' } })));
    const response = await proxyJson(new Request('http://127.0.0.1:5173/api/providers/settings'), '/api/providers/settings', 'GET');
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual([{
      id: 'group-1', name: 'Demo', kind: 'openai', endpoint: 'https://api.example.com/chat/completions',
      configured: true, models: [{ id: 'model-1', model: 'api-a', name: 'A' }]
    }]);
  });

  it('blocks cross-origin settings writes before reaching Python', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const request = new Request('http://127.0.0.1:5173/api/providers/settings', {
      method: 'POST', headers: { origin: 'https://other.example', 'content-type': 'application/json' }, body: '{}'
    });
    const response = await proxyJson(request, '/api/providers/settings', 'POST');
    expect(response.status).toBe(403);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('rejects oversized writes and non-JSON upstream responses', async () => {
    const largeRequest = new Request('http://127.0.0.1:5173/api/providers/settings', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ data: 'x'.repeat(65_536) })
    });
    expect((await proxyJson(largeRequest, '/api/providers/settings', 'POST')).status).toBe(413);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>broken</html>', { headers: { 'content-type': 'text/html' } })));
    const response = await proxyJson(new Request('http://127.0.0.1:5173/api/providers/settings'), '/api/providers/settings', 'GET');
    expect(response.status).toBe(502);
  });
});

describe('search BFF', () => {
  it('allows only opaque job IDs in search paths', () => {
    expect(searchPath('abc-123_X')).toBe('/api/search/abc-123_X');
    for (const id of ['', '../providers', 'a/b', 'a'.repeat(129), 'id with space']) {
      expect(() => searchPath(id)).toThrow();
    }
  });

  it('rejects unknown search paths', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    for (const path of ['/api/search/regions/extra', '/api/search/', '/api/search/a/b'] as const) {
      const response = await proxyJson(new Request('http://127.0.0.1:5173/api/search'), path, 'GET');
      expect(response.status).toBe(400);
    }
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('returns only the public fields of a created job', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      id: 'job-1', total: 2, status: 'pending', api_key: 'private', folder_id: 'private', operation_id: 'private'
    }), { status: 202, headers: { 'content-type': 'application/json' } })));
    const response = await proxyJson(
      new Request('http://127.0.0.1:5173/api/search', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' }),
      '/api/search',
      'POST'
    );
    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({ id: 'job-1', total: 2, status: 'pending' });
  });

  it('strips operation IDs and credentials from a snapshot', () => {
    const projected = publicSearchSnapshot({
      id: 'job-1', domain: 'example.ru', regions: [1], total: 1, completed: 1, status: 'done',
      summary: { successful: 1, found: 1, failed: 0 },
      api_key: 'private', folder_id: 'private',
      results: [{
        prompt: 'цветы', region_id: 1, region_name: 'Москва и Московская область',
        status: 'found', position: 2, url: 'https://shop.example.ru/x', error: null,
        operation_id: 'private', api_key: 'private'
      }]
    });
    expect(projected).not.toHaveProperty('api_key');
    expect(projected).not.toHaveProperty('folder_id');
    expect(projected).toEqual({
      id: 'job-1', domain: 'example.ru', regions: [1], total: 1, completed: 1, status: 'done',
      summary: { successful: 1, found: 1, failed: 0 },
      results: [{
        prompt: 'цветы', region_id: 1, region_name: 'Москва и Московская область',
        status: 'found', position: 2, url: 'https://shop.example.ru/x', error: null
      }]
    });
    expect(publicSearchSnapshot({
      id: 'job-2', domain: 'example.ru', regions: [1, 213], total: 2, completed: 1, status: 'pending',
      summary: { successful: 1, found: 1, failed: 0 },
      results: [{ prompt: 'цветы', region_id: 213, region_name: 'Москва', status: 'error', position: null, url: null, error: 'Не удалось получить выдачу Яндекса' }]
    }).results[0].error).toBe('Не удалось получить выдачу Яндекса');
  });

  it('refuses a malformed snapshot instead of inventing values', () => {
    expect(() => publicSearchSnapshot({ id: 'job-1', domain: 'example.ru', regions: [1], total: 1, completed: 0, status: 'later', summary: {}, results: [] })).toThrow();
    expect(() => publicSearchSnapshot({
      id: 'job-1', domain: 'example.ru', regions: [1], total: 1, completed: 0, status: 'pending',
      summary: { successful: 0, found: 0, failed: 0 },
      results: [{ prompt: 'цветы', region_id: 1, region_name: 'Москва', status: 'thinking', position: null, url: null, error: null }]
    })).toThrow();
  });

  it('keeps the region catalog to id and name', () => {
    expect(publicSearchRegions([
      { id: 1, name: 'Москва и Московская область', extra: 'private' },
      { id: 213, name: 'Москва' }
    ])).toEqual([{ id: 1, name: 'Москва и Московская область' }, { id: 213, name: 'Москва' }]);
    expect(() => publicSearchRegions([{ id: '1', name: 'Москва' }])).toThrow();
    expect(() => publicSearchRegions('nope')).toThrow();
  });

  it('keeps a forged or expired job at 404', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: 'Задача поиска не найдена', operation_id: 'private'
    }), { status: 404, headers: { 'content-type': 'application/json' } })));
    const response = await proxyJson(
      new Request('http://127.0.0.1:5173/api/search/job-1'),
      searchPath('job-1'),
      'GET'
    );
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ detail: 'Задача поиска не найдена' });
  });

  it('blocks a cross-origin search before reaching Python', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const request = new Request('http://127.0.0.1:5173/api/search', {
      method: 'POST', headers: { origin: 'https://other.example', 'content-type': 'application/json' }, body: '{}'
    });
    expect((await proxyJson(request, '/api/search', 'POST')).status).toBe(403);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('turns a non-JSON search response into a safe 502', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>secret-value</html>', { headers: { 'content-type': 'text/html' } })));
    const response = await proxyJson(new Request('http://127.0.0.1:5173/api/search/job-1'), searchPath('job-1'), 'GET');
    expect(response.status).toBe(502);
    expect(await response.text()).not.toContain('secret-value');
  });

  it('loads the region catalog independently of the model list', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (String(url).endsWith('/api/search/regions')) return Promise.resolve(new Response('nope', { status: 500 }));
      if (String(url).endsWith('/api/providers/settings')) return Promise.resolve(new Response('[]', { headers: { 'content-type': 'application/json' } }));
      if (String(url).endsWith('/api/form')) return Promise.resolve(new Response(JSON.stringify({
        limits: { max_prompts: 20, max_providers: 5, max_prompt_length: 500, max_brand_length: 100, max_domain_length: 253 },
        new_provider_fields: [], default_provider_ids: [], scope_options: []
      }), { headers: { 'content-type': 'application/json' } }));
      return Promise.resolve(new Response(JSON.stringify([
        { id: 'p1', name: 'Demo', kind: 'openai', endpoint: 'https://api.example.com/chat/completions', model: 'm', configured: true }
      ]), { headers: { 'content-type': 'application/json' } }));
    }));
    const data = await loadPageData();
    expect(data.loadError).toBe('');
    expect(data.providers.map((provider) => provider.id)).toEqual(['p1']);
    expect(data.searchRegions).toEqual([]);
    expect(data.searchRegionError).toBe('Справочник регионов недоступен');
  });
});
