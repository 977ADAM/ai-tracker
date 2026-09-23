import type { PageServerLoad } from './$types';
import type { PublicProvider } from '$lib/types';
import { publicProvider, pythonApi } from '$lib/server/python-api';

export const load = (async () => {
  try {
    const response = await pythonApi('/api/providers');
    if (!response.ok || !/^application\/json(?:\s*;|$)/i.test(response.headers.get('content-type') || '')) throw new Error('Invalid provider list');
    const value: unknown = await response.json();
    if (!Array.isArray(value)) throw new Error('Invalid provider list');
    return { providers: value.map((item) => publicProvider(item) as PublicProvider), loadError: '' };
  } catch {
    return { providers: [] as PublicProvider[], loadError: 'Python API недоступен. Проверьте, запущены ли оба сервиса.' };
  }
}) satisfies PageServerLoad;
