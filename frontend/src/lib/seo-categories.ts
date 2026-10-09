/**
 * Russian labels of the backend query categories (`QUERY_CATEGORIES` in
 * `backend/app/domain/seo.py`).
 *
 * The backend keys stay the source of truth: only these four are translated,
 * and an unknown key is shown as-is by the caller.
 */
export const SEO_CATEGORY_LABELS: Record<string, string> = {
  commercial: 'Коммерческие',
  informational: 'Информационные',
  comparative: 'Сравнительные',
  recommendation: 'Рекомендовательные',
};
