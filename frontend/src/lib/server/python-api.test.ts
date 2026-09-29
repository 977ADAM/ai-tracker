import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  apiOrigin, apiTimeoutMs, DEFAULT_TIMEOUT_MS, loadPageData, proxyJson, publicConfig, publicSearchRegions,
  sameOriginRequest,
  publicSearchSnapshot, publicSettingsProvider, publicSearchSettings, searchPath, settingsProviderPath,
  publicRunSnapshot, publicRunList, runPath, runListPath, runExportPath, proxyCsv,
  publicSeoAnalysisCreated, publicSeoHistory, publicSeoRows, publicSeoSettings, publicSeoSettingsTest,
  publicSeoSnapshot, publicSeoTracePage, seoAnalysisCancelPath, seoAnalysisListPath, seoAnalysisPath,
  seoAnalysisRowsPath, seoAnalysisTracePath, SEO_SETTINGS_TEST_TIMEOUT_MS
} from './python-api';
import type { ApiPath } from '$lib/types';

afterEach(() => vi.unstubAllGlobals());

const publicSearchState = {
  yandex: { enabled: true, folder_id: 'folder-1', has_api_key: true,
    api_key_source: 'ui', folder_id_source: 'env' }
};

describe('the same-origin guard of a state-changing request', () => {
  it('accepts the address the browser opened, not only the configured one', () => {
    // The container is opened at 127.0.0.1:3000 while ORIGIN is localhost:3000:
    // both are the same server, and only the request knows which one was used.
    const request = new Request('http://localhost:3000/api/providers/settings', {
      method: 'POST', headers: { origin: 'http://127.0.0.1:3000', host: '127.0.0.1:3000' }
    });

    expect(sameOriginRequest(request)).toBe(true);
  });

  it('falls back to the configured address when no Host header is set', () => {
    const request = new Request('http://127.0.0.1:5173/api/search/settings', {
      method: 'PUT', headers: { origin: 'http://127.0.0.1:5173' }
    });

    expect(sameOriginRequest(request)).toBe(true);
    expect(sameOriginRequest(new Request('http://127.0.0.1:5173/api/search/settings', {
      method: 'PUT', headers: { origin: 'http://localhost:5173' }
    }))).toBe(false);
  });

  it('refuses another site and a request without a usable Origin', () => {
    const crossSite = new Request('http://127.0.0.1:5173/api/providers/settings', {
      method: 'POST', headers: { origin: 'https://other.example', host: '127.0.0.1:5173' }
    });
    const broken = new Request('http://127.0.0.1:5173/api/providers/settings', {
      method: 'POST', headers: { origin: 'not a url', host: '127.0.0.1:5173' }
    });

    expect(sameOriginRequest(crossSite)).toBe(false);
    expect(sameOriginRequest(broken)).toBe(false);
  });

  it('treats a request without an Origin as same-origin', () => {
    const request = new Request('http://127.0.0.1:5173/api/providers/settings', { method: 'POST' });

    expect(sameOriginRequest(request)).toBe(true);
  });
});

describe('the Python API origin guard', () => {
  afterEach(() => vi.unstubAllEnvs());

  it('accepts the loopback API of a local run', () => {
    vi.stubEnv('AI_TRACKER_API_URL', 'http://127.0.0.1:8000');
    vi.stubEnv('AI_TRACKER_API_HOSTS', '');

    expect(apiOrigin()).toBe('http://127.0.0.1:8000');
  });

  it('accepts a host the deployment lists explicitly', () => {
    // A container reaches the API by its compose service name, not by loopback.
    vi.stubEnv('AI_TRACKER_API_URL', 'http://backend:8000');
    vi.stubEnv('AI_TRACKER_API_HOSTS', ' backend , other-host ');

    expect(apiOrigin()).toBe('http://backend:8000');
  });

  it('refuses a host nobody listed', () => {
    vi.stubEnv('AI_TRACKER_API_URL', 'http://evil.example:8000');
    vi.stubEnv('AI_TRACKER_API_HOSTS', 'backend');

    expect(() => apiOrigin()).toThrow('Invalid Python API origin');
  });

  it('keeps refusing a non-http address and a nested path', () => {
    vi.stubEnv('AI_TRACKER_API_HOSTS', 'backend');
    vi.stubEnv('AI_TRACKER_API_URL', 'https://backend:8000');
    expect(() => apiOrigin()).toThrow('Invalid Python API origin');

    vi.stubEnv('AI_TRACKER_API_URL', 'http://backend:8000/api/providers');
    expect(() => apiOrigin()).toThrow('Invalid Python API origin');

    vi.stubEnv('AI_TRACKER_API_URL', 'http://user:secret@backend:8000');
    expect(() => apiOrigin()).toThrow('Invalid Python API origin');
  });
});

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
        new_provider_fields: [], default_provider_ids: []
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

  it('returns the configuration document and drops anything else', () => {
    expect(publicConfig({
      directory: '/tmp/ai-tracker', exists: true,
      content: '{\n  "providers": null\n}', api_key: 'secret'
    })).toEqual({
      directory: '/tmp/ai-tracker', exists: true, content: '{\n  "providers": null\n}'
    });
    expect(publicConfig({ directory: '/tmp/ai-tracker', exists: false, content: null }))
      .toEqual({ directory: '/tmp/ai-tracker', exists: false, content: null });
    expect(() => publicConfig({ directory: '/tmp/ai-tracker', exists: true, content: null })).toThrow();
    expect(() => publicConfig({ directory: '/tmp/ai-tracker', exists: true, content: '' })).toThrow();
  });

  it('projects the configuration document from Python without provider fields', async () => {
    const document = '{\n  "providers": {\n    "groups": []\n  },\n  "search": null,\n  "seo": null\n}';
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      directory: '/tmp/ai-tracker', exists: true, content: document, api_key: 'secret'
    }), { headers: { 'content-type': 'application/json' } })));
    const response = await proxyJson(
      new Request('http://127.0.0.1:5173/api/config'),
      '/api/config',
      'GET'
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ directory: '/tmp/ai-tracker', exists: true, content: document });
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
        new_provider_fields: [], default_provider_ids: []
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

