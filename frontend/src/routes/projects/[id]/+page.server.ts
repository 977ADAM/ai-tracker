import type { PageServerLoad } from './$types';
import { error } from '@sveltejs/kit';
import { loadProjectData } from '$lib/server/projects-api';
export const load: PageServerLoad = async ({ params }) => {
  try {
    return await loadProjectData(params.id);
  } catch {
    error(404, 'Проект не найден или API недоступен');
  }
};
