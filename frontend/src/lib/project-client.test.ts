import { afterEach, expect, it, vi } from 'vitest';
import { projectRequest } from './project-client';

vi.mock('$app/paths', () => ({ base: '/clustering/tracker' }));
afterEach(() => vi.unstubAllGlobals());

it('requests the project API beneath the deployed base path', async () => {
  vi.stubGlobal('fetch', async (path: string) => {
    return path === '/clustering/tracker/api/projects/p1?cursor=next'
      ? new Response(JSON.stringify({ id: 'p1' }))
      : new Response(JSON.stringify({ detail: 'Route not found' }), { status: 404 });
  });
  expect(await projectRequest('/api/projects/p1?cursor=next')).toEqual({ id: 'p1' });
});