describe('SEO BFF', () => {
  const metric = { denominator: 4, successes: 2, share: 0.5, average_position: 3.5 };
  const searchMetrics = { overall: metric, branded: metric, unbranded: metric };
  const siteAiMetrics = { name: metric, host: metric, combined: metric };
  const siteAiBlock = { ...siteAiMetrics, branded: siteAiMetrics, unbranded: siteAiMetrics };
  const publicSeoState = {
    endpoint: 'https://llm.example.com/v1/chat/completions', model: 'seo-model',
    has_api_key: true, endpoint_source: 'ui', model_source: 'env', api_key_source: 'env'
  } as const;
  const seoSnapshot = {
    id: 'seo-1', status: 'completed', created_at: '2026-09-28T10:00:00Z', updated_at: '2026-09-28T10:20:00Z',
    finished_at: '2026-09-28T10:20:00Z',
    input: { url: 'https://example.ru/', host: 'example.ru', sphere: 'Цветы', seeds: ['a', 'b', 'c'],
      services: ['Букеты'], connection_ids: ['p1'] },
    estimate: { search_upper: 23, model_upper: 20, generated_limit: 20, connections: 1 },
    company_name: 'Ромашка', services: ['Букеты'],
    pages: [{ url: 'https://example.ru/', title: 'Ромашка' }],
    stages: [{ stage: 1, status: 'done', error: null, counters: { pages: 1 }, updated_at: '2026-09-28T10:01:00Z', api_key: 'secret' }],
    agents: [
      { agent: 'supervisor', status: 'done', error: null, updated_at: '2026-09-28T10:20:00Z', api_key: 'secret' },
      { agent: 'site', status: 'error', error: 'Сайт недоступен', updated_at: '2026-09-28T10:03:00Z' }
    ],
    budget: {
      pages: { used: 3, limit: 20 }, searches: { used: 5, limit: 43 },
      model_answers: { used: 4, limit: 40 }, tool_calls: { used: 9, limit: 120 },
      handoffs: { used: 5, limit: 15 }, seed_searches: 3, model_rows: 4, steps: 12,
      agent_steps: { supervisor: 4, site: 3, competitors: 2, queries: 1, checks: 1, report: 1 },
      operation_id: 'secret'
    },
    budget_exhausted: true,
    candidates: [{ host: 'rival.ru', title: 'Rival', occurrences: 2, average_position: 3.5, seed_indexes: [0, 1], recurring: true }],
    queries: [{ index: 0, text: 'букеты с доставкой', category: 'commercial', service: 'Букеты',
      flags: { mentions_company_name: false, mentions_company_host: false, mentions_candidate_host: false, branded: false } }],
    summary: 'Итог',
    conclusions: { summary: 'Выводы', recommendations: 'Рекомендации', model: 'seo-model',
      created_at: '2026-09-28T10:20:00Z', operation_id: 'secret' },
    counters: { queries: 1, search_rows: 1, model_rows: 1, search_errors: 0, model_errors: 0 },
    readiness: { report_ready: true, summary_ready: true, queries_ready: true, has_submitted_search_rows: false,
      has_unsubmitted_search_rows: false, has_unfinished_model_rows: false, search_rows: 1, model_rows: 1 },
    aggregates: {
      site: { search: searchMetrics, ai: { p1: siteAiBlock } },
      competitors: [{ host: 'rival.ru', title: 'Rival', occurrences: 2, average_position: 3.5, seed_indexes: [0, 1],
        search: searchMetrics, ai: { p1: { host: metric } } }],
      categories: { commercial: { search: metric, ai: { p1: metric } } },
      services: { 'Букеты': { search: metric, ai: { p1: metric } } },
      counts: { queries: 1, search_rows: 1, model_rows: 1, search_errors: 0, model_errors: 0 }
    },
    api_key: 'secret', operation_id: 'secret'
  };

  it('projects the SEO settings and drops any unexpected key, including a returned secret', () => {
    expect(publicSeoSettings({ ...publicSeoState, api_key: 'secret', extra: 'private' })).toEqual(publicSeoState);
    expect(publicSeoSettings(publicSeoState)).toEqual(publicSeoState);
    expect(publicSeoSettings({ ...publicSeoState, endpoint: null, model: null })).toEqual({
      ...publicSeoState, endpoint: null, model: null
    });
  });

  it('rejects malformed SEO settings instead of inventing defaults', () => {
    for (const value of [
      {}, { ...publicSeoState, has_api_key: 'yes' }, { ...publicSeoState, endpoint_source: 'other' },
      { ...publicSeoState, model_source: null }, { ...publicSeoState, endpoint: 7 }, 'nope'
    ]) expect(() => publicSeoSettings(value)).toThrow();
  });

  it('projects the connection probe result without leaking an upstream secret', () => {
    expect(publicSeoSettingsTest({ ok: true, model: 'seo-model', tools: true }))
      .toEqual({ ok: true, model: 'seo-model', error: null, tools: true });
    // `tools` is omitted when the probe failed or the model cannot call tools.
    expect(publicSeoSettingsTest({ ok: true, model: 'seo-model' }))
      .toEqual({ ok: true, model: 'seo-model', error: null, tools: null });
    expect(publicSeoSettingsTest({ ok: false, error: 'Модель недоступна', api_key: 'secret' }))
      .toEqual({ ok: false, model: null, error: 'Модель недоступна', tools: null });
    expect(() => publicSeoSettingsTest({ ok: 'yes' })).toThrow();
  });

  it('accepts only opaque analysis IDs, known row kinds and validated cursors in SEO paths', () => {
    expect(seoAnalysisPath('seo-1_X')).toBe('/api/seo/analyses/seo-1_X');
    expect(seoAnalysisCancelPath('seo-1_X')).toBe('/api/seo/analyses/seo-1_X/cancel');
    expect(seoAnalysisRowsPath('seo-1_X', 'model', null)).toBe('/api/seo/analyses/seo-1_X/rows?kind=model');
    expect(seoAnalysisRowsPath('seo-1_X', 'search', 'cur_1')).toBe('/api/seo/analyses/seo-1_X/rows?kind=search&cursor=cur_1');
    expect(seoAnalysisTracePath('seo-1_X', null)).toBe('/api/seo/analyses/seo-1_X/trace');
    expect(seoAnalysisTracePath('seo-1_X', 'cur_1')).toBe('/api/seo/analyses/seo-1_X/trace?cursor=cur_1');
    expect(seoAnalysisListPath(null)).toBe('/api/seo/analyses');
    expect(seoAnalysisListPath('cur_1')).toBe('/api/seo/analyses?cursor=cur_1');
    for (const id of ['../settings', 'a/b', 'a'.repeat(129), '']) expect(() => seoAnalysisPath(id)).toThrow();
    expect(() => seoAnalysisRowsPath('seo-1', 'answers' as 'model', null)).toThrow();
    expect(() => seoAnalysisRowsPath('seo-1', 'model', 'a/b')).toThrow();
    expect(() => seoAnalysisTracePath('seo-1', 'a/b')).toThrow();
    expect(() => seoAnalysisTracePath('a/b', null)).toThrow();
    expect(() => seoAnalysisTracePath('seo-1', 'a'.repeat(257))).toThrow();
    expect(() => seoAnalysisListPath('x&limit=1000')).toThrow();
  });

  it('rejects unknown or forged SEO paths before reaching Python', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    for (const path of [
      '/api/seo/settings/other', '/api/seo/analyses/', '/api/seo/analyses/a/b/rows?kind=model',
      '/api/seo/analyses/seo-1/rows?kind=answers', '/api/seo/analyses/seo-1/rows', '/api/seo/analyses/../settings',
      '/api/seo/analyses/seo-1/trace?cursor=a b', '/api/seo/analyses/seo-1/trace?limit=10',
      '/api/seo/analyses/a/b/trace', '/api/seo/analyses/seo-1/trace/'
    ] as const) {
      expect((await proxyJson(new Request('http://127.0.0.1:5173/api/seo/analyses'), path as ApiPath, 'GET')).status).toBe(400);
    }
    // A wrong method on a settings path is rejected by the shared method check.
    expect((await proxyJson(new Request('http://127.0.0.1:5173/api/seo/settings'),
      '/api/seo/settings', 'DELETE')).status).toBe(405);
    expect((await proxyJson(new Request('http://127.0.0.1:5173/api/seo/settings/test'),
      '/api/seo/settings/test', 'GET')).status).toBe(405);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('keeps the SEO connection test out of the shared short timeout', () => {
    expect(apiTimeoutMs('/api/seo/settings/test')).toBe(SEO_SETTINGS_TEST_TIMEOUT_MS);
    expect(SEO_SETTINGS_TEST_TIMEOUT_MS).toBeGreaterThan(DEFAULT_TIMEOUT_MS);
    expect(apiTimeoutMs('/api/runs')).toBe(DEFAULT_TIMEOUT_MS);
    expect(apiTimeoutMs('/api/check')).toBeUndefined();
  });

  it('proxies settings GET, PUT and credentials DELETE with an exact safe response', async () => {
    const fetchSpy = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({
      ...publicSeoState, api_key: 'secret'
    }), { headers: { 'content-type': 'application/json' } })));
    vi.stubGlobal('fetch', fetchSpy);
    const get = await proxyJson(new Request('http://127.0.0.1:5173/api/seo/settings'), '/api/seo/settings', 'GET');
    expect(get.status).toBe(200);
    expect(await get.json()).toEqual(publicSeoState);
    const put = await proxyJson(new Request('http://127.0.0.1:5173/api/seo/settings', {
      method: 'PUT', headers: { origin: 'http://127.0.0.1:5173', 'content-type': 'application/json' },
      body: JSON.stringify({ endpoint: publicSeoState.endpoint, model: publicSeoState.model })
    }), '/api/seo/settings', 'PUT');
    expect(await put.json()).toEqual(publicSeoState);
    expect(fetchSpy).toHaveBeenLastCalledWith('http://127.0.0.1:8000/api/seo/settings',
      expect.objectContaining({ method: 'PUT', body: JSON.stringify({ endpoint: publicSeoState.endpoint, model: publicSeoState.model }) }));
    const reset = await proxyJson(new Request('http://127.0.0.1:5173/api/seo/settings/credentials',
      { method: 'DELETE' }), '/api/seo/settings/credentials', 'DELETE');
    expect(reset.status).toBe(200);
    expect(await reset.json()).toEqual(publicSeoState);
  });

  it('proxies the bodyless connection probe and reports a safe failure', async () => {
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, model: 'seo-model', tools: true }),
        { headers: { 'content-type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: false, error: 'Модель недоступна' }),
        { headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchSpy);
    const request = new Request('http://127.0.0.1:5173/api/seo/settings/test', { method: 'POST' });
    const ok = await proxyJson(request, '/api/seo/settings/test', 'POST');
    expect(ok.status).toBe(200);
    expect(await ok.json()).toEqual({ ok: true, model: 'seo-model', error: null, tools: true });
    expect(fetchSpy).toHaveBeenLastCalledWith('http://127.0.0.1:8000/api/seo/settings/test',
      expect.objectContaining({ method: 'POST', body: undefined }));
    const failed = await proxyJson(request, '/api/seo/settings/test', 'POST');
    expect(await failed.json()).toEqual({ ok: false, model: null, error: 'Модель недоступна', tools: null });
  });

  it('turns SEO settings failures into a fixed safe error without the upstream text', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'secret-key' }),
      { status: 500, headers: { 'content-type': 'application/json' } })));
    const response = await proxyJson(new Request('http://127.0.0.1:5173/api/seo/settings'), '/api/seo/settings', 'GET');
    expect(response.status).toBe(500);
    expect(await response.json()).toEqual({ detail: 'Ошибка настроек служебной LLM' });
  });

  it('blocks cross-origin SEO writes before reaching Python', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const forged = new Request('http://127.0.0.1:5173/api/seo/settings', {
      method: 'PUT', headers: { origin: 'https://other.example', 'content-type': 'application/json' }, body: '{}'
    });
    expect((await proxyJson(forged, '/api/seo/settings', 'PUT')).status).toBe(403);
    const forgedCreate = new Request('http://127.0.0.1:5173/api/seo/analyses', {
      method: 'POST', headers: { origin: 'https://other.example', 'content-type': 'application/json' }, body: '{}'
    });
    expect((await proxyJson(forgedCreate, '/api/seo/analyses', 'POST')).status).toBe(403);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('projects the 202 analysis creation with its estimate and drops extra fields', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      id: 'seo-1_X', status: 'running', estimate: { search_upper: 23, model_upper: 20, generated_limit: 20, connections: 1 },
      api_key: 'secret', operation_id: 'secret'
    }), { status: 202, headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchSpy);
    const response = await proxyJson(new Request('http://127.0.0.1:5173/api/seo/analyses', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url: 'https://example.ru/' })
    }), '/api/seo/analyses', 'POST');
    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({
      id: 'seo-1_X', status: 'running', estimate: { search_upper: 23, model_upper: 20, generated_limit: 20, connections: 1 }
    });
    expect(publicSeoAnalysisCreated({ id: 'seo-1_X', status: 'running', estimate: { search_upper: 23, model_upper: 20, generated_limit: 20, connections: 1 } }))
      .toEqual({ id: 'seo-1_X', status: 'running', estimate: { search_upper: 23, model_upper: 20, generated_limit: 20, connections: 1 } });
    expect(() => publicSeoAnalysisCreated({ id: 'seo-1', status: 'completed', estimate: {} })).toThrow();
  });

  it('projects a snapshot without answers, secrets or operation IDs', () => {
    const projected = publicSeoSnapshot(seoSnapshot);
    expect(projected).not.toHaveProperty('api_key');
    expect(projected).not.toHaveProperty('operation_id');
    expect(projected.stages[0]).not.toHaveProperty('api_key');
    expect(projected.stages[0]).toEqual({ stage: 1, status: 'done', error: null, counters: { pages: 1 },
      updated_at: '2026-09-28T10:01:00Z' });
    expect(projected.agents).toEqual([
      { agent: 'supervisor', status: 'done', error: null, updated_at: '2026-09-28T10:20:00Z' },
      { agent: 'site', status: 'error', error: 'Сайт недоступен', updated_at: '2026-09-28T10:03:00Z' }
    ]);
    expect(projected.agents[0]).not.toHaveProperty('api_key');
    expect(projected.budget.pages).toEqual({ used: 3, limit: 20 });
    expect(projected.budget.searches).toEqual({ used: 5, limit: 43 });
    expect(projected.budget.model_answers).toEqual({ used: 4, limit: 40 });
    expect(projected.budget.agent_steps.supervisor).toBe(4);
    expect(projected.budget).not.toHaveProperty('operation_id');
    expect(projected.budget_exhausted).toBe(true);
    expect(projected.conclusions).toEqual({ summary: 'Выводы', recommendations: 'Рекомендации', model: 'seo-model' });
    expect(projected.conclusions).not.toHaveProperty('operation_id');
    expect(projected.candidates[0]).toEqual({ host: 'rival.ru', title: 'Rival', occurrences: 2,
      average_position: 3.5, seed_indexes: [0, 1], recurring: true });
    expect(projected.aggregates.site.ai.p1.combined.share).toBe(0.5);
    expect(projected.aggregates.competitors[0].ai.p1.host.average_position).toBe(3.5);
    expect(projected.queries[0].flags.branded).toBe(false);
    expect(projected.summary).toBe('Итог');
    // An analysis without the report agent's block keeps it null, not invented.
    expect(publicSeoSnapshot({ ...seoSnapshot, conclusions: null }).conclusions).toBeNull();
  });

  it('refuses a malformed snapshot instead of inventing values', () => {
    expect(() => publicSeoSnapshot({ ...seoSnapshot, status: 'later' })).toThrow();
    expect(() => publicSeoSnapshot({ ...seoSnapshot, readiness: { ...seoSnapshot.readiness, report_ready: 'yes' } })).toThrow();
    expect(() => publicSeoSnapshot({
      ...seoSnapshot,
      aggregates: { ...seoSnapshot.aggregates, site: { search: searchMetrics, ai: { p1: siteAiMetrics } } }
    })).toThrow();
    expect(() => publicSeoSnapshot({ ...seoSnapshot, stages: [{ stage: 1, status: 'thinking', error: null, counters: {}, updated_at: 'x' }] })).toThrow();
    expect(() => publicSeoSnapshot({ ...seoSnapshot, agents: [{ agent: 'site', status: 'thinking', error: null, updated_at: null }] })).toThrow();
    expect(() => publicSeoSnapshot({ ...seoSnapshot, agents: [{ agent: 'site' }] })).toThrow();
    expect(() => publicSeoSnapshot({ ...seoSnapshot, budget: { ...seoSnapshot.budget, searches: { used: 5 } } })).toThrow();
    expect(() => publicSeoSnapshot({ ...seoSnapshot, budget: { ...seoSnapshot.budget, agent_steps: { supervisor: 'many' } } })).toThrow();
    expect(() => publicSeoSnapshot({ ...seoSnapshot, budget_exhausted: 'yes' })).toThrow();
    expect(() => publicSeoSnapshot({ ...seoSnapshot, conclusions: { summary: 'a', model: 'm' } })).toThrow();
  });

  it('projects history items and pagination cursors', () => {
    const page = publicSeoHistory({
      items: [{ id: 'seo-1_X', created_at: '2026-09-28T10:00:00Z', finished_at: null, status: 'running',
        sphere: 'Цветы', host: 'example.ru', company_name: 'Ромашка',
        counters: { queries: 0, search_rows: 0, model_rows: 0, search_errors: 0, model_errors: 0 }, api_key: 'secret' }],
      next_cursor: 'cur_1', api_key: 'secret'
    });
    expect(page.next_cursor).toBe('cur_1');
    expect(page.items[0]).not.toHaveProperty('api_key');
    expect(page.items[0].status).toBe('running');
    expect(() => publicSeoHistory({ items: [], next_cursor: 'a/b' })).toThrow();
    expect(() => publicSeoHistory({ items: [{ id: 'seo-1', status: 'later' }], next_cursor: null })).toThrow();
  });

  it('projects paginated model and search rows by kind and drops operation IDs', () => {
    const model = publicSeoRows({
      items: [{ query_index: 0, connection_id: 'p1', provider_name: 'Demo', status: 'found', answer: 'Ответ',
        name_mentioned: true, host_mentioned: false, error: null, query: 'букеты', category: 'commercial',
        service: 'Букеты', operation_id: 'secret', api_key: 'secret' }],
      next_cursor: null
    }, 'model');
    expect(model.items[0]).not.toHaveProperty('operation_id');
    expect(model.items[0]).not.toHaveProperty('api_key');
    expect(model.items[0]).toEqual({ query_index: 0, connection_id: 'p1', provider_name: 'Demo', status: 'found',
      answer: 'Ответ', name_mentioned: true, host_mentioned: false, error: null, query: 'букеты',
      category: 'commercial', service: 'Букеты' });

    const search = publicSeoRows({
      items: [{ query_index: 0, query: 'букеты', category: 'commercial', service: 'Букеты', status: 'found',
        site_position: 2, site_url: 'https://example.ru/', error: null, operation_id: 'secret' }],
      next_cursor: 'cur_1'
    }, 'search');
    expect(search.next_cursor).toBe('cur_1');
    expect(search.items[0]).toEqual({ query_index: 0, query: 'букеты', category: 'commercial', service: 'Букеты',
      status: 'found', site_position: 2, site_url: 'https://example.ru/', error: null });

    expect(() => publicSeoRows({ items: [{ query_index: 0, status: 'thinking' }], next_cursor: null }, 'search')).toThrow();
    expect(() => publicSeoRows({ items: [{ query_index: 0, status: 'found' }], next_cursor: null }, 'model')).toThrow();
    expect(() => publicSeoRows({ items: [], next_cursor: 'a b' }, 'search')).toThrow();
  });

  it('projects trace pages step by step and drops secrets and unknown fields', () => {
    const page = publicSeoTracePage({
      items: [
        { step_index: 1, agent: 'supervisor', kind: 'handoff', name: 'handoff_to',
          arguments: { agent: 'site' }, result_summary: '{"status":"accepted"}', status: 'done',
          error: null, created_at: '2026-09-28T10:01:00Z', api_key: 'secret', operation_id: 'secret' },
        { step_index: 2, agent: 'site', kind: 'tool', name: 'fetch_site',
          arguments: { max_pages: 2 }, result_summary: null, status: 'rejected',
          error: 'Лимит прогона исчерпан', created_at: '2026-09-28T10:02:00Z' }
      ],
      next_cursor: 'cur_1', api_key: 'secret'
    });
    expect(page.next_cursor).toBe('cur_1');
    expect(page.items[0]).toEqual({ step_index: 1, agent: 'supervisor', kind: 'handoff', name: 'handoff_to',
      arguments: { agent: 'site' }, result_summary: '{"status":"accepted"}', status: 'done', error: null,
      created_at: '2026-09-28T10:01:00Z' });
    expect(page.items[0]).not.toHaveProperty('api_key');
    expect(page.items[0]).not.toHaveProperty('operation_id');
    expect(page.items[1].arguments).toEqual({ max_pages: 2 });
    expect(page.items[1].error).toBe('Лимит прогона исчерпан');
    expect(publicSeoTracePage({ items: [], next_cursor: null })).toEqual({ items: [], next_cursor: null });
  });

  it('refuses structurally broken trace pages and cursors', () => {
    const step = { step_index: 1, agent: 'site', kind: 'tool', name: 'fetch_site',
      arguments: {}, result_summary: null, status: 'done', error: null, created_at: 'x' };
    expect(() => publicSeoTracePage({ items: [{ ...step, kind: 'thinking' }], next_cursor: null })).toThrow();
    expect(() => publicSeoTracePage({ items: [{ ...step, status: 'thinking' }], next_cursor: null })).toThrow();
    expect(() => publicSeoTracePage({ items: [{ ...step, arguments: 'nope' }], next_cursor: null })).toThrow();
    expect(() => publicSeoTracePage({ items: [{ ...step, step_index: '1' }], next_cursor: null })).toThrow();
    expect(() => publicSeoTracePage({ items: [{ ...step, name: '' }], next_cursor: null })).toThrow();
    expect(() => publicSeoTracePage({ items: [], next_cursor: 'a b' })).toThrow();
    expect(() => publicSeoTracePage({ next_cursor: null })).toThrow();
  });

  it('serves snapshots, rows, trace, cancel and delete through their exact SEO paths', async () => {
    const snapshotBody = JSON.stringify({ ...seoSnapshot, api_key: 'secret' });
    const fetchSpy = vi.fn().mockImplementation((url: string, init: RequestInit) => {
      if (init.method === 'DELETE') return Promise.resolve(new Response(null, { status: 204 }));
      if (String(url).includes('/trace')) return Promise.resolve(new Response(JSON.stringify({
        items: [{ step_index: 1, agent: 'site', kind: 'tool', name: 'fetch_site', arguments: { max_pages: 2 },
          result_summary: '{"used_pages":1}', status: 'done', error: null,
          created_at: '2026-09-28T10:01:00Z', operation_id: 'secret', api_key: 'secret' }],
        next_cursor: null, api_key: 'secret'
      }), { headers: { 'content-type': 'application/json' } }));
      if (String(url).includes('/rows?kind=')) return Promise.resolve(new Response(JSON.stringify({
        items: [{ query_index: 0, query: 'букеты', category: 'commercial', service: 'Букеты', status: 'found',
          site_position: 2, site_url: 'https://example.ru/', error: null, operation_id: 'secret' }],
        next_cursor: null
      }), { headers: { 'content-type': 'application/json' } }));
      return Promise.resolve(new Response(snapshotBody, { headers: { 'content-type': 'application/json' } }));
    });
    vi.stubGlobal('fetch', fetchSpy);
    const snapshot = await proxyJson(new Request(`http://127.0.0.1:5173${seoAnalysisPath('seo-1_X')}`),
      seoAnalysisPath('seo-1_X'), 'GET');
    expect(snapshot.status).toBe(200);
    const snapshotJson = await snapshot.json() as Record<string, unknown>;
    expect(snapshotJson).not.toHaveProperty('api_key');
    expect(snapshotJson).toHaveProperty('budget_exhausted', true);

    const rows = await proxyJson(new Request('http://127.0.0.1:5173/api/seo/analyses/seo-1_X/rows?kind=search'),
      seoAnalysisRowsPath('seo-1_X', 'search', null), 'GET');
    expect(await rows.json()).toEqual({ items: [{ query_index: 0, query: 'букеты', category: 'commercial',
      service: 'Букеты', status: 'found', site_position: 2, site_url: 'https://example.ru/', error: null }], next_cursor: null });

    const trace = await proxyJson(new Request('http://127.0.0.1:5173/api/seo/analyses/seo-1_X/trace?cursor=cur_1'),
      seoAnalysisTracePath('seo-1_X', 'cur_1'), 'GET');
    expect(trace.status).toBe(200);
    expect(await trace.json()).toEqual({ items: [{ step_index: 1, agent: 'site', kind: 'tool', name: 'fetch_site',
      arguments: { max_pages: 2 }, result_summary: '{"used_pages":1}', status: 'done', error: null,
      created_at: '2026-09-28T10:01:00Z' }], next_cursor: null });
    expect(fetchSpy).toHaveBeenLastCalledWith('http://127.0.0.1:8000/api/seo/analyses/seo-1_X/trace?cursor=cur_1',
      expect.objectContaining({ method: 'GET' }));

    const cancel = await proxyJson(new Request(`http://127.0.0.1:5173${seoAnalysisCancelPath('seo-1_X')}`, { method: 'POST' }),
      seoAnalysisCancelPath('seo-1_X'), 'POST');
    expect(cancel.status).toBe(200);
    expect(fetchSpy).toHaveBeenLastCalledWith('http://127.0.0.1:8000/api/seo/analyses/seo-1_X/cancel',
      expect.objectContaining({ method: 'POST' }));

    const deleted = await proxyJson(new Request(`http://127.0.0.1:5173${seoAnalysisPath('seo-1_X')}`, { method: 'DELETE' }),
      seoAnalysisPath('seo-1_X'), 'DELETE');
    expect(deleted.status).toBe(204);
    expect(await deleted.text()).toBe('');
  });

  it('passes a safe detail through for a failed analysis request', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Анализ не найден' }),
      { status: 404, headers: { 'content-type': 'application/json' } })));
    const response = await proxyJson(new Request(`http://127.0.0.1:5173${seoAnalysisPath('seo-1_X')}`),
      seoAnalysisPath('seo-1_X'), 'GET');
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ detail: 'Анализ не найден' });
  });

  it('passes a safe trace detail through for a rejected cursor and an unknown analysis', async () => {
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Некорректный курсор', operation_id: 'secret' }),
        { status: 400, headers: { 'content-type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Анализ не найден' }),
        { status: 404, headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchSpy);
    const badCursor = await proxyJson(new Request('http://127.0.0.1:5173/api/seo/analyses/seo-1_X/trace?cursor=cur_1'),
      seoAnalysisTracePath('seo-1_X', 'cur_1'), 'GET');
    expect(badCursor.status).toBe(400);
    expect(await badCursor.json()).toEqual({ detail: 'Некорректный курсор' });
    const missing = await proxyJson(new Request('http://127.0.0.1:5173/api/seo/analyses/seo-1_X/trace'),
      seoAnalysisTracePath('seo-1_X', null), 'GET');
    expect(missing.status).toBe(404);
    expect(await missing.json()).toEqual({ detail: 'Анализ не найден' });
  });

  it('loads SEO settings independently from the model configuration', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (String(url).endsWith('/api/seo/settings')) return Promise.resolve(new Response(JSON.stringify({
        ...publicSeoState, api_key: 'secret'
      }), { headers: { 'content-type': 'application/json' } }));
      if (String(url).endsWith('/api/search/settings')) return Promise.resolve(new Response('nope', { status: 500 }));
      if (String(url).endsWith('/api/search/regions')) return Promise.resolve(new Response('[]', { headers: { 'content-type': 'application/json' } }));
      return Promise.resolve(new Response('nope', { status: 500 }));
    }));
    const data = await loadPageData();
    expect(data.seoSettings).toEqual(publicSeoState);
    expect(data.seoSettings).not.toHaveProperty('api_key');
    expect(data.seoSettingsError).toBe('');
    expect(data.loadError).not.toBe('');
    expect(data.searchSettingsError).not.toBe('');
  });

  it('keeps the model configuration when the SEO settings resource fails', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (String(url).endsWith('/api/seo/settings')) return Promise.resolve(new Response('nope', { status: 500 }));
      if (String(url).endsWith('/api/search/settings')) return Promise.resolve(new Response(JSON.stringify({
        yandex: publicSearchState.yandex
      }), { headers: { 'content-type': 'application/json' } }));
      if (String(url).endsWith('/api/search/regions')) return Promise.resolve(new Response('[]', { headers: { 'content-type': 'application/json' } }));
      if (String(url).endsWith('/api/providers/settings')) return Promise.resolve(new Response('[]', { headers: { 'content-type': 'application/json' } }));
      if (String(url).endsWith('/api/form')) return Promise.resolve(new Response(JSON.stringify({
        limits: { max_prompts: 20, max_providers: 5, max_prompt_length: 500, max_brand_length: 100, max_domain_length: 253 },
        new_provider_fields: [], default_provider_ids: []
      }), { headers: { 'content-type': 'application/json' } }));
      return Promise.resolve(new Response(JSON.stringify([
        { id: 'p1', name: 'Demo', kind: 'openai', endpoint: 'https://api.example.com/chat/completions', model: 'm', configured: true }
      ]), { headers: { 'content-type': 'application/json' } }));
    }));
    const data = await loadPageData();
    expect(data.seoSettings).toBeNull();
    expect(data.seoSettingsError).toBe('Настройки служебной LLM недоступны');
    expect(data.loadError).toBe('');
    expect(data.providers.map((provider) => provider.id)).toEqual(['p1']);
    expect(data.searchSettings).toEqual(publicSearchState.yandex);
  });
});
