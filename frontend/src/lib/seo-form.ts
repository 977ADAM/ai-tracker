/**
 * Pure rules of one SEO analysis: what the five form fields must contain and
 * how many paid calls the run is going to make.
 *
 * The SEO flow has its own constants: the generated-query limit is fixed and
 * the form has no field for it, while the old 20-question validators in
 * `search-form.ts` keep serving the brand-check API unchanged.
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

export type SeoFormInput = {
  url: string;
  sphere: string;
  seeds: string[];
  services: string[];
  connectionIds: string[];
};

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

/** The services textarea: one service per line, trimmed, empty lines dropped. */
export function parseServices(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/** The three key queries: trimmed, empty fields dropped, duplicates kept for validation. */
export function parseSeeds(seeds: string[]): string[] {
  return seeds.map((seed) => seed.trim()).filter((seed) => seed.length > 0);
}

/**
 * Whether the value is a public HTTP(S) URL of a domain.
 *
 * A bare host is rejected on purpose: the crawler and the canonical host need a
 * scheme. IP literals are rejected with a dedicated message, exactly like the
 * backend rule, because a private address must never reach the fetcher.
 */
function urlProblem(value: string): string | null {
  const text = value.trim();
  if (!text) return 'Укажите адрес главной страницы сайта';
  let parsed: URL;
  try {
    parsed = new URL(text);
  } catch {
    return 'Укажите полный адрес сайта, например https://example.ru';
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return 'Укажите полный адрес сайта, например https://example.ru';
  }
  if (parsed.username || parsed.password || !parsed.hostname) {
    return 'Укажите полный адрес сайта, например https://example.ru';
  }
  if (isIpLiteral(parsed.hostname)) return 'Укажите адрес сайта доменом, а не IP';
  return null;
}

function isIpLiteral(host: string): boolean {
  const value = host.replace(/^\[|\]$/g, '');
  if (value.includes(':')) return true;
  const parts = value.split('.');
  return parts.length === 4 && parts.every((part) => /^\d{1,3}$/.test(part));
}

/**
 * The first problem the user has to fix, or null when the analysis can start.
 *
 * Never throws: every branch returns a ready Russian sentence for the form.
 */
export function validateSeoForm(input: SeoFormInput): string | null {
  const problem = urlProblem(input.url);
  if (problem) return problem;

  const sphere = input.sphere.trim();
  if (!sphere) return 'Укажите сферу бизнеса';
  if (sphere.length > MAX_SPHERE_LENGTH) return `Сфера бизнеса должна быть не длиннее ${MAX_SPHERE_LENGTH} символов`;

  const seeds = parseSeeds(input.seeds);
  if (seeds.length !== SEO_SEED_COUNT) return `Укажите ровно ${SEO_SEED_COUNT} ключевых запроса`;
  if (new Set(seeds).size !== seeds.length) return 'Ключевые запросы не должны повторяться';
  if (seeds.some((seed) => seed.length > MAX_QUERY_LENGTH)) {
    return `Ключевой запрос должен быть не длиннее ${MAX_QUERY_LENGTH} символов`;
  }

  const services = input.services.map((service) => service.trim()).filter((service) => service.length > 0);
  if (services.length === 0) return 'Добавьте хотя бы одну услугу';
  if (services.length > MAX_SERVICES) return `Не больше ${MAX_SERVICES} услуг`;
  if (services.some((service) => service.length > MAX_SERVICE_LENGTH)) {
    return `Название услуги должно быть не длиннее ${MAX_SERVICE_LENGTH} символов`;
  }

  const connections = new Set(input.connectionIds);
  if (connections.size < 1 || connections.size > MAX_CONNECTIONS) {
    return `Выберите от 1 до ${MAX_CONNECTIONS} подключений моделей`;
  }

  return null;
}

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
