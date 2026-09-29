import { describe, expect, it } from 'vitest';
import {
  actualConnectionCount, actualQueryCount, estimateActual, estimateUpper, GENERATED_QUERY_LIMIT,
  parseSeeds, parseServices, queriesGenerated, SEO_STAGE_LABELS, SEARCH_UPPER, snapshotActualEstimate,
  validateSeoForm
} from './seo-form';
import type { SeoAnalysisSnapshot } from './types';

const valid = {
  url: 'https://example.ru',
  sphere: 'Цветы и подарки',
  seeds: ['купить цветы', 'доставка букетов', 'цветочный магазин'],
  services: ['Доставка цветов'],
  connectionIds: ['model-1']
};

function snapshot(overrides: Partial<SeoAnalysisSnapshot> = {}): SeoAnalysisSnapshot {
  return {
    id: 'seo-1', status: 'running', created_at: '2026-09-28T00:00:00Z', updated_at: '2026-09-28T00:00:00Z',
    finished_at: null,
    input: { url: 'https://example.ru', host: 'example.ru', sphere: 'Цветы', seeds: ['а'], services: ['б'], connection_ids: ['model-1', 'model-2'] },
    estimate: { search_upper: 43, model_upper: 40, generated_limit: 40, connections: 2 },
    company_name: '', services: [], pages: [], stages: [], candidates: [], queries: [], summary: null,
    counters: { queries: 0, search_rows: 0, model_rows: 0, search_errors: 0, model_errors: 0 },
    readiness: {
      report_ready: false, summary_ready: false, queries_ready: false, has_submitted_search_rows: false,
      has_unsubmitted_search_rows: false, has_unfinished_model_rows: false, search_rows: 0, model_rows: 0
    },
    aggregates: { site: { search: {}, ai: {} }, competitors: [], categories: {}, services: {}, counts: {} },
    ...overrides
  } as unknown as SeoAnalysisSnapshot;
}

describe('parseServices', () => {
  it('reads one service per line and ignores blank lines', () => {
    expect(parseServices('Доставка цветов\n  Букеты  \n\n\nОформление')).toEqual(['Доставка цветов', 'Букеты', 'Оформление']);
  });

  it('returns nothing for an empty textarea', () => {
    expect(parseServices('')).toEqual([]);
    expect(parseServices('   \n \n')).toEqual([]);
  });
});

describe('parseSeeds', () => {
  it('trims the three fields and drops the empty ones', () => {
    expect(parseSeeds([' купить цветы ', '', '  ', 'доставка букетов'])).toEqual(['купить цветы', 'доставка букетов']);
  });
});

describe('validateSeoForm', () => {
  it('accepts the documented five fields', () => {
    expect(validateSeoForm(valid)).toBeNull();
  });

  it('requires a full public HTTP(S) URL', () => {
    expect(validateSeoForm({ ...valid, url: '' })).toMatch(/адрес главной страницы/i);
    expect(validateSeoForm({ ...valid, url: 'example.ru' })).toMatch(/https:\/\/example\.ru/);
    expect(validateSeoForm({ ...valid, url: 'ftp://example.ru' })).toMatch(/https:\/\/example\.ru/);
    expect(validateSeoForm({ ...valid, url: 'http://example.ru/catalog' })).toBeNull();
    expect(validateSeoForm({ ...valid, url: 'https://user:pass@example.ru' })).toMatch(/https:\/\/example\.ru/);
  });

  it('rejects IP addresses like the backend crawler does', () => {
    expect(validateSeoForm({ ...valid, url: 'http://127.0.0.1:8000' })).toMatch(/доменом, а не IP/);
    expect(validateSeoForm({ ...valid, url: 'http://[::1]/' })).toMatch(/доменом, а не IP/);
  });

  it('requires a sphere', () => {
    expect(validateSeoForm({ ...valid, sphere: '   ' })).toMatch(/сферу бизнеса/);
    expect(validateSeoForm({ ...valid, sphere: 'x'.repeat(201) })).toMatch(/200/);
  });

  it('requires exactly three distinct non-empty key queries', () => {
    expect(validateSeoForm({ ...valid, seeds: ['один', 'два', ''] })).toMatch(/ровно 3/);
    expect(validateSeoForm({ ...valid, seeds: ['один', 'два', 'три', 'четыре'] })).toMatch(/ровно 3/);
    expect(validateSeoForm({ ...valid, seeds: ['один', 'один ', 'два'] })).toMatch(/не должны повторяться/);
    expect(validateSeoForm({ ...valid, seeds: ['x'.repeat(401), 'два', 'три'] })).toMatch(/400/);
  });

  it('requires at least one service', () => {
    expect(validateSeoForm({ ...valid, services: [] })).toMatch(/хотя бы одну услугу/);
    expect(validateSeoForm({ ...valid, services: ['  '] })).toMatch(/хотя бы одну услугу/);
    expect(validateSeoForm({ ...valid, services: Array.from({ length: 21 }, (_, index) => `услуга ${index}`) })).toMatch(/20 услуг/);
  });

  it('holds the connections to one through five distinct choices', () => {
    expect(validateSeoForm({ ...valid, connectionIds: [] })).toMatch(/от 1 до 5/);
    expect(validateSeoForm({ ...valid, connectionIds: ['a', 'b', 'c', 'd', 'e', 'f'] })).toMatch(/от 1 до 5/);
    expect(validateSeoForm({ ...valid, connectionIds: ['a', 'a', 'b'] })).toBeNull();
  });
});

