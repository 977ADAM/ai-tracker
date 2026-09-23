import type { RequestHandler } from '$lib/types';
import { proxyJson } from '$lib/server/python-api';

export const POST: RequestHandler = ({ request }) => proxyJson(request, '/api/check', 'POST');
