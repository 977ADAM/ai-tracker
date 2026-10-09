import type { RequestHandler } from './$types';
import { proxyJson } from '$lib/server/python-api';

// The probe waits for a real LLM completion, so `pythonApi` gives this exact
// path its own longer timeout instead of the shared request budget.
export const POST: RequestHandler = ({ request }) =>
  proxyJson(request, '/api/seo/settings/test', 'POST');
