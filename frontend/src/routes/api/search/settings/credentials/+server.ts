import type { RequestHandler } from './$types';
import { proxyJson } from '$lib/server/python-api';

export const DELETE: RequestHandler = ({ request }) =>
  proxyJson(request, '/api/search/settings/credentials', 'DELETE');
