import type { PageServerLoad } from './$types';
import { loadProjectsData } from '$lib/server/projects-api';
export const load: PageServerLoad = ({ url }) => loadProjectsData(url.searchParams.get('cursor'));
