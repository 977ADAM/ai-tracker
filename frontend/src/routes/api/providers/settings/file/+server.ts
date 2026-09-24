import type { RequestHandler } from '@sveltejs/kit';
import { proxyJson } from '$lib/server/python-api';

export const GET: RequestHandler = ({ request }) => proxyJson(request, '/api/providers/settings/file', 'GET');
