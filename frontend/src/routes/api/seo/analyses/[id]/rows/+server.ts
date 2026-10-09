import type { RequestHandler } from './$types';
import { proxyJson, seoAnalysisRowsPath } from '$lib/server/python-api';
import type { SeoRowsKind } from '$lib/types';

const invalid = () =>
  new Response(JSON.stringify({ detail: 'Некорректная страница результатов' }), {
    status: 400,
    headers: { 'content-type': 'application/json' },
  });

export const GET: RequestHandler = ({ request, params }) => {
  const url = new URL(request.url);
  const kind = url.searchParams.get('kind');
  if (
    [...url.searchParams.keys()].some((key) => key !== 'kind' && key !== 'cursor') ||
    url.searchParams.getAll('kind').length !== 1 ||
    url.searchParams.getAll('cursor').length > 1 ||
    (kind !== 'model' && kind !== 'search')
  )
    return invalid();
  try {
    return proxyJson(
      request,
      seoAnalysisRowsPath(params.id, kind as SeoRowsKind, url.searchParams.get('cursor')),
      'GET',
    );
  } catch {
    return invalid();
  }
};
