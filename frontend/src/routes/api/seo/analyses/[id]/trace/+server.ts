import type { RequestHandler } from './$types';
import { proxyJson, seoAnalysisTracePath } from '$lib/server/python-api';

const invalid = () => new Response(JSON.stringify({ detail: 'Некорректная страница трассы' }), {
  status: 400, headers: { 'content-type': 'application/json' }
});

export const GET: RequestHandler = ({ request, params }) => {
  const url = new URL(request.url);
  if ([...url.searchParams.keys()].some((key) => key !== 'cursor') ||
      url.searchParams.getAll('cursor').length > 1)
    return invalid();
  try {
    return proxyJson(request, seoAnalysisTracePath(params.id, url.searchParams.get('cursor')), 'GET');
  } catch {
    return invalid();
  }
};
