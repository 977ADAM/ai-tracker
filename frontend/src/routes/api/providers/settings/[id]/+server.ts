import type { RequestHandler } from './$types';
import { settingsProviderPath, proxyJson } from '$lib/server/python-api';

export const PUT: RequestHandler = ({ request, params }) => {
  try { return proxyJson(request, settingsProviderPath(params.id), 'PUT'); }
  catch { return new Response(JSON.stringify({ detail: 'Некорректное подключение' }), { status: 400, headers: { 'content-type': 'application/json' } }); }
};

export const DELETE: RequestHandler = ({ request, params }) => {
  try { return proxyJson(request, settingsProviderPath(params.id), 'DELETE'); }
  catch { return new Response(JSON.stringify({ detail: 'Некорректное подключение' }), { status: 400, headers: { 'content-type': 'application/json' } }); }
};
