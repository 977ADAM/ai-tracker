import type { RequestHandler } from './$types';
import { proxyJson } from '$lib/server/python-api';

export const GET: RequestHandler = ({ request }) => proxyJson(request, '/api/seo/settings', 'GET');
export const PUT: RequestHandler = ({ request }) => proxyJson(request, '/api/seo/settings', 'PUT');
