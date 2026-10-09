import type { PageServerLoad } from './$types';
import { error } from '@sveltejs/kit';
import { getProjectsResource, projectPath, publicProject } from '$lib/server/projects-api';
export const load: PageServerLoad = async ({ params, parent }) => {
  const data = await parent();
  try {
    const project = await getProjectsResource(projectPath(params.id), publicProject);
    return { project, providers: data.providers };
  } catch {
    error(404, 'Не удалось загрузить проект');
  }
};