describe('call estimates', () => {
  it('bounds the run before generation with M connections', () => {
    expect(estimateUpper(1)).toEqual({ searchUpper: 43, modelUpper: 40, generatedLimit: 40, connections: 1 });
    expect(estimateUpper(3)).toEqual({ searchUpper: 43, modelUpper: 120, generatedLimit: 40, connections: 3 });
    expect(estimateUpper(5)).toEqual({ searchUpper: 43, modelUpper: 200, generatedLimit: 40, connections: 5 });
    expect(SEARCH_UPPER).toBe(43);
    expect(GENERATED_QUERY_LIMIT).toBe(40);
  });

  it('counts the actual K and K x M after generation', () => {
    expect(estimateActual(0, 3)).toEqual({ searchActual: 3, modelActual: 0 });
    expect(estimateActual(12, 3)).toEqual({ searchActual: 15, modelActual: 36 });
    expect(estimateActual(20, 1)).toEqual({ searchActual: 23, modelActual: 20 });
    expect(estimateActual(40, 5)).toEqual({ searchActual: 43, modelActual: 200 });
  });
});

describe('stage labels', () => {
  it('names the six stages in order', () => {
    expect(SEO_STAGE_LABELS).toEqual([
      'Анализ сайта', 'Поиск конкурентов', 'Генерация запросов',
      'Проверки в ИИ и Поиске', 'Анализ результатов', 'Отчёт'
    ]);
    expect(SEO_STAGE_LABELS).toHaveLength(6);
  });
});

describe('snapshot helpers', () => {
  it('reads K from the saved queries and M from the selected connections', () => {
    const withQueries = snapshot({
      queries: [{
        index: 1, text: 'а', category: 'commercial', service: null,
        flags: { mentions_company_name: false, mentions_company_host: false, mentions_candidate_host: false, branded: false }
      }],
      counters: { queries: 7, search_rows: 0, model_rows: 0, search_errors: 0, model_errors: 0 }
    });
    expect(actualQueryCount(withQueries)).toBe(1);
    expect(actualQueryCount(snapshot())).toBe(0);
    expect(actualConnectionCount(snapshot())).toBe(2);
  });

  it('falls back to the counter while the query list is still empty', () => {
    const counted = snapshot({ counters: { queries: 9, search_rows: 9, model_rows: 18, search_errors: 0, model_errors: 0 } });
    expect(actualQueryCount(counted)).toBe(9);
    expect(queriesGenerated(counted)).toBe(true);
    expect(snapshotActualEstimate(counted)).toEqual({ searchActual: 12, modelActual: 18 });
    expect(queriesGenerated(snapshot())).toBe(false);
  });
});
