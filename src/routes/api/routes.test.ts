import { afterEach, expect, it, vi } from 'vitest';
import { GET, POST } from './providers/+server';
import { PUT, DELETE } from './providers/[id]/+server';
import { POST as CHECK } from './check/+server';

afterEach(() => vi.restoreAllMocks());

it('routes browser requests to fixed Python paths', async () => {
  const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([]), { headers: { 'content-type': 'application/json' } }));
  await GET({ request: new Request('http://127.0.0.1:5173/api/providers') } as never);
  await POST({ request: new Request('http://127.0.0.1:5173/api/providers', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{"name":"x"}' }) } as never);
  await PUT({ params: { id: 'deepseek' }, request: new Request('http://127.0.0.1:5173/api/providers/deepseek', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: '{"api_key":"x"}' }) } as never);
  await DELETE({ params: { id: 'deepseek' }, request: new Request('http://127.0.0.1:5173/api/providers/deepseek', { method: 'DELETE' }) } as never);
  await CHECK({ request: new Request('http://127.0.0.1:5173/api/check', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{"brand":"Ромашка"}' }) } as never);
  expect(spy.mock.calls.map(([url]) => url)).toEqual([
    'http://127.0.0.1:8000/api/providers',
    'http://127.0.0.1:8000/api/providers',
    'http://127.0.0.1:8000/api/providers/deepseek',
    'http://127.0.0.1:8000/api/providers/deepseek',
    'http://127.0.0.1:8000/api/check'
  ]);
});
