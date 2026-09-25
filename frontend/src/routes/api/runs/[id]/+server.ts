import type { RequestHandler } from './$types';
import { proxyJson, runPath } from '$lib/server/python-api';

const invalid = () => new Response(JSON.stringify({ detail: 'Некорректный прогон' }), { status: 400, headers: { 'content-type': 'application/json' } });

export const GET: RequestHandler = ({ request, params }) => {
  try { return proxyJson(request, runPath(params.id), 'GET'); }
  catch { return invalid(); }
};

export const DELETE: RequestHandler = ({ request, params }) => {
  try { return proxyJson(request, runPath(params.id), 'DELETE'); }
  catch { return invalid(); }
};
