import type { LayoutServerLoad } from './$types';
import { loadPageData } from '$lib/server/python-api';

export const load = (async () => {
  return await loadPageData();
}) satisfies LayoutServerLoad;