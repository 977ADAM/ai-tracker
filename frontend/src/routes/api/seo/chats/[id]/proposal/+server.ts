import type { RequestHandler } from './$types';
import { proxyJson, seoChatProposalPath } from '$lib/server/python-api';

const invalid = () =>
  new Response(JSON.stringify({ detail: 'Некорректное предложение чата' }), {
    status: 400,
    headers: { 'content-type': 'application/json' },
  });

export const PUT: RequestHandler = ({ request, params }) => {
  if (new URL(request.url).search) return invalid();
  try {
    return proxyJson(request, seoChatProposalPath(params.id), 'PUT');
  } catch {
    return invalid();
  }
};
