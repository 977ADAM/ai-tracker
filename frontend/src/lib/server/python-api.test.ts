import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  apiOrigin,
  apiTimeoutMs,
  DEFAULT_TIMEOUT_MS,
  loadPageData,
  proxyJson,
  publicConfig,
  sameOriginRequest,
  publicSettingsProvider,
  publicSearchSettings,
  settingsProviderPath,
  publicSeoSettings,
  publicSeoSettingsTest,
  SEO_SETTINGS_TEST_TIMEOUT_MS,
} from './python-api';
import type { ApiPath } from '$lib/types';

afterEach(() => vi.unstubAllGlobals());

const publicSearchState = {
  yandex: {
    enabled: true,
    folder_id: 'folder-1',
    has_api_key: true,
    api_key_source: 'ui',
    folder_id_source: 'env',
  },
};

describe('the same-origin guard of a state-changing request', () => {
  it('accepts the address the browser opened, not only the configured one', () => {
    // The container is opened at 127.0.0.1:3000 while ORIGIN is localhost:3000:
    // both are the same server, and only the request knows which one was used.
    const request = new Request('http://localhost:3000/api/providers/settings', {
      method: 'POST',
      headers: { origin: 'http://127.0.0.1:3000', host: '127.0.0.1:3000' },
    });

    expect(sameOriginRequest(request)).toBe(true);
  });

  it('falls back to the configured address when no Host header is set', () => {
    const request = new Request('http://127.0.0.1:5173/api/search/settings', {
      method: 'PUT',
      headers: { origin: 'http://127.0.0.1:5173' },
    });

    expect(sameOriginRequest(request)).toBe(true);
    expect(
      sameOriginRequest(
        new Request('http://127.0.0.1:5173/api/search/settings', {
          method: 'PUT',
          headers: { origin: 'http://localhost:5173' },
        }),
      ),
    ).toBe(false);
  });

  it('refuses another site and a request without a usable Origin', () => {
    const crossSite = new Request('http://127.0.0.1:5173/api/providers/settings', {
      method: 'POST',
      headers: { origin: 'https://other.example', host: '127.0.0.1:5173' },
    });
    const broken = new Request('http://127.0.0.1:5173/api/providers/settings', {
      method: 'POST',
      headers: { origin: 'not a url', host: '127.0.0.1:5173' },
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
    expect(
      publicSearchSettings({
        yandex: { ...publicSearchState.yandex, api_key: 'secret', extra: 'private' },
        extra: 'private',
      }),
    ).toEqual(publicSearchState);
  });

  it('rejects malformed public settings rather than inventing defaults', () => {
    for (const value of [
      {},
      { yandex: { ...publicSearchState.yandex, enabled: 'true' } },
      { yandex: { ...publicSearchState.yandex, folder_id: 1 } },
      { yandex: { ...publicSearchState.yandex, has_api_key: 'yes' } },
      { yandex: { ...publicSearchState.yandex, api_key_source: 'other' } },
      { yandex: { ...publicSearchState.yandex, folder_id_source: null } },
    ])
      expect(() => publicSearchSettings(value)).toThrow();
  });

  it('proxies GET and PUT with an exact safe response and an unchanged write body', async () => {
    const fetchSpy = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            yandex: { ...publicSearchState.yandex, api_key: 'secret' },
          }),
          { headers: { 'content-type': 'application/json' } },
        ),
      ),
    );
    vi.stubGlobal('fetch', fetchSpy);
    const get = await proxyJson(
      new Request('http://127.0.0.1:5173/api/search/settings'),
      '/api/search/settings',
      'GET',
    );
    expect(get.status).toBe(200);
    expect(await get.json()).toEqual(publicSearchState);
    const put = await proxyJson(
      new Request('http://127.0.0.1:5173/api/search/settings', {
        method: 'PUT',
        headers: { origin: 'http://127.0.0.1:5173', 'content-type': 'application/json' },
        body: JSON.stringify({ enabled: false, api_key: 'new-key' }),
      }),
      '/api/search/settings',
      'PUT',
    );
    expect(await put.json()).toEqual(publicSearchState);
    expect(fetchSpy).toHaveBeenLastCalledWith(
      'http://127.0.0.1:8000/api/search/settings',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ enabled: false, api_key: 'new-key' }),
      }),
    );
  });

  it('proxies credentials DELETE without a request body and projects its 200 response', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(publicSearchState), {
        headers: { 'content-type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchSpy);
    const response = await proxyJson(
      new Request('http://127.0.0.1:5173/api/search/settings/credentials', { method: 'DELETE' }),
      '/api/search/settings/credentials',
      'DELETE',
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(publicSearchState);
    expect(fetchSpy).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/search/settings/credentials',
      expect.objectContaining({ method: 'DELETE', body: undefined }),
    );
  });

  it('blocks cross-origin writes and unsupported settings methods', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const forged = new Request('http://127.0.0.1:5173/api/search/settings', {
      method: 'PUT',
      headers: { origin: 'https://other.example', 'content-type': 'application/json' },
      body: '{}',
    });
    expect((await proxyJson(forged, '/api/search/settings', 'PUT')).status).toBe(403);
    const forgedDelete = new Request('http://127.0.0.1:5173/api/search/settings/credentials', {
      method: 'DELETE',
      headers: { origin: 'https://other.example' },
    });
    expect(
      (await proxyJson(forgedDelete, '/api/search/settings/credentials', 'DELETE')).status,
    ).toBe(403);
    expect(
      (
        await proxyJson(
          new Request('http://127.0.0.1:5173/api/search/settings'),
          '/api/search/settings',
          'DELETE',
        )
      ).status,
    ).toBe(405);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('returns a safe error when Python sends malformed settings or a secret in an error', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ yandex: { enabled: true, api_key: 'secret' } }), {
            headers: { 'content-type': 'application/json' },
          }),
        )
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ detail: 'secret-key' }), {
            status: 500,
            headers: { 'content-type': 'application/json' },
          }),
        ),
    );
    const request = new Request('http://127.0.0.1:5173/api/search/settings');
    const malformed = await proxyJson(request, '/api/search/settings', 'GET');
    expect(malformed.status).toBe(502);
    expect(await malformed.text()).not.toContain('secret');
    const failed = await proxyJson(request, '/api/search/settings', 'GET');
    expect(failed.status).toBe(500);
    expect(await failed.text()).not.toContain('secret-key');
  });

  it('loads search settings independently from model configuration', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (String(url).endsWith('/api/search/settings'))
          return Promise.resolve(new Response('nope', { status: 500 }));
        if (String(url).endsWith('/api/providers/settings'))
          return Promise.resolve(
            new Response('[]', { headers: { 'content-type': 'application/json' } }),
          );
        return Promise.resolve(
          new Response(
            JSON.stringify([
              {
                id: 'p1',
                name: 'Demo',
                kind: 'openai',
                endpoint: 'https://api.example.com/chat/completions',
                model: 'm',
                configured: true,
              },
            ]),
            { headers: { 'content-type': 'application/json' } },
          ),
        );
      }),
    );
    const data = await loadPageData();
    expect(data.providers.map((provider) => provider.id)).toEqual(['p1']);
    expect(data.loadError).toBe('');
    expect(data.searchSettings).toBeNull();
    expect(data.searchSettingsError).toBe('Настройки поисковых систем недоступны');
  });

  it('loads and projects valid search settings even when model configuration fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (String(url).endsWith('/api/search/settings'))
          return Promise.resolve(
            new Response(
              JSON.stringify({
                yandex: { ...publicSearchState.yandex, api_key: 'secret' },
              }),
              { headers: { 'content-type': 'application/json' } },
            ),
          );
        return Promise.resolve(new Response('nope', { status: 500 }));
      }),
    );
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
      id: 'group-1',
      name: 'Demo',
      endpoint: 'https://api.example.com/chat/completions',
      kind: 'openai',
      configured: true,
      api_key: 'secret',
      models: [{ id: 'model-1', model: 'api-model', name: 'Demo model', api_key: 'secret' }],
    });
    expect(projected).not.toHaveProperty('api_key');
    expect(projected.models).toEqual([{ id: 'model-1', model: 'api-model', name: 'Demo model' }]);
  });

  it('allows only stable provider IDs in settings item paths', () => {
    expect(settingsProviderPath('group-1')).toBe('/api/providers/settings/group-1');
    expect(() => settingsProviderPath('../check')).toThrow();
  });

  it('rejects malformed settings data instead of exposing invented values', () => {
    expect(() =>
      publicSettingsProvider({
        id: 'group-1',
        name: 'Demo',
        endpoint: 'https://api.example.com/chat/completions',
        kind: 'openai',
        configured: true,
        models: [{ model: 'api-model', name: 'Demo model' }],
      }),
    ).toThrow();
  });

  it('returns the configuration document and drops anything else', () => {
    expect(
      publicConfig({
        directory: '/tmp/ai-tracker',
        exists: true,
        content: '{\n  "providers": null\n}',
        api_key: 'secret',
      }),
    ).toEqual({
      directory: '/tmp/ai-tracker',
      exists: true,
      content: '{\n  "providers": null\n}',
    });
    expect(publicConfig({ directory: '/tmp/ai-tracker', exists: false, content: null })).toEqual({
      directory: '/tmp/ai-tracker',
      exists: false,
      content: null,
    });
    expect(() =>
      publicConfig({ directory: '/tmp/ai-tracker', exists: true, content: null }),
    ).toThrow();
    expect(() =>
      publicConfig({ directory: '/tmp/ai-tracker', exists: true, content: '' }),
    ).toThrow();
  });

  it('projects the configuration document from Python without provider fields', async () => {
    const document =
      '{\n  "providers": {\n    "groups": []\n  },\n  "search": null,\n  "seo": null\n}';
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            directory: '/tmp/ai-tracker',
            exists: true,
            content: document,
            api_key: 'secret',
          }),
          { headers: { 'content-type': 'application/json' } },
        ),
      ),
    );
    const response = await proxyJson(
      new Request('http://127.0.0.1:5173/api/config'),
      '/api/config',
      'GET',
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      directory: '/tmp/ai-tracker',
      exists: true,
      content: document,
    });
  });

  it('returns only the application version from Python', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ version: '0.1.0', extra: 'ignored' }), {
          headers: { 'content-type': 'application/json' },
        }),
      ),
    );
    const response = await proxyJson(
      new Request('http://127.0.0.1:5173/api/version'),
      '/api/version',
      'GET',
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ version: '0.1.0' });
  });

  it('projects settings list responses from Python', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify([
            {
              id: 'group-1',
              name: 'Demo',
              kind: 'openai',
              endpoint: 'https://api.example.com/chat/completions',
              configured: true,
              api_key: 'secret',
              models: [{ id: 'model-1', model: 'api-a', name: 'A' }],
            },
          ]),
          { headers: { 'content-type': 'application/json' } },
        ),
      ),
    );
    const response = await proxyJson(
      new Request('http://127.0.0.1:5173/api/providers/settings'),
      '/api/providers/settings',
      'GET',
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual([
      {
        id: 'group-1',
        name: 'Demo',
        kind: 'openai',
        endpoint: 'https://api.example.com/chat/completions',
        configured: true,
        models: [{ id: 'model-1', model: 'api-a', name: 'A' }],
      },
    ]);
  });

  it('blocks cross-origin settings writes before reaching Python', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const request = new Request('http://127.0.0.1:5173/api/providers/settings', {
      method: 'POST',
      headers: { origin: 'https://other.example', 'content-type': 'application/json' },
      body: '{}',
    });
    const response = await proxyJson(request, '/api/providers/settings', 'POST');
    expect(response.status).toBe(403);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('rejects oversized writes and non-JSON upstream responses', async () => {
    const largeRequest = new Request('http://127.0.0.1:5173/api/providers/settings', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ data: 'x'.repeat(65_536) }),
    });
    expect((await proxyJson(largeRequest, '/api/providers/settings', 'POST')).status).toBe(413);
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response('<html>broken</html>', { headers: { 'content-type': 'text/html' } }),
        ),
    );
    const response = await proxyJson(
      new Request('http://127.0.0.1:5173/api/providers/settings'),
      '/api/providers/settings',
      'GET',
    );
    expect(response.status).toBe(502);
  });
});

