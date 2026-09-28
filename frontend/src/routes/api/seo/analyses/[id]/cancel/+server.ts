import type { RequestHandler } from './$types';
import { proxyJson, seoAnalysisCancelPath } from '$lib/server/python-api';

export const POST: RequestHandler = ({ request, params }) => {
  try {
    return proxyJson(request, seoAnalysisCancelPath(params.id), 'POST');
  } catch {
    return new Response(JSON.stringify({ detail: 'Некорректный SEO-анализ' }), {
      status: 400, headers: { 'content-type': 'application/json' }
    });
  }
};
