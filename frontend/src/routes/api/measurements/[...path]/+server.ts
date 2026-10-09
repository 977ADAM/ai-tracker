import type { RequestHandler } from './$types';
import { proxyProjects } from '$lib/server/projects-api';
const handle: RequestHandler = ({ request, params, url }) =>
  proxyProjects(request, '/api/measurements/' + params.path + url.search, request.method);
export const GET = handle;
export const POST = handle;
export const DELETE = handle;
