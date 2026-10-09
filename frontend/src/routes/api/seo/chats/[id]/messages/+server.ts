import type { RequestHandler } from './$types';
import { proxyJson, seoChatMessagesPath } from '$lib/server/python-api';

const invalid = () =>
  new Response(JSON.stringify({ detail: 'Некорректное сообщение чата' }), {
    status: 400,
    headers: { 'content-type': 'application/json' },
  });

export const POST: RequestHandler = ({ request, params }) => {
  if (new URL(request.url).search) return invalid();
  try {
    return proxyJson(request, seoChatMessagesPath(params.id), 'POST');
  } catch {
    return invalid();
  }
};
