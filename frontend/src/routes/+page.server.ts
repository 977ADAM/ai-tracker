import type { PageServerLoad } from './$types';
import { loadPageData } from '$lib/server/python-api';

export const load = (() => loadPageData()) satisfies PageServerLoad;
