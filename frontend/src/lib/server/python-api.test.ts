import { afterEach, describe, expect, it, vi } from 'vitest';
import { proxyJson, publicConfigurationFile, publicSettingsProvider, settingsProviderPath } from './python-api';

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
