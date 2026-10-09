import { describe, expect, it } from 'vitest';
import {
  actualConnectionCount,
  actualQueryCount,
  estimateActual,
  estimateUpper,
  GENERATED_QUERY_LIMIT,
  MAX_MODEL_ANSWERS,
  queriesGenerated,
  SEO_STAGE_LABELS,
  SEARCH_UPPER,
  snapshotActualEstimate,
} from './seo-form';
import type { SeoAnalysisSnapshot } from './types';

function snapshot(overrides: Partial<SeoAnalysisSnapshot> = {}): SeoAnalysisSnapshot {
  return {
    id: 'seo-1',
    status: 'running',
    created_at: '2026-09-28T00:00:00Z',
    updated_at: '2026-09-28T00:00:00Z',
    finished_at: null,
    input: {
      url: 'https://example.ru',
      host: 'example.ru',
      sphere: 'Цветы',
      seeds: ['а'],
      services: ['б'],
      connection_ids: ['model-1', 'model-2'],
    },
    estimate: { search_upper: 43, model_upper: 40, generated_limit: 40, connections: 2 },
    company_name: '',
    services: [],
    pages: [],
    stages: [],
    candidates: [],
    queries: [],
    counters: { queries: 0, search_rows: 0, model_rows: 0, search_errors: 0, model_errors: 0 },
    readiness: {
      report_ready: false,
      summary_ready: false,
      queries_ready: false,
      has_submitted_search_rows: false,
      has_unsubmitted_search_rows: false,
      has_unfinished_model_rows: false,
      search_rows: 0,
      model_rows: 0,
    },
    aggregates: {
      site: { search: {}, ai: {} },
      competitors: [],
      categories: {},
      services: {},
      sources: [],
      counts: {},
    },
    ...overrides,
  } as unknown as SeoAnalysisSnapshot;
}

describe('call estimates', () => {
  it('bounds the run before generation with M connections', () => {
    expect(estimateUpper(0)).toEqual({
      searchUpper: 5,
      modelUpper: 0,
      generatedLimit: 2,
      connections: 0,
    });
    expect(estimateUpper(1)).toEqual({
      searchUpper: 5,
      modelUpper: 5,
      generatedLimit: 2,
      connections: 1,
    });
    expect(estimateUpper(3)).toEqual({
      searchUpper: 5,
      modelUpper: 5,
      generatedLimit: 2,
      connections: 3,
    });
    expect(estimateUpper(5)).toEqual({
      searchUpper: 5,
      modelUpper: 5,
      generatedLimit: 2,
      connections: 5,
    });
    expect(SEARCH_UPPER).toBe(5);
    expect(GENERATED_QUERY_LIMIT).toBe(2);
    expect(MAX_MODEL_ANSWERS).toBe(5);
  });

  it('counts the actual K and K x M after generation, capped by the flat model budget', () => {
    expect(estimateActual(0, 3)).toEqual({ searchActual: 3, modelActual: 0 });
    expect(estimateActual(12, 3)).toEqual({ searchActual: 15, modelActual: 5 });
    expect(estimateActual(2, 1)).toEqual({ searchActual: 5, modelActual: 2 });
    expect(estimateActual(2, 2)).toEqual({ searchActual: 5, modelActual: 4 });
    expect(estimateActual(40, 5)).toEqual({ searchActual: 43, modelActual: 5 });
  });
});

describe('stage labels', () => {
  it('names the six stages in order', () => {
    expect(SEO_STAGE_LABELS).toEqual([
      'Анализ сайта',
      'Поиск конкурентов',
      'Генерация запросов',
      'Проверки в ИИ и Поиске',
      'Анализ результатов',
      'Отчёт',
    ]);
    expect(SEO_STAGE_LABELS).toHaveLength(6);
  });
});

describe('snapshot helpers', () => {
  it('reads K from the saved queries and M from the selected connections', () => {
    const withQueries = snapshot({
      queries: [
        {
          index: 1,
          text: 'а',
          category: 'commercial',
          service: null,
          flags: {
            mentions_company_name: false,
            mentions_company_host: false,
            mentions_candidate_host: false,
            branded: false,
          },
        },
      ],
      counters: { queries: 7, search_rows: 0, model_rows: 0, search_errors: 0, model_errors: 0 },
    });
    expect(actualQueryCount(withQueries)).toBe(1);
    expect(actualQueryCount(snapshot())).toBe(0);
    expect(actualConnectionCount(snapshot())).toBe(2);
  });

  it('falls back to the counter while the query list is still empty', () => {
    const counted = snapshot({
      counters: { queries: 9, search_rows: 9, model_rows: 18, search_errors: 0, model_errors: 0 },
    });
    expect(actualQueryCount(counted)).toBe(9);
    expect(queriesGenerated(counted)).toBe(true);
    expect(snapshotActualEstimate(counted)).toEqual({ searchActual: 12, modelActual: 5 });
    expect(queriesGenerated(snapshot())).toBe(false);
  });
});
