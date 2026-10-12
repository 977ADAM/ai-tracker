import { describe, expect, it } from 'vitest';
import { publicProject, projectPath } from './projects-api';

describe('project public boundary', () => {
  it('keeps known project fields and strips keys', () => {
    const p = publicProject({
      id: 'p1',
      name: 'Pizza',
      brand: 'Dodo',
      site_url: 'https://example.ru',
      competitors: [],
      queries: [{ text: 'Pizza?', category: null }],
      connection_ids: ['m1'],
      yandex_enabled: false,
      yandex_region: 213,
      revision: 1,
      created_at: 'now',
      updated_at: 'now',
      api_key: 'secret',
    });
    expect(p.name).toBe('Pizza');
    expect(JSON.stringify(p)).not.toContain('secret');
  });
  it('rejects an injected path and malformed project', () => {
    expect(() => projectPath('../config')).toThrow();
    expect(() => publicProject({ id: 'p1', queries: 'wrong' })).toThrow();
  });
});

it('preserves prompt groups in the public answer details', async () => {
  const { proxyProjects } = await import('./projects-api');
  const { vi } = await import('vitest');
  vi.stubGlobal(
    'fetch',
    async () =>
      new Response(
        JSON.stringify({
          kind: 'model',
          cursor: null,
          items: [
            {
              query_index: 0,
              connection_id: 'm1',
              query: 'Pizza?',
              category: null,
              group: 'Delivery',
              provider_name: 'Model',
              status: 'success',
              answer: 'Pizza',
              brand_mentioned: false,
              domain_mentioned: false,
              sentiment_status: 'not_applicable',
              sentiment: null,
              error: null,
              sentiment_error: null,
              answer_mode: 'text',
              citations: [],
            },
          ],
        }),
      ),
  );
  try {
    const response = await proxyProjects(
      new Request('http://localhost/api/measurements/m1/rows?kind=model'),
      '/api/measurements/m1/rows?kind=model',
      'GET',
    );
    expect(response.status).toBe(200);
    expect((await response.json()).items[0].group).toBe('Delivery');
  } finally {
    vi.unstubAllGlobals();
  }
});
