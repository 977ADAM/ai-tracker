/**
 * The cost model of one SEO analysis: the fixed limits of the run and the
 * estimates built from them.
 *
 * The chat asks for the run parameters in words and the backend validates
 * them, so the old client-side form rules are gone; what stays is what the run
 * cards need — the connection limit and the call estimates.
 */
import type { SeoAnalysisSnapshot } from './types';

/** At most this many unique queries are generated per run, and to the Yandex seeds. */
export const GENERATED_QUERY_LIMIT = 2;
/** Model answers are paid for per run, not per connection: this is the flat cap. */
export const MAX_MODEL_ANSWERS = 5;
/** Exactly three key queries are sent to Yandex in stage 2. */
export const SEO_SEED_COUNT = 3;
export const MAX_SPHERE_LENGTH = 200;
export const MAX_SERVICES = 20;
export const MAX_SERVICE_LENGTH = 100;
export const MAX_CONNECTIONS = 5;
export const MAX_QUERY_LENGTH = 400;

/** Search requests of stage 2: exactly three key queries plus the generated ones. */
export const SEED_SEARCHES = 3;
export const SEARCH_UPPER = SEED_SEARCHES + GENERATED_QUERY_LIMIT;

export type SeoUpperEstimate = {
  searchUpper: number;
  modelUpper: number;
  generatedLimit: number;
  connections: number;
};

export type SeoActualEstimate = { searchActual: number; modelActual: number };

/** The six stages, in the order the orchestrator runs them. */
export const SEO_STAGE_LABELS: readonly string[] = [
  'Анализ сайта',
  'Поиск конкурентов',
  'Генерация запросов',
  'Проверки в ИИ и Поиске',
  'Анализ результатов',
  'Отчёт'
];

/**
 * The upper bound shown next to the submit button, before anything is generated.
 *
 * The model cap is flat — one number for the whole run, whatever the connection
 * count — but a run without a single selected connection makes no model call at
 * all, so the estimate stays `0` until one is chosen.
 */
export function estimateUpper(connections: number): SeoUpperEstimate {
  return {
    searchUpper: SEARCH_UPPER,
    modelUpper: connections > 0 ? MAX_MODEL_ANSWERS : 0,
    generatedLimit: GENERATED_QUERY_LIMIT,
    connections
  };
}

/** The informational estimate once the generated query count `K` is known. */
export function estimateActual(queries: number, connections: number): SeoActualEstimate {
  return {
    searchActual: SEED_SEARCHES + queries,
    modelActual: Math.min(queries * connections, MAX_MODEL_ANSWERS)
  };
}

/** The number of generated queries `K` of a saved analysis. */
export function actualQueryCount(snapshot: SeoAnalysisSnapshot): number {
  const saved = snapshot.queries.length;
  return saved > 0 ? saved : snapshot.counters.queries;
}

/** The number of selected connections `M` of a saved analysis. */
export function actualConnectionCount(snapshot: SeoAnalysisSnapshot): number {
  return snapshot.input.connection_ids.length;
}

/** `3 + K` search and at most the flat model-answer cap once the queries were generated. */
export function snapshotActualEstimate(snapshot: SeoAnalysisSnapshot): SeoActualEstimate {
  return estimateActual(actualQueryCount(snapshot), actualConnectionCount(snapshot));
}

/** Whether the generated queries are already known, so the actual estimate can be shown. */
export function queriesGenerated(snapshot: SeoAnalysisSnapshot): boolean {
  return snapshot.readiness.queries_ready || snapshot.counters.queries > 0;
}
