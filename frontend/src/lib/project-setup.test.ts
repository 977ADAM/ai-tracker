import { expect, it } from 'vitest';
import { normalizeSiteInput, parseQueryList, parseCompetitorInput } from './project-setup';
it('accepts a domain without a scheme and preserves list groups', () => {
  expect(normalizeSiteInput('dodopizza.ru')).toBe('https://dodopizza.ru');
  expect(
    parseQueryList('Пицца?\nДоставка?', [{ text: 'Пицца?', category: null, group: 'Пицца' }])[0]
      .group,
  ).toBe('Пицца');
  expect(parseCompetitorInput('Pizza Hut')).toEqual({ brand: 'Pizza Hut', site_url: '' });
  expect(() => parseQueryList('Пицца?\nПИЦЦА?')).toThrow();
});
it('keeps imported metadata when the text of a row is edited', () => {
  const row = parseQueryList('Новый текст пиццы?', [
    { text: 'Пицца?', category: 'commercial', group: 'Пицца' },
  ])[0];
  expect(row.group).toBe('Пицца');
  expect(row.category).toBe('commercial');
});
