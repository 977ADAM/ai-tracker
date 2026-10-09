import { describe, expect, it } from 'vitest';
import { SEO_CATEGORY_LABELS } from './seo-categories';

describe('SEO category labels', () => {
  it('maps every backend query category to its Russian label', () => {
    expect(SEO_CATEGORY_LABELS).toEqual({
      commercial: 'Коммерческие',
      informational: 'Информационные',
      comparative: 'Сравнительные',
      recommendation: 'Рекомендовательные',
    });
  });
});
