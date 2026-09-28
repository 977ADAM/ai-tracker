import type { RequestHandler } from './$types';
import { proxyJson, seoAnalysisPath } from '$lib/server/python-api';

const invalid = () => new Response(JSON.stringify({ detail: 'Некорректный SEO-анализ' }), {
  status: 400, headers: { 'content-type': 'application/json' }
});

export const GET: RequestHandler = ({ request, params }) => {
  try {
    return proxyJson(request, seoAnalysisPath(params.id), 'GET');
  } catch {
    return invalid();
  }
};

export const DELETE: RequestHandler = ({ request, params }) => {
  try {
    return proxyJson(request, seoAnalysisPath(params.id), 'DELETE');
  } catch {
    return invalid();
  }
};
