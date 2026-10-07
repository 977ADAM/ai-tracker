import type { RequestHandler } from './$types';
import { proxyJson } from '$lib/server/python-api';

const invalid = () => new Response(JSON.stringify({ detail: 'Некорректный список чатов' }), {
  status: 400, headers: { 'content-type': 'application/json' }
});

const hasQuery = (request: Request) => [...new URL(request.url).searchParams.keys()].length > 0;

export const GET: RequestHandler = ({ request }) => {
  if (hasQuery(request)) return invalid();
  return proxyJson(request, '/api/seo/chats', 'GET');
};

export const POST: RequestHandler = ({ request }) => {
  if (hasQuery(request)) return invalid();
  return proxyJson(request, '/api/seo/chats', 'POST');
};