describe('SEO BFF', () => {
  const publicSeoState = {
    endpoint: 'https://llm.example.com/v1/chat/completions',
    model: 'seo-model',
    has_api_key: true,
    endpoint_source: 'ui',
    model_source: 'env',
    api_key_source: 'env',
  } as const;

  it('projects the SEO settings and drops any unexpected key, including a returned secret', () => {
    expect(publicSeoSettings({ ...publicSeoState, api_key: 'secret', extra: 'private' })).toEqual(
      publicSeoState,
    );
    expect(publicSeoSettings(publicSeoState)).toEqual(publicSeoState);
    expect(publicSeoSettings({ ...publicSeoState, endpoint: null, model: null })).toEqual({
      ...publicSeoState,
      endpoint: null,
      model: null,
    });
  });

  it('rejects malformed SEO settings instead of inventing defaults', () => {
    for (const value of [
      {},
      { ...publicSeoState, has_api_key: 'yes' },
      { ...publicSeoState, endpoint_source: 'other' },
      { ...publicSeoState, model_source: null },
      { ...publicSeoState, endpoint: 7 },
      'nope',
    ])
      expect(() => publicSeoSettings(value)).toThrow();
  });

  it('projects the connection probe result without leaking an upstream secret', () => {
    expect(publicSeoSettingsTest({ ok: true, model: 'seo-model', tools: true })).toEqual({
      ok: true,
      model: 'seo-model',
      error: null,
    });
    expect(publicSeoSettingsTest({ ok: true, model: 'seo-model' })).toEqual({
      ok: true,
      model: 'seo-model',
      error: null,
    });
    expect(
      publicSeoSettingsTest({ ok: false, error: 'Модель недоступна', api_key: 'secret' }),
    ).toEqual({ ok: false, model: null, error: 'Модель недоступна' });
    expect(() => publicSeoSettingsTest({ ok: 'yes' })).toThrow();
  });

  it('rejects unknown or forged SEO settings paths before reaching Python', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    for (const path of [
      '/api/seo/settings/other',
      '/api/seo/analyses/',
      '/api/seo/chats',
      '/api/seo/chats/chat-1/messages',
    ] as const) {
      expect(
        (
          await proxyJson(
            new Request('http://127.0.0.1:5173/api/seo/settings'),
            path as ApiPath,
            'GET',
          )
        ).status,
      ).toBe(400);
    }
    // A wrong method on a settings path is rejected by the shared method check.
    expect(
      (
        await proxyJson(
          new Request('http://127.0.0.1:5173/api/seo/settings'),
          '/api/seo/settings',
          'DELETE',
        )
      ).status,
    ).toBe(405);
    expect(
      (
        await proxyJson(
          new Request('http://127.0.0.1:5173/api/seo/settings/test'),
          '/api/seo/settings/test',
          'GET',
        )
      ).status,
    ).toBe(405);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('keeps the SEO connection test out of the shared short timeout', () => {
    expect(apiTimeoutMs('/api/seo/settings/test')).toBe(SEO_SETTINGS_TEST_TIMEOUT_MS);
    expect(SEO_SETTINGS_TEST_TIMEOUT_MS).toBeGreaterThan(DEFAULT_TIMEOUT_MS);
    expect(apiTimeoutMs('/api/providers')).toBe(DEFAULT_TIMEOUT_MS);
    expect(apiTimeoutMs('/api/search/settings')).toBe(DEFAULT_TIMEOUT_MS);
  });

  it('proxies settings GET, PUT and credentials DELETE with an exact safe response', async () => {
    const fetchSpy = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            ...publicSeoState,
            api_key: 'secret',
          }),
          { headers: { 'content-type': 'application/json' } },
        ),
      ),
    );
    vi.stubGlobal('fetch', fetchSpy);
    const get = await proxyJson(
      new Request('http://127.0.0.1:5173/api/seo/settings'),
      '/api/seo/settings',
      'GET',
    );
    expect(get.status).toBe(200);
    expect(await get.json()).toEqual(publicSeoState);
    const put = await proxyJson(
      new Request('http://127.0.0.1:5173/api/seo/settings', {
        method: 'PUT',
        headers: { origin: 'http://127.0.0.1:5173', 'content-type': 'application/json' },
        body: JSON.stringify({ endpoint: publicSeoState.endpoint, model: publicSeoState.model }),
      }),
      '/api/seo/settings',
      'PUT',
    );
    expect(await put.json()).toEqual(publicSeoState);
    expect(fetchSpy).toHaveBeenLastCalledWith(
      'http://127.0.0.1:8000/api/seo/settings',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ endpoint: publicSeoState.endpoint, model: publicSeoState.model }),
      }),
    );
    const reset = await proxyJson(
      new Request('http://127.0.0.1:5173/api/seo/settings/credentials', { method: 'DELETE' }),
      '/api/seo/settings/credentials',
      'DELETE',
    );
    expect(reset.status).toBe(200);
    expect(await reset.json()).toEqual(publicSeoState);
  });

  it('proxies the bodyless connection probe and reports a safe failure', async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true, model: 'seo-model' }), {
          headers: { 'content-type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: false, error: 'Модель недоступна' }), {
          headers: { 'content-type': 'application/json' },
        }),
      );
    vi.stubGlobal('fetch', fetchSpy);
    const request = new Request('http://127.0.0.1:5173/api/seo/settings/test', { method: 'POST' });
    const ok = await proxyJson(request, '/api/seo/settings/test', 'POST');
    expect(ok.status).toBe(200);
    expect(await ok.json()).toEqual({ ok: true, model: 'seo-model', error: null });
    expect(fetchSpy).toHaveBeenLastCalledWith(
      'http://127.0.0.1:8000/api/seo/settings/test',
      expect.objectContaining({ method: 'POST', body: undefined }),
    );
    const failed = await proxyJson(request, '/api/seo/settings/test', 'POST');
    expect(await failed.json()).toEqual({
      ok: false,
      model: null,
      error: 'Модель недоступна',
    });
  });

  it('turns SEO settings failures into a fixed safe error without the upstream text', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'secret-key' }), {
          status: 500,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    );
    const response = await proxyJson(
      new Request('http://127.0.0.1:5173/api/seo/settings'),
      '/api/seo/settings',
      'GET',
    );
    expect(response.status).toBe(500);
    expect(await response.json()).toEqual({ detail: 'Ошибка настроек служебной LLM' });
  });

  it('blocks cross-origin SEO writes before reaching Python', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const forged = new Request('http://127.0.0.1:5173/api/seo/settings', {
      method: 'PUT',
      headers: { origin: 'https://other.example', 'content-type': 'application/json' },
      body: '{}',
    });
    expect((await proxyJson(forged, '/api/seo/settings', 'PUT')).status).toBe(403);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('loads SEO settings independently from the model configuration', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (String(url).endsWith('/api/seo/settings'))
          return Promise.resolve(
            new Response(
              JSON.stringify({
                ...publicSeoState,
                api_key: 'secret',
              }),
              { headers: { 'content-type': 'application/json' } },
            ),
          );
        if (String(url).endsWith('/api/search/settings'))
          return Promise.resolve(new Response('nope', { status: 500 }));
        return Promise.resolve(new Response('nope', { status: 500 }));
      }),
    );
    const data = await loadPageData();
    expect(data.seoSettings).toEqual(publicSeoState);
    expect(data.seoSettings).not.toHaveProperty('api_key');
    expect(data.seoSettingsError).toBe('');
    expect(data.loadError).not.toBe('');
    expect(data.searchSettingsError).not.toBe('');
  });

  it('keeps the model configuration when the SEO settings resource fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (String(url).endsWith('/api/seo/settings'))
          return Promise.resolve(new Response('nope', { status: 500 }));
        if (String(url).endsWith('/api/search/settings'))
          return Promise.resolve(
            new Response(
              JSON.stringify({
                yandex: publicSearchState.yandex,
              }),
              { headers: { 'content-type': 'application/json' } },
            ),
          );
        if (String(url).endsWith('/api/providers/settings'))
          return Promise.resolve(
            new Response('[]', { headers: { 'content-type': 'application/json' } }),
          );
        return Promise.resolve(
          new Response(
            JSON.stringify([
              {
                id: 'p1',
                name: 'Demo',
                kind: 'openai',
                endpoint: 'https://api.example.com/chat/completions',
                model: 'm',
                configured: true,
              },
            ]),
            { headers: { 'content-type': 'application/json' } },
          ),
        );
      }),
    );
    const data = await loadPageData();
    expect(data.seoSettings).toBeNull();
    expect(data.seoSettingsError).toBe('Настройки служебной LLM недоступны');
    expect(data.loadError).toBe('');
    expect(data.providers.map((provider) => provider.id)).toEqual(['p1']);
    expect(data.searchSettings).toEqual(publicSearchState.yandex);
  });
});

