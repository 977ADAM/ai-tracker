import type { RequestHandler } from './$types';
import { proxyJson, runListPath } from '$lib/server/python-api';

export const POST: RequestHandler = ({ request }) => proxyJson(request, '/api/runs', 'POST');

export const GET: RequestHandler = ({ request }) => {
  const url = new URL(request.url);
  if ([...url.searchParams.keys()].some((key) => key !== 'cursor') || url.searchParams.getAll('cursor').length > 1)
    return new Response(JSON.stringify({ detail: 'Некорректная страница истории' }), { status: 400, headers: { 'content-type': 'application/json' } });
  try { return proxyJson(request, runListPath(url.searchParams.get('cursor')), 'GET'); }
  catch { return new Response(JSON.stringify({ detail: 'Некорректная страница истории' }), { status: 400, headers: { 'content-type': 'application/json' } }); }
};
