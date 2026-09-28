import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  loadPageData, proxyJson, publicConfigurationFile, publicSearchRegions, publicSearchSnapshot,
  publicSettingsProvider, publicSearchSettings, searchPath, settingsProviderPath
  , publicRunSnapshot, publicRunList, runPath, runListPath, runExportPath, proxyCsv
} from './python-api';

afterEach(() => vi.unstubAllGlobals());

const publicSearchState = {
  yandex: { enabled: true, folder_id: 'folder-1', has_api_key: true,
    api_key_source: 'ui', folder_id_source: 'env' }
};

describe('search settings BFF', () => {
  it('projects exactly the public settings fields and drops a returned key', () => {
    expect(publicSearchSettings({ yandex: { ...publicSearchState.yandex, api_key: 'secret', extra: 'private' }, extra: 'private' }))
      .toEqual(publicSearchState);
  });

  it('rejects malformed public settings rather than inventing defaults', () => {
    for (const value of [
      {}, { yandex: { ...publicSearchState.yandex, enabled: 'true' } },
      { yandex: { ...publicSearchState.yandex, folder_id: 1 } },
      { yandex: { ...publicSearchState.yandex, has_api_key: 'yes' } },
      { yandex: { ...publicSearchState.yandex, api_key_source: 'other' } },
      { yandex: { ...publicSearchState.yandex, folder_id_source: null } }
    ]) expect(() => publicSearchSettings(value)).toThrow();
  });

  it('proxies GET and PUT with an exact safe response and an unchanged write body', async () => {
    const fetchSpy = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({
      yandex: { ...publicSearchState.yandex, api_key: 'secret' }
    }), { headers: { 'content-type': 'application/json' } })));
    vi.stubGlobal('fetch', fetchSpy);
    const get = await proxyJson(new Request('http://127.0.0.1:5173/api/search/settings'), '/api/search/settings', 'GET');
    expect(get.status).toBe(200);
    expect(await get.json()).toEqual(publicSearchState);
    const put = await proxyJson(new Request('http://127.0.0.1:5173/api/search/settings', {
      method: 'PUT', headers: { origin: 'http://127.0.0.1:5173', 'content-type': 'application/json' },
      body: JSON.stringify({ enabled: false, api_key: 'new-key' })
    }), '/api/search/settings', 'PUT');
    expect(await put.json()).toEqual(publicSearchState);
    expect(fetchSpy).toHaveBeenLastCalledWith('http://127.0.0.1:8000/api/search/settings',
      expect.objectContaining({ method: 'PUT', body: JSON.stringify({ enabled: false, api_key: 'new-key' }) }));
  });

  it('proxies credentials DELETE without a request body and projects its 200 response', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(new Response(JSON.stringify(publicSearchState),
      { headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchSpy);
    const response = await proxyJson(new Request('http://127.0.0.1:5173/api/search/settings/credentials',
      { method: 'DELETE' }), '/api/search/settings/credentials', 'DELETE');
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(publicSearchState);
    expect(fetchSpy).toHaveBeenCalledWith('http://127.0.0.1:8000/api/search/settings/credentials',
      expect.objectContaining({ method: 'DELETE', body: undefined }));
  });

  it('blocks cross-origin writes and unsupported settings methods', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const forged = new Request('http://127.0.0.1:5173/api/search/settings', {
      method: 'PUT', headers: { origin: 'https://other.example', 'content-type': 'application/json' }, body: '{}'
    });
    expect((await proxyJson(forged, '/api/search/settings', 'PUT')).status).toBe(403);
    const forgedDelete = new Request('http://127.0.0.1:5173/api/search/settings/credentials', {
      method: 'DELETE', headers: { origin: 'https://other.example' }
    });
    expect((await proxyJson(forgedDelete, '/api/search/settings/credentials', 'DELETE')).status).toBe(403);
    expect((await proxyJson(new Request('http://127.0.0.1:5173/api/search/settings'),
      '/api/search/settings', 'DELETE')).status).toBe(405);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('returns a safe error when Python sends malformed settings or a secret in an error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ yandex: { enabled: true, api_key: 'secret' } }),
      { headers: { 'content-type': 'application/json' } })).mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'secret-key' }),
      { status: 500, headers: { 'content-type': 'application/json' } })));
    const request = new Request('http://127.0.0.1:5173/api/search/settings');
    const malformed = await proxyJson(request, '/api/search/settings', 'GET');
    expect(malformed.status).toBe(502);
    expect(await malformed.text()).not.toContain('secret');
    const failed = await proxyJson(request, '/api/search/settings', 'GET');
    expect(failed.status).toBe(500);
    expect(await failed.text()).not.toContain('secret-key');
  });

  it('loads search settings independently from model configuration', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (String(url).endsWith('/api/search/settings')) return Promise.resolve(new Response('nope', { status: 500 }));
      if (String(url).endsWith('/api/search/regions')) return Promise.resolve(new Response('[]', { headers: { 'content-type': 'application/json' } }));
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
    expect(data.providers.map((provider) => provider.id)).toEqual(['p1']);
    expect(data.form).not.toBeNull();
    expect(data.loadError).toBe('');
    expect(data.searchSettings).toBeNull();
    expect(data.searchSettingsError).toBe('Настройки поисковых систем недоступны');
  });

  it('loads and projects valid search settings even when model configuration fails', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (String(url).endsWith('/api/search/settings')) return Promise.resolve(new Response(JSON.stringify({
        yandex: { ...publicSearchState.yandex, api_key: 'secret' }
      }), { headers: { 'content-type': 'application/json' } }));
      if (String(url).endsWith('/api/search/regions')) return Promise.resolve(new Response('[]', { headers: { 'content-type': 'application/json' } }));
      return Promise.resolve(new Response('nope', { status: 500 }));
    }));
    const data = await loadPageData();
    expect(data.searchSettings).toEqual(publicSearchState.yandex);
    expect(data.searchSettings).not.toHaveProperty('api_key');
    expect(data.searchSettingsError).toBe('');
    expect(data.loadError).not.toBe('');
  });
});

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