describe('the layout data the pages consume', () => {
  const jsonResponse = (value: unknown) =>
    new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } });

  it('keeps the fields the pages and the settings dialog consume', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (String(url).endsWith('/api/providers')) return Promise.resolve(jsonResponse([]));
        if (String(url).endsWith('/api/providers/settings'))
          return Promise.resolve(jsonResponse([]));
        if (String(url).endsWith('/api/search/settings'))
          return Promise.resolve(jsonResponse(publicSearchState));
        if (String(url).endsWith('/api/seo/settings'))
          return Promise.resolve(
            jsonResponse({
              endpoint: 'https://api.example.com/chat/completions',
              model: 'm',
              has_api_key: true,
              endpoint_source: 'ui',
              model_source: 'ui',
              api_key_source: 'ui',
            }),
          );
        if (String(url).endsWith('/api/version'))
          return Promise.resolve(jsonResponse({ version: '0.1.0' }));
        return Promise.resolve(new Response('nope', { status: 500 }));
      }),
    );
    const data = await loadPageData();
    expect(Object.keys(data).sort()).toEqual([
      'loadError',
      'providers',
      'searchSettings',
      'searchSettingsError',
      'seoSettings',
      'seoSettingsError',
      'settingsProviders',
      'version',
    ]);
    expect(data.version).toBe('0.1.0');
    expect(data.providers).toEqual([]);
    expect(data.loadError).toBe('');
  });
});

describe('retired compatibility surface', () => {
  it('no longer exports the projections of removed resources', async () => {
    const api = (await import('./python-api')) as Record<string, unknown>;
    for (const name of [
      'publicRunCreated',
      'publicRunSnapshot',
      'publicRunList',
      'publicCheck',
      'publicSearchCreated',
      'publicSearchSnapshot',
      'publicSearchRegions',
      'publicForm',
      'runPath',
      'runListPath',
      'runExportPath',
      'searchPath',
      'proxyCsv',
    ])
      expect(api[name]).toBeUndefined();
  });

  it('rejects the retired paths before any upstream call', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    for (const path of ['/api/runs', '/api/check', '/api/form', '/api/search/regions'] as never[]) {
      const response = await proxyJson(new Request('http://127.0.0.1:5173/'), path, 'GET');
      expect(response.status).toBe(400);
    }
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
