import type { RequestHandler } from '$lib/types';
import { proxyJson } from '$lib/server/python-api';

export const GET: RequestHandler = ({ request }) => proxyJson(request, '/api/providers', 'GET');
export const POST: RequestHandler = ({ request }) => proxyJson(request, '/api/providers', 'POST');
