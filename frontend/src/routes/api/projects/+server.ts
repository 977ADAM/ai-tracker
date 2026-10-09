import type { RequestHandler } from './$types';
import { proxyProjects } from '$lib/server/projects-api';
export const GET: RequestHandler = ({ request, url }) =>
  proxyProjects(request, '/api/projects' + url.search, 'GET');
export const POST: RequestHandler = ({ request }) =>
  proxyProjects(request, '/api/projects', 'POST');
