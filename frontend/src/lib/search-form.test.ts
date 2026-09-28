import { describe, expect, it } from 'vitest';
import { availableSearchEngines, enabledRegionTargets, requestCount, requestCountLabel, validateRun } from './search-form';

const base = { brand: 'Бренд', domain: 'example.ru', promptsText: 'цветы', providerIds: ['p1'], regions: [] as number[] };

describe('validateRun', () => {
  it('accepts a model-only run', () => {
    expect(validateRun(base)).toBeNull();
  });

  it('accepts a search-only run without a brand', () => {
    expect(validateRun({ brand: '', domain: 'example.ru', promptsText: 'цветы', providerIds: [], regions: [1] })).toBeNull();
  });

  it('needs at least one model or one region', () => {
    expect(validateRun({ ...base, providerIds: [], regions: [] })).toMatch(/модель|регион/);
  });

  it('needs a site only when regions are selected', () => {
    expect(validateRun({ ...base, domain: '' })).toBeNull();
    expect(validateRun({ ...base, domain: '', regions: [1] })).toMatch(/сайт/i);
  });

  it('holds Yandex questions to 400 characters and model questions to 500', () => {
    const long = 'x'.repeat(401);
    expect(validateRun({ ...base, promptsText: long })).toBeNull();
    expect(validateRun({ ...base, promptsText: 'x'.repeat(501) })).toMatch(/500/);
    expect(validateRun({ brand: 'Бренд', domain: 'example.ru', promptsText: long, providerIds: [], regions: [1] })).toMatch(/400/);
    expect(validateRun({ ...base, promptsText: 'x'.repeat(400), regions: [1] })).toBeNull();
  });

  it('holds Yandex questions to 40 words', () => {
    expect(validateRun({ ...base, promptsText: Array(40).fill('слово').join(' '), regions: [1] })).toBeNull();
    expect(validateRun({ ...base, promptsText: Array(41).fill('слово').join(' '), regions: [1] })).toMatch(/40/);
  });

  it('rejects repeated, extra, or missing regions', () => {
    expect(validateRun({ ...base, regions: [1, 1] })).toMatch(/один раз/);
    expect(validateRun({ ...base, regions: [1, 213, 2, 54, 65, 43] })).toMatch(/5/);
  });

  it('rejects an empty or oversized question list', () => {
    expect(validateRun({ ...base, promptsText: '   \n  ' })).toMatch(/вопрос/i);
    expect(validateRun({ ...base, promptsText: '\n'.repeat(21) + 'x'.repeat(1) })).toBeNull();
    expect(validateRun({ ...base, promptsText: Array.from({ length: 21 }, () => 'вопрос').join('\n') })).toMatch(/20/);
  });
});

describe('request count', () => {
  it('is questions times regions', () => {
    expect(requestCount('первый\nвторой', [1, 213])).toBe(4);
    expect(requestCount('первый\n\n  второй  \n', [])).toBe(0);
    expect(requestCount(Array.from({ length: 20 }, (_, index) => `вопрос ${index}`).join('\n'), [1, 213, 2, 54, 65])).toBe(100);
  });

  it('is spelled out for the page', () => {
    expect(requestCountLabel(1)).toBe('1 запрос к Яндексу');
    expect(requestCountLabel(2)).toBe('2 запроса к Яндексу');
    expect(requestCountLabel(5)).toBe('5 запросов к Яндексу');
    expect(requestCountLabel(100)).toBe('100 запросов к Яндексу');
  });
});

describe('search availability', () => {
  const settings = { enabled: true, folder_id: null, has_api_key: false, api_key_source: 'none' as const, folder_id_source: 'none' as const };

  it('offers Yandex when settings use the enabled default', () => {
    expect(availableSearchEngines(settings)).toEqual(['yandex']);
    expect(enabledRegionTargets([1, '', 213], ['yandex', 'yandex', 'yandex'], ['yandex']))
      .toEqual([{ region: 1, engine: 'yandex' }, { region: 213, engine: 'yandex' }]);
  });

  it('omits stale Yandex regions when disabled and keeps a model-only run valid', () => {
    const engines = availableSearchEngines({ ...settings, enabled: false });
    const targets = enabledRegionTargets([1, 213], ['yandex', 'yandex'], engines);
    expect(engines).toEqual([]);
    expect(targets).toEqual([]);
    expect(requestCount('первый\nвторой', targets.map((target) => target.region))).toBe(0);
    expect(validateRun({ ...base, regions: targets.map((target) => target.region) })).toBeNull();
  });
});
