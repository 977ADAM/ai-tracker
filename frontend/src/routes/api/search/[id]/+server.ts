import type { RequestHandler } from './$types';
import { proxyJson, searchPath } from '$lib/server/python-api';

export const GET: RequestHandler = ({ request, params }) => {
  try {
    return proxyJson(request, searchPath(params.id), 'GET');
  } catch {
    return new Response(JSON.stringify({ detail: 'Некорректная задача поиска' }), {
      status: 400,
      headers: { 'content-type': 'application/json' },
    });
  }
};
