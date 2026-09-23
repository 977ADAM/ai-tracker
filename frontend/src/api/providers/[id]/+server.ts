import type { RequestHandler } from '$lib/types';
import { providerPath, proxyJson } from '$lib/server/python-api';

export const PUT: RequestHandler = ({ request, params }) => {
  try { return proxyJson(request, providerPath(params.id), 'PUT'); }
  catch { return new Response(JSON.stringify({ detail: 'Некорректное подключение' }), { status: 400, headers: { 'content-type': 'application/json' } }); }
};

export const DELETE: RequestHandler = ({ request, params }) => {
  try { return proxyJson(request, providerPath(params.id), 'DELETE'); }
  catch { return new Response(JSON.stringify({ detail: 'Некорректное подключение' }), { status: 400, headers: { 'content-type': 'application/json' } }); }
};
