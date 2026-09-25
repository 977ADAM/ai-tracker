import type { RequestHandler } from './$types';
import { proxyCsv, runExportPath } from '$lib/server/python-api';

export const GET: RequestHandler = ({ request, params }) => {
  try { return proxyCsv(request, runExportPath(params.id)); }
  catch { return new Response(JSON.stringify({ detail: 'Некорректный прогон' }), { status: 400, headers: { 'content-type': 'application/json' } }); }
};