describe('run BFF', () => {
  const snapshot = {
    id: 'abc-123_X', created_at: '2026-09-25T14:00:00Z', finished_at: null, status: 'pending',
    brand: 'Ромашка', domain: 'example.ru', prompts: ['цветы'], provider_ids: ['p'], regions: [1],
    models: [{ provider_id: 'p', prompt_index: 0, provider_name: 'Demo', prompt: 'цветы',
      status: 'pending', answer: null, mentioned: null, error: null, api_key: 'secret' }],
    search: [{ search_index: 0, prompt_index: 0, region_index: 0, prompt: 'цветы', region_id: 1,
      region_name: 'Москва', status: 'submitting', position: null, url: null, error: null, operation_id: 'secret' }],
    summary_rows: [{ prompt: 'цветы', source: 'Яндекс', language: 'ru', region: 'Москва', ai_answer: '—',
      site_found: '—', position: '—', brand_found: '—', status: 'Выполняется', api_key: 'secret' }],
    api_key: 'secret'
  };

  it('accepts only opaque IDs and validated cursors', () => {
    expect(runPath('abc-123_X')).toBe('/api/runs/abc-123_X');
    expect(runExportPath('abc-123_X')).toBe('/api/runs/abc-123_X/export.csv');
    expect(runListPath('abc_X')).toBe('/api/runs?cursor=abc_X');
    for (const id of ['../providers', 'a/b', 'a'.repeat(129), '']) expect(() => runPath(id)).toThrow();
    for (const cursor of ['a/b', 'x&limit=1000', 'a'.repeat(257)]) expect(() => runListPath(cursor)).toThrow();
  });

  it('projects snapshots and history without secret fields', () => {
    const projected = publicRunSnapshot(snapshot);
    expect(projected).not.toHaveProperty('api_key');
    expect(projected.models[0]).not.toHaveProperty('api_key');
    expect(projected.search[0]).not.toHaveProperty('operation_id');
    expect(projected.summary_rows[0]).not.toHaveProperty('api_key');
    expect(publicRunList({ items: [{ id: 'abc-123_X', created_at: snapshot.created_at,
      status: 'pending', prompts: ['цветы'], api_key: 'secret' }], next_cursor: null, api_key: 'secret' }))
      .toEqual({ items: [{ id: 'abc-123_X', created_at: snapshot.created_at,
        status: 'pending', prompts: ['цветы'] }], next_cursor: null });
  });

  it('blocks cross-origin deletes and handles empty 204 responses', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const forged = new Request('http://127.0.0.1:5173/api/runs/abc-123_X',
      { method: 'DELETE', headers: { origin: 'https://other.example' } });
    expect((await proxyJson(forged, runPath('abc-123_X'), 'DELETE')).status).toBe(403);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockResolvedValue(new Response(null, { status: 204 }));
    const local = new Request('http://127.0.0.1:5173/api/runs/abc-123_X', { method: 'DELETE' });
    expect((await proxyJson(local, runPath('abc-123_X'), 'DELETE')).status).toBe(204);
  });

  it('rejects malformed JSON and preserves CSV bytes and safe headers', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{bad',
      { headers: { 'content-type': 'application/json' } })));
    expect((await proxyJson(new Request('http://127.0.0.1:5173/api/runs/abc-123_X'),
      runPath('abc-123_X'), 'GET')).status).toBe(502);
    const bytes = new Uint8Array([0xef, 0xbb, 0xbf, 0x61, 0x3b, 0x62]);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(bytes, { headers: {
      'content-type': 'text/csv; charset=utf-8', 'content-disposition': 'attachment; filename="evil.html"',
      'x-api-key': 'secret'
    } })));
    const response = await proxyCsv(new Request('http://127.0.0.1:5173/api/runs/abc-123_X/export.csv'), runExportPath('abc-123_X'));
    expect(Array.from(new Uint8Array(await response.arrayBuffer()))).toEqual(Array.from(bytes));
    expect(response.headers.get('content-type')).toContain('text/csv');
    expect(response.headers.get('content-disposition')).not.toContain('evil.html');
    expect(response.headers.get('x-api-key')).toBeNull();
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
