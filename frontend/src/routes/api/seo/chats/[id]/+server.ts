import type { RequestHandler } from './$types';
import { proxyJson, seoChatDetailPath, seoChatPath } from '$lib/server/python-api';

const invalid = () => new Response(JSON.stringify({ detail: 'Некорректный чат' }), {
  status: 400, headers: { 'content-type': 'application/json' }
});

export const GET: RequestHandler = ({ request, params }) => {
  const url = new URL(request.url);
  const before = url.searchParams.get('before');
  if ([...url.searchParams.keys()].some((key) => key !== 'before') ||
      url.searchParams.getAll('before').length > 1 ||
      (before !== null && !/^[1-9]\d{0,15}$/.test(before)))
    return invalid();
  try {
    return proxyJson(request, seoChatDetailPath(params.id, before === null ? null : Number(before)), 'GET');
  } catch {
    return invalid();
  }
};

export const DELETE: RequestHandler = ({ request, params }) => {
  if (new URL(request.url).search) return invalid();
  try {
    return proxyJson(request, seoChatPath(params.id), 'DELETE');
  } catch {
    return invalid();
  }
};
