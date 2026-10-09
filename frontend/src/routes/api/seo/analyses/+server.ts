import type { RequestHandler } from './$types';
import { proxyJson, seoAnalysisListPath } from '$lib/server/python-api';

const invalid = () =>
  new Response(JSON.stringify({ detail: 'Некорректная страница истории' }), {
    status: 400,
    headers: { 'content-type': 'application/json' },
  });

export const POST: RequestHandler = ({ request }) =>
  proxyJson(request, '/api/seo/analyses', 'POST');

export const GET: RequestHandler = ({ request }) => {
  const url = new URL(request.url);
  if (
    [...url.searchParams.keys()].some((key) => key !== 'cursor') ||
    url.searchParams.getAll('cursor').length > 1
  )
    return invalid();
  try {
    return proxyJson(request, seoAnalysisListPath(url.searchParams.get('cursor')), 'GET');
  } catch {
    return invalid();
  }
};
