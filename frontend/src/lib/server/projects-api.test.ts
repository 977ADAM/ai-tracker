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
