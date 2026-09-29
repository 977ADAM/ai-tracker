import type {
  ApiPath, FormConfig, PublicProvider, SearchCreated, SearchRegion, SearchRow, SearchRowStatus,
  SearchSnapshot, SettingsProvider, RunCreated, RunHistoryPage, RunSnapshot, RunSummaryRow,
  RunModelRow, RunSearchRow, YandexSearchSettings,
  SeoAggregates, SeoAgent, SeoAgentStatus, SeoAnalysisCreated, SeoAnalysisSnapshot, SeoAnalysisStatus,
  SeoBudgetItem, SeoBudgetView, SeoCategoryAggregates, SeoCandidate, SeoCompetitorAggregates,
  SeoConclusions, SeoCounts, SeoEstimate, SeoHistoryPage, SeoMetric, SeoModelRow, SeoQuery,
  SeoQueryFlags, SeoReadiness, SeoRow, SeoRowsKind, SeoRowsPage, SeoRowStatus, SeoSearchMetrics,
  SeoSearchRow, SeoSettings, SeoSettingsTest, SeoSiteAggregates, SeoSiteAiBlock, SeoSiteAiMetrics,
  SeoSource, SeoStage, SeoStageStatus, SeoTracePage, SeoTraceStep
} from '$lib/types';

const DEFAULT_API_ORIGIN = 'http://127.0.0.1:8000';
const MAX_BODY_BYTES = 64 * 1024;
const MAX_CSV_BYTES = 5 * 1024 * 1024;
/** The shared request budget; a real LLM call does not fit into it. */
export const DEFAULT_TIMEOUT_MS = 10_000;
/** `POST /api/seo/settings/test` waits for one real chat completion. */
export const SEO_SETTINGS_TEST_TIMEOUT_MS = 120_000;

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } });
}

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid API response');
  return value as Record<string, unknown>;
}

function requiredString(value: unknown): string {
  if (typeof value !== 'string' || !value) throw new Error('Invalid API response');
  return value;
}

function stringValue(value: unknown): string {
  if (typeof value !== 'string') throw new Error('Invalid API response');
  return value;
}

function strings(value: unknown): string[] {
  if (!Array.isArray(value)) throw new Error('Invalid API response');
  return value.map(stringValue);
}

function integers(value: unknown): number[] {
  if (!Array.isArray(value)) throw new Error('Invalid API response');
  return value.map(requiredInteger);
}

function requiredInteger(value: unknown): number {
  if (typeof value !== 'number' || !Number.isInteger(value)) throw new Error('Invalid API response');
  return value;
}

function optionalString(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== 'string') throw new Error('Invalid API response');
  return value;
}

function optionalInteger(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  return requiredInteger(value);
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[]): T {
  if (typeof value !== 'string' || !allowed.includes(value as T)) throw new Error('Invalid API response');
  return value as T;
}

function requiredBoolean(value: unknown): boolean {
  if (typeof value !== 'boolean') throw new Error('Invalid API response');
  return value;
}

function optionalBoolean(value: unknown): boolean | null {
  if (value === null || value === undefined) return null;
  return requiredBoolean(value);
}

function optionalNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error('Invalid API response');
  return value;
}

function requiredNumber(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error('Invalid API response');
  return value;
}

function integerRecord(value: unknown): Record<string, number> {
  const item = record(value);
  return Object.fromEntries(Object.entries(item).map(([key, entry]) => [key, requiredInteger(entry)]));
}

function apiOrigin(): string {
  const url = new URL(process.env.AI_TRACKER_API_URL || DEFAULT_API_ORIGIN);
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(url.hostname) ||
      url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Invalid Python API origin');
  }
  return url.origin;
}

export function providerPath(id: string): ApiPath {
  if (!/^[A-Za-z0-9-]{1,64}$/.test(id)) throw new Error('Invalid provider ID');
  return `/api/providers/${encodeURIComponent(id)}`;
}

export function settingsProviderPath(id: string): ApiPath {
  if (!/^[A-Za-z0-9-]{1,64}$/.test(id)) throw new Error('Invalid provider ID');
  return `/api/providers/settings/${encodeURIComponent(id)}`;
}

export function searchPath(id: string): ApiPath {
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(id)) throw new Error('Invalid search ID');
  return `/api/search/${encodeURIComponent(id)}`;
}

export function runPath(id: string): ApiPath {
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(id)) throw new Error('Invalid run ID');
  return `/api/runs/${encodeURIComponent(id)}`;
}

export function runExportPath(id: string): ApiPath {
  return `${runPath(id)}/export.csv` as ApiPath;
}

export function runListPath(cursor: string | null): ApiPath {
  if (cursor === null) return '/api/runs';
  if (!/^[A-Za-z0-9_-]{1,256}$/.test(cursor)) throw new Error('Invalid cursor');
  return `/api/runs?cursor=${cursor}`;
}

function seoCursor(cursor: string): string {
  if (!/^[A-Za-z0-9_-]{1,256}$/.test(cursor)) throw new Error('Invalid cursor');
  return cursor;
}

export function seoAnalysisPath(id: string): ApiPath {
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(id)) throw new Error('Invalid SEO analysis ID');
  return `/api/seo/analyses/${encodeURIComponent(id)}`;
}

export function seoAnalysisCancelPath(id: string): ApiPath {
  return `${seoAnalysisPath(id)}/cancel` as ApiPath;
}

export function seoAnalysisRowsPath(id: string, kind: SeoRowsKind, cursor: string | null): ApiPath {
  if (kind !== 'model' && kind !== 'search') throw new Error('Invalid rows kind');
  const query = cursor === null ? `kind=${kind}` : `kind=${kind}&cursor=${seoCursor(cursor)}`;
  return `${seoAnalysisPath(id)}/rows?${query}` as ApiPath;
}

export function seoAnalysisTracePath(id: string, cursor: string | null): ApiPath {
  const suffix = cursor === null ? '' : `?cursor=${seoCursor(cursor)}`;
  return `${seoAnalysisPath(id)}/trace${suffix}` as ApiPath;
}

export function seoAnalysisListPath(cursor: string | null): ApiPath {
  if (cursor === null) return '/api/seo/analyses';
  return `/api/seo/analyses?cursor=${seoCursor(cursor)}`;
}

const SEO_ROWS_SUFFIX = /^([^/]+)\/rows\?kind=(model|search)(?:&cursor=([A-Za-z0-9_-]{1,256}))?$/;
const SEO_TRACE_SUFFIX = /^([^/]+)\/trace(?:\?cursor=([A-Za-z0-9_-]{1,256}))?$/;

function validPath(path: ApiPath): boolean {
  if (path === '/api/runs') return true;
  if (path.startsWith('/api/runs?cursor=')) {
    try { return runListPath(path.slice('/api/runs?cursor='.length)) === path; }
    catch { return false; }
  }
  if (path.startsWith('/api/runs/')) {
    const suffix = path.slice('/api/runs/'.length);
    if (suffix.endsWith('/export.csv')) {
      try { return runExportPath(suffix.slice(0, -'/export.csv'.length)) === path; }
      catch { return false; }
    }
    try { return runPath(suffix) === path; }
    catch { return false; }
  }
  // The static SEO settings paths come before the dynamic analysis route.
  if (path === '/api/seo/settings' || path === '/api/seo/settings/credentials' || path === '/api/seo/settings/test') return true;
  if (path === '/api/seo/analyses') return true;
  if (path.startsWith('/api/seo/analyses?cursor=')) {
    try { return seoAnalysisListPath(path.slice('/api/seo/analyses?cursor='.length)) === path; }
    catch { return false; }
  }
  if (path.startsWith('/api/seo/analyses/')) {
    const suffix = path.slice('/api/seo/analyses/'.length);
    if (suffix.endsWith('/cancel')) {
      try { return seoAnalysisCancelPath(suffix.slice(0, -'/cancel'.length)) === path; }
      catch { return false; }
    }
    const rows = SEO_ROWS_SUFFIX.exec(suffix);
    if (rows) {
      try { return seoAnalysisRowsPath(decodeURIComponent(rows[1]), rows[2] as SeoRowsKind, rows[3] ?? null) === path; }
      catch { return false; }
    }
    const trace = SEO_TRACE_SUFFIX.exec(suffix);
    if (trace) {
      try { return seoAnalysisTracePath(decodeURIComponent(trace[1]), trace[2] ?? null) === path; }
      catch { return false; }
    }
    try { return seoAnalysisPath(suffix) === path; }
    catch { return false; }
  }
  if (path === '/api/providers' || path === '/api/check' || path === '/api/form' || path === '/api/providers/settings') return true;
  // The static catalog comes before the dynamic job route, exactly as in Python.
  if (path === '/api/search' || path === '/api/search/regions' || path === '/api/search/settings' ||
      path === '/api/search/settings/credentials') return true;
  if (path.startsWith('/api/search/')) {
    try { return searchPath(decodeURIComponent(path.slice('/api/search/'.length))) === path; }
    catch { return false; }
  }
  if (path.startsWith('/api/providers/settings/')) {
    try { return settingsProviderPath(decodeURIComponent(path.slice('/api/providers/settings/'.length))) === path; }
    catch { return false; }
  }
  if (!path.startsWith('/api/providers/')) return false;
  try { return providerPath(decodeURIComponent(path.slice('/api/providers/'.length))) === path; }
  catch { return false; }
}

const RUN_STATUSES = ['pending', 'done', 'interrupted'] as const;
const MODEL_RUN_STATUSES = ['pending', 'mentioned', 'absent', 'error', 'interrupted'] as const;
const SEARCH_RUN_STATUSES = ['submitting', 'waiting', 'found', 'absent', 'error', 'interrupted'] as const;

export function publicRunCreated(value: unknown): RunCreated {
  const item = record(value);
  const id = requiredString(item.id);
  runPath(id);
  return { id, status: oneOf(item.status, RUN_STATUSES) };
}

function runModelRow(value: unknown): RunModelRow {
  const row = record(value);
  const mentioned = row.mentioned;
  if (mentioned !== null && typeof mentioned !== 'boolean') throw new Error('Invalid model row');
  return {
    provider_id: requiredString(row.provider_id), prompt_index: requiredInteger(row.prompt_index),
    provider_name: requiredString(row.provider_name), prompt: requiredString(row.prompt),
    status: oneOf(row.status, MODEL_RUN_STATUSES), answer: optionalString(row.answer),
    mentioned: mentioned as boolean | null, error: optionalString(row.error)
  };
}

function runSearchRow(value: unknown): RunSearchRow {
  const row = record(value);
  return {
    search_index: requiredInteger(row.search_index), prompt_index: requiredInteger(row.prompt_index),
    region_index: requiredInteger(row.region_index), prompt: requiredString(row.prompt),
    region_id: requiredInteger(row.region_id), region_name: requiredString(row.region_name),
    status: oneOf(row.status, SEARCH_RUN_STATUSES), position: optionalInteger(row.position),
    url: optionalString(row.url), error: optionalString(row.error)
  };
}

function runSummaryRow(value: unknown): RunSummaryRow {
  const row = record(value);
  return {
    prompt: stringValue(row.prompt), source: stringValue(row.source),
    language: stringValue(row.language), region: stringValue(row.region),
    ai_answer: stringValue(row.ai_answer), site_found: stringValue(row.site_found),
    position: stringValue(row.position), brand_found: stringValue(row.brand_found),
    status: stringValue(row.status)
  };
}

export function publicRunSnapshot(value: unknown): RunSnapshot {
  const item = record(value);
  const id = requiredString(item.id);
  runPath(id);
  if (!Array.isArray(item.models) || !Array.isArray(item.search) || !Array.isArray(item.summary_rows))
    throw new Error('Invalid run snapshot');
  return {
    id, created_at: requiredString(item.created_at), finished_at: optionalString(item.finished_at),
    status: oneOf(item.status, RUN_STATUSES), brand: stringValue(item.brand), domain: stringValue(item.domain),
    prompts: strings(item.prompts), provider_ids: strings(item.provider_ids), regions: integers(item.regions),
    models: item.models.map(runModelRow), search: item.search.map(runSearchRow),
    summary_rows: item.summary_rows.map(runSummaryRow)
  };
}

export function publicRunList(value: unknown): RunHistoryPage {
  const page = record(value);
  if (!Array.isArray(page.items)) throw new Error('Invalid run history');
  const next_cursor = optionalString(page.next_cursor);
  if (next_cursor !== null) runListPath(next_cursor);
  return { items: page.items.map((raw) => {
    const item = record(raw);
    const id = requiredString(item.id);
    runPath(id);
    return { id, created_at: requiredString(item.created_at), status: oneOf(item.status, RUN_STATUSES),
      prompts: strings(item.prompts) };
  }), next_cursor };
}

export function publicConfigurationFile(value: unknown): { path: string; exists: boolean; content: string | null } {
  const item = record(value);
  const exists = item.exists;
  if (typeof exists !== 'boolean') throw new Error('Invalid configuration file');
  const content = item.content;
  if (exists) {
    if (typeof content !== 'string') throw new Error('Invalid configuration file');
    return { path: requiredString(item.path), exists, content };
  }
  if (content !== null) throw new Error('Invalid configuration file');
  return { path: requiredString(item.path), exists, content: null };
}

export function publicSettingsProvider(value: unknown): SettingsProvider {
  const item = record(value);
  if (!Array.isArray(item.models)) throw new Error('Invalid settings provider');
  if (typeof item.configured !== 'boolean') throw new Error('Invalid settings provider');
  return {
    id: requiredString(item.id), name: requiredString(item.name), kind: requiredString(item.kind),
    endpoint: requiredString(item.endpoint), configured: item.configured,
    models: item.models.map((raw) => {
      const model = record(raw);
      return { id: requiredString(model.id), model: requiredString(model.model), name: requiredString(model.name) };
    })
  };
}

export function publicProvider(value: unknown): Record<string, unknown> {
  const item = record(value);
  const allowed = ['id', 'name', 'kind', 'endpoint', 'model', 'scope', 'configured', 'editable_fields', 'can_reset', 'can_delete', 'status_label', 'delete_label', 'delete_prompt', 'delete_success'] as const;
  return Object.fromEntries(allowed.filter((key) => key in item).map((key) => [key, item[key]]));
}

export function publicCheck(value: unknown): Record<string, unknown> {
  const item = record(value);
  if (!Array.isArray(item.checks) || !Array.isArray(item.rows)) throw new Error('Invalid checks');
  const summary = record(item.summary);
  const publicResult = (raw: unknown) => {
    const result = record(raw);
    return { prompt: result.prompt, answer: result.answer, mentioned: result.mentioned, error: result.error, status: result.status };
  };
  return {
    brand: item.brand,
    domain: item.domain,
    summary: { successful: summary.successful, failed: summary.failed, mentioned: summary.mentioned, mention_percent: summary.mention_percent,
      visibility_label: summary.visibility_label, mentions_label: summary.mentions_label, errors_label: summary.errors_label },
    rows: item.rows.map((raw) => ({ ...publicResult(raw), provider_name: record(raw).provider_name })),
    checks: item.checks.map((raw) => {
      const group = record(raw);
      const summary = record(group.summary);
      if (!Array.isArray(group.results)) throw new Error('Invalid results');
      return {
        provider_id: group.provider_id,
        provider_name: group.provider_name,
        summary: { successful: summary.successful, failed: summary.failed, mentioned: summary.mentioned },
        results: group.results.map(publicResult)
      };
    })
  };
}

const JOB_STATUSES = ['pending', 'done'] as const;
const ROW_STATUSES: readonly SearchRowStatus[] = ['submitting', 'waiting', 'found', 'absent', 'error'];

export function publicSearchRegions(value: unknown): SearchRegion[] {
  if (!Array.isArray(value)) throw new Error('Invalid search regions');
  return value.map((raw) => {
    const item = record(raw);
    return { id: requiredInteger(item.id), name: requiredString(item.name) };
  });
}

export function publicSearchSettings(value: unknown): { yandex: YandexSearchSettings } {
  const item = record(record(value).yandex);
  if (typeof item.enabled !== 'boolean' || typeof item.has_api_key !== 'boolean' ||
      (item.folder_id !== null && typeof item.folder_id !== 'string')) throw new Error('Invalid search settings');
  return { yandex: {
    enabled: item.enabled,
    folder_id: item.folder_id,
    has_api_key: item.has_api_key,
    api_key_source: oneOf(item.api_key_source, ['ui', 'env', 'none'] as const),
    folder_id_source: oneOf(item.folder_id_source, ['ui', 'env', 'none'] as const)
  } };
}

export function publicSearchCreated(value: unknown): SearchCreated {
  const item = record(value);
  const total = requiredInteger(item.total);
  if (total < 1) throw new Error('Invalid search job');
  return { id: requiredString(item.id), total, status: oneOf(item.status, JOB_STATUSES) };
}

function searchRow(value: unknown): SearchRow {
  const row = record(value);
  return {
    prompt: requiredString(row.prompt),
    region_id: requiredInteger(row.region_id),
    region_name: requiredString(row.region_name),
    status: oneOf(row.status, ROW_STATUSES),
    position: optionalInteger(row.position),
    url: optionalString(row.url),
    error: optionalString(row.error)
  };
}

export function publicSearchSnapshot(value: unknown): SearchSnapshot {
  const item = record(value);
  if (!Array.isArray(item.regions) || !Array.isArray(item.results)) throw new Error('Invalid search snapshot');
  const summary = record(item.summary);
  return {
    id: requiredString(item.id),
    domain: requiredString(item.domain),
    regions: item.regions.map(requiredInteger),
    total: requiredInteger(item.total),
    completed: requiredInteger(item.completed),
    status: oneOf(item.status, JOB_STATUSES),
    summary: {
      successful: requiredInteger(summary.successful),
      found: requiredInteger(summary.found),
      failed: requiredInteger(summary.failed)
    },
    results: item.results.map(searchRow)
  };
}

const SEO_SOURCES: readonly SeoSource[] = ['ui', 'env', 'none'];
const SEO_ANALYSIS_STATUSES: readonly SeoAnalysisStatus[] =
  ['running', 'completed', 'failed', 'interrupted', 'cancelled'];
const SEO_STAGE_STATUSES: readonly SeoStageStatus[] = ['pending', 'running', 'done', 'error', 'skipped'];
const SEO_ROW_STATUSES: readonly SeoRowStatus[] =
  ['pending', 'submitting', 'waiting', 'found', 'absent', 'error', 'interrupted', 'cancelled'];
const SEO_AGENT_STATUSES: readonly SeoAgentStatus[] =
  ['pending', 'running', 'waiting', 'done', 'error', 'skipped'];
const SEO_TRACE_KINDS = ['model', 'tool', 'handoff', 'system'] as const;
const SEO_TRACE_STATUSES = ['pending', 'running', 'done', 'error', 'rejected', 'skipped'] as const;

/**
 * Project the public service-LLM settings.
 *
 * Only the six public fields are copied: a returned `api_key`, an upstream
 * echo, or any future backend field is dropped instead of being forwarded.
 */
export function publicSeoSettings(value: unknown): SeoSettings {
  const item = record(value);
  return {
    endpoint: optionalString(item.endpoint),
    model: optionalString(item.model),
    has_api_key: requiredBoolean(item.has_api_key),
    endpoint_source: oneOf(item.endpoint_source, SEO_SOURCES),
    model_source: oneOf(item.model_source, SEO_SOURCES),
    api_key_source: oneOf(item.api_key_source, SEO_SOURCES)
  };
}

/** The availability probe answers with a safe result and never with a key. */
export function publicSeoSettingsTest(value: unknown): SeoSettingsTest {
  const item = record(value);
  return {
    ok: requiredBoolean(item.ok),
    model: optionalString(item.model),
    error: optionalString(item.error)
  };
}

export function publicSeoAnalysisCreated(value: unknown): SeoAnalysisCreated {
  const item = record(value);
  const id = requiredString(item.id);
  seoAnalysisPath(id);
  return { id, status: oneOf(item.status, ['running'] as const), estimate: seoEstimate(item.estimate) };
}

function seoEstimate(value: unknown): SeoEstimate {
  const item = record(value);
  return {
    search_upper: requiredInteger(item.search_upper),
    model_upper: requiredInteger(item.model_upper),
    generated_limit: requiredInteger(item.generated_limit),
    connections: requiredInteger(item.connections)
  };
}

function seoCounts(value: unknown): SeoCounts {
  const item = record(value);
  return {
    queries: requiredInteger(item.queries),
    search_rows: requiredInteger(item.search_rows),
    model_rows: requiredInteger(item.model_rows),
    search_errors: requiredInteger(item.search_errors),
    model_errors: requiredInteger(item.model_errors)
  };
}

function seoMetric(value: unknown): SeoMetric {
  const item = record(value);
  return {
    denominator: requiredInteger(item.denominator),
    successes: requiredInteger(item.successes),
    share: optionalNumber(item.share),
    average_position: optionalNumber(item.average_position)
  };
}

function seoSearchMetrics(value: unknown): SeoSearchMetrics {
  const item = record(value);
  return { overall: seoMetric(item.overall), branded: seoMetric(item.branded), unbranded: seoMetric(item.unbranded) };
}

function seoSiteAiMetrics(value: unknown): SeoSiteAiMetrics {
  const item = record(value);
  return { name: seoMetric(item.name), host: seoMetric(item.host), combined: seoMetric(item.combined) };
}

function seoSiteAiBlock(value: unknown): SeoSiteAiBlock {
  const item = record(value);
  return {
    ...seoSiteAiMetrics(item),
    branded: seoSiteAiMetrics(item.branded),
    unbranded: seoSiteAiMetrics(item.unbranded)
  };
}

function seoMetricRecord(value: unknown): Record<string, SeoMetric> {
  return Object.fromEntries(Object.entries(record(value)).map(([key, entry]) => [key, seoMetric(entry)]));
}

function seoNestedMetricRecord(value: unknown): Record<string, Record<string, SeoMetric>> {
  return Object.fromEntries(Object.entries(record(value)).map(([key, entry]) => [key, seoMetricRecord(entry)]));
}

function seoAggregates(value: unknown): SeoAggregates {
  const item = record(value);
  if (!Array.isArray(item.competitors)) throw new Error('Invalid SEO aggregates');
  const siteRaw = record(item.site);
  const site: SeoSiteAggregates = {
    search: seoSearchMetrics(siteRaw.search),
    ai: Object.fromEntries(Object.entries(record(siteRaw.ai)).map(([key, entry]) => [key, seoSiteAiBlock(entry)]))
  };
  const competitors: SeoCompetitorAggregates[] = item.competitors.map((raw) => {
    const competitor = record(raw);
    return {
      host: requiredString(competitor.host),
      title: stringValue(competitor.title),
      occurrences: requiredInteger(competitor.occurrences),
      average_position: requiredNumber(competitor.average_position),
      seed_indexes: integers(competitor.seed_indexes),
      search: seoSearchMetrics(competitor.search),
      ai: seoNestedMetricRecord(competitor.ai)
    };
  });
  const groups = (raw: unknown): Record<string, SeoCategoryAggregates> =>
    Object.fromEntries(Object.entries(record(raw)).map(([key, entry]) => {
      const group = record(entry);
      return [key, { search: seoMetric(group.search), ai: seoMetricRecord(group.ai) }];
    }));
  return {
    site,
    competitors,
    categories: groups(item.categories),
    services: groups(item.services),
    counts: seoCounts(item.counts)
  };
}

function seoStage(value: unknown): SeoStage {
  const item = record(value);
  return {
    stage: requiredInteger(item.stage),
    status: oneOf(item.status, SEO_STAGE_STATUSES),
    error: optionalString(item.error),
    counters: integerRecord(item.counters),
    updated_at: requiredString(item.updated_at)
  };
}

function seoCandidate(value: unknown): SeoCandidate {
  const item = record(value);
  return {
    host: requiredString(item.host),
    title: stringValue(item.title),
    occurrences: requiredInteger(item.occurrences),
    average_position: requiredNumber(item.average_position),
    seed_indexes: integers(item.seed_indexes),
    recurring: requiredBoolean(item.recurring)
  };
}

function seoQueryFlags(value: unknown): SeoQueryFlags {
  const item = record(value);
  return {
    mentions_company_name: requiredBoolean(item.mentions_company_name),
    mentions_company_host: requiredBoolean(item.mentions_company_host),
    mentions_candidate_host: requiredBoolean(item.mentions_candidate_host),
    branded: requiredBoolean(item.branded)
  };
}

function seoQuery(value: unknown): SeoQuery {
  const item = record(value);
  return {
    index: requiredInteger(item.index),
    text: requiredString(item.text),
    category: requiredString(item.category),
    service: optionalString(item.service),
    flags: seoQueryFlags(item.flags)
  };
}

function seoReadiness(value: unknown): SeoReadiness {
  const item = record(value);
  return {
    report_ready: requiredBoolean(item.report_ready),
    summary_ready: requiredBoolean(item.summary_ready),
    queries_ready: requiredBoolean(item.queries_ready),
    has_submitted_search_rows: requiredBoolean(item.has_submitted_search_rows),
    has_unsubmitted_search_rows: requiredBoolean(item.has_unsubmitted_search_rows),
    has_unfinished_model_rows: requiredBoolean(item.has_unfinished_model_rows),
    search_rows: requiredInteger(item.search_rows),
    model_rows: requiredInteger(item.model_rows)
  };
}

/** One agent of the run: only its name, status, safe error and timestamp. */
function seoAgent(value: unknown): SeoAgent {
  const item = record(value);
  return {
    agent: requiredString(item.agent),
    status: oneOf(item.status, SEO_AGENT_STATUSES),
    error: optionalString(item.error),
    updated_at: optionalString(item.updated_at)
  };
}

function seoBudgetItem(value: unknown): SeoBudgetItem {
  const item = record(value);
  return { used: requiredInteger(item.used), limit: requiredInteger(item.limit) };
}

function seoBudget(value: unknown): SeoBudgetView {
  const item = record(value);
  return {
    pages: seoBudgetItem(item.pages),
    searches: seoBudgetItem(item.searches),
    model_answers: seoBudgetItem(item.model_answers),
    tool_calls: seoBudgetItem(item.tool_calls),
    handoffs: seoBudgetItem(item.handoffs),
    seed_searches: requiredInteger(item.seed_searches),
    model_rows: requiredInteger(item.model_rows),
    steps: requiredInteger(item.steps),
    agent_steps: integerRecord(item.agent_steps)
  };
}

/** The report agent's block: only the labelled text and the model name. */
function seoConclusions(value: unknown): SeoConclusions {
  const item = record(value);
  return {
    summary: stringValue(item.summary),
    recommendations: stringValue(item.recommendations),
    model: stringValue(item.model)
  };
}

/** One trace step: safe arguments and a short result, never a secret. */
function seoTraceStep(value: unknown): SeoTraceStep {
  const item = record(value);
  return {
    step_index: requiredInteger(item.step_index),
    agent: requiredString(item.agent),
    kind: oneOf(item.kind, SEO_TRACE_KINDS),
    name: requiredString(item.name),
    arguments: record(item.arguments),
    result_summary: optionalString(item.result_summary),
    status: oneOf(item.status, SEO_TRACE_STATUSES),
    error: optionalString(item.error),
    created_at: requiredString(item.created_at)
  };
}

/** Project the saved analysis; model answers and operation IDs never appear here. */
export function publicSeoSnapshot(value: unknown): SeoAnalysisSnapshot {
  const item = record(value);
  const id = requiredString(item.id);
  seoAnalysisPath(id);
  const input = record(item.input);
  if (!Array.isArray(item.services) || !Array.isArray(item.pages) || !Array.isArray(item.stages) ||
      !Array.isArray(item.agents) || !Array.isArray(item.candidates) || !Array.isArray(item.queries))
    throw new Error('Invalid SEO snapshot');
  return {
    id,
    status: oneOf(item.status, SEO_ANALYSIS_STATUSES),
    created_at: requiredString(item.created_at),
    updated_at: requiredString(item.updated_at),
    finished_at: optionalString(item.finished_at),
    input: {
      url: requiredString(input.url),
      host: requiredString(input.host),
      sphere: stringValue(input.sphere),
      seeds: strings(input.seeds),
      services: strings(input.services),
      connection_ids: strings(input.connection_ids)
    },
    estimate: seoEstimate(item.estimate),
    company_name: stringValue(item.company_name),
    services: strings(item.services),
    pages: item.pages.map((raw) => {
      const page = record(raw);
      return { url: requiredString(page.url), title: stringValue(page.title) };
    }),
    stages: item.stages.map(seoStage),
    agents: item.agents.map(seoAgent),
    budget: seoBudget(item.budget),
    budget_exhausted: requiredBoolean(item.budget_exhausted),
    candidates: item.candidates.map(seoCandidate),
    queries: item.queries.map(seoQuery),
    summary: optionalString(item.summary),
    conclusions: item.conclusions === null || item.conclusions === undefined
      ? null : seoConclusions(item.conclusions),
    counters: seoCounts(item.counters),
    readiness: seoReadiness(item.readiness),
    aggregates: seoAggregates(item.aggregates)
  };
}

export function publicSeoHistory(value: unknown): SeoHistoryPage {
  const page = record(value);
  if (!Array.isArray(page.items)) throw new Error('Invalid SEO history');
  const next_cursor = optionalString(page.next_cursor);
  if (next_cursor !== null) seoCursor(next_cursor);
  return {
    items: page.items.map((raw) => {
      const item = record(raw);
      const id = requiredString(item.id);
      seoAnalysisPath(id);
      return {
        id,
        created_at: requiredString(item.created_at),
        finished_at: optionalString(item.finished_at),
        status: oneOf(item.status, SEO_ANALYSIS_STATUSES),
        sphere: stringValue(item.sphere),
        host: requiredString(item.host),
        company_name: stringValue(item.company_name),
        counters: seoCounts(item.counters)
      };
    }),
    next_cursor
  };
}

function seoSearchRow(value: unknown): SeoSearchRow {
  const item = record(value);
  return {
    query_index: requiredInteger(item.query_index),
    query: optionalString(item.query),
    category: optionalString(item.category),
    service: optionalString(item.service),
    status: oneOf(item.status, SEO_ROW_STATUSES),
    site_position: optionalInteger(item.site_position),
    site_url: optionalString(item.site_url),
    error: optionalString(item.error)
  };
}

function seoModelRow(value: unknown): SeoModelRow {
  const item = record(value);
  return {
    query_index: requiredInteger(item.query_index),
    connection_id: requiredString(item.connection_id),
    provider_name: requiredString(item.provider_name),
    status: oneOf(item.status, SEO_ROW_STATUSES),
    answer: optionalString(item.answer),
    name_mentioned: optionalBoolean(item.name_mentioned),
    host_mentioned: optionalBoolean(item.host_mentioned),
    error: optionalString(item.error),
    query: optionalString(item.query),
    category: optionalString(item.category),
    service: optionalString(item.service)
  };
}

/** Project one page of the detail resource; the shape depends on the row kind. */
export function publicSeoRows(value: unknown, kind: SeoRowsKind): SeoRowsPage {
  const page = record(value);
  if (!Array.isArray(page.items)) throw new Error('Invalid SEO rows');
  const next_cursor = optionalString(page.next_cursor);
  if (next_cursor !== null) seoCursor(next_cursor);
  const project = (raw: unknown): SeoRow => (kind === 'model' ? seoModelRow(raw) : seoSearchRow(raw));
  return { items: page.items.map(project), next_cursor };
}

/** Project one page of the agent trace; secrets and operation IDs never appear here. */
export function publicSeoTracePage(value: unknown): SeoTracePage {
  const page = record(value);
  if (!Array.isArray(page.items)) throw new Error('Invalid SEO trace');
  const next_cursor = optionalString(page.next_cursor);
  if (next_cursor !== null) seoCursor(next_cursor);
  return { items: page.items.map(seoTraceStep), next_cursor };
}

export function publicForm(value: unknown): Record<string, unknown> {  const item = record(value);
  const limits = record(item.limits);
  if (!Array.isArray(item.scope_options) || !Array.isArray(item.new_provider_fields) || !Array.isArray(item.default_provider_ids)) throw new Error('Invalid form');
  return { limits: { max_prompts: limits.max_prompts, max_providers: limits.max_providers, max_prompt_length: limits.max_prompt_length,
    max_brand_length: limits.max_brand_length, max_domain_length: limits.max_domain_length },
    new_provider_fields: item.new_provider_fields, default_provider_ids: item.default_provider_ids, scope_options: item.scope_options.map((option) => {
      const entry = record(option);
      return { value: entry.value, label: entry.label };
    }) };
}

/**
 * The request budget for one upstream path.
 *
 * `/api/check` is streamed without a shared deadline, the SEO connection test
 * waits for a real LLM completion, and every other call keeps the short budget.
 */
export function apiTimeoutMs(path: ApiPath): number | undefined {
  if (path === '/api/check') return undefined;
  if (path === '/api/seo/settings/test') return SEO_SETTINGS_TEST_TIMEOUT_MS;
  return DEFAULT_TIMEOUT_MS;
}

export async function pythonApi(path: ApiPath, init: RequestInit = {}): Promise<Response> {
  if (!validPath(path)) throw new Error('Invalid Python API path');
  const timeout = apiTimeoutMs(path);
  const signal = init.signal ?? (timeout === undefined ? undefined : AbortSignal.timeout(timeout));
  return fetch(`${apiOrigin()}${path}`, { ...init, signal, redirect: 'manual' });
}

export async function loadPageData(): Promise<{ providers: PublicProvider[]; settingsProviders: SettingsProvider[]; form: FormConfig | null; searchRegions: SearchRegion[]; searchRegionError: string; searchSettings: YandexSearchSettings | null; searchSettingsError: string; seoSettings: SeoSettings | null; seoSettingsError: string; loadError: string }> {
  // The region catalog is an independent request: a failure there must not stop
  // the model list, and vice versa.
  const { regions: searchRegions, error: searchRegionError } = await loadSearchRegions();
  const { settings: searchSettings, error: searchSettingsError } = await loadSearchSettings();
  // The SEO service-LLM settings are independent as well: an unavailable SEO
  // resource must never take the model configuration down with it.
  const { settings: seoSettings, error: seoSettingsError } = await loadSeoSettings();
  try {
    const [providerResponse, formResponse, settingsResponse] = await Promise.all([pythonApi('/api/providers'), pythonApi('/api/form'), pythonApi('/api/providers/settings')]);
    if (!providerResponse.ok || !formResponse.ok || !settingsResponse.ok ||
        !/^application\/json(?:\s*;|$)/i.test(providerResponse.headers.get('content-type') || '') ||
        !/^application\/json(?:\s*;|$)/i.test(formResponse.headers.get('content-type') || '') ||
        !/^application\/json(?:\s*;|$)/i.test(settingsResponse.headers.get('content-type') || '')) throw new Error('Invalid API response');
    const providers: unknown = await providerResponse.json();
    const settingsProviders: unknown = await settingsResponse.json();
    if (!Array.isArray(providers) || !Array.isArray(settingsProviders)) throw new Error('Invalid providers');
    return { providers: providers.map((item) => publicProvider(item) as PublicProvider), settingsProviders: settingsProviders.map(publicSettingsProvider), form: publicForm(await formResponse.json()) as FormConfig, searchRegions, searchRegionError, searchSettings, searchSettingsError, seoSettings, seoSettingsError, loadError: '' };
  } catch {
    return { providers: [], settingsProviders: [], form: null, searchRegions, searchRegionError, searchSettings, searchSettingsError, seoSettings, seoSettingsError, loadError: 'Python API недоступен. Проверьте, запущены ли оба сервиса.' };
  }
}

async function loadSeoSettings(): Promise<{ settings: SeoSettings | null; error: string }> {
  try {
    const response = await pythonApi('/api/seo/settings');
    if (!response.ok || !/^application\/json(?:\s*;|$)/i.test(response.headers.get('content-type') || ''))
      throw new Error('Invalid SEO settings');
    return { settings: publicSeoSettings(await response.json()), error: '' };
  } catch {
    return { settings: null, error: 'Настройки служебной LLM недоступны' };
  }
}

async function loadSearchSettings(): Promise<{ settings: YandexSearchSettings | null; error: string }> {
  try {
    const response = await pythonApi('/api/search/settings');
    if (!response.ok || !/^application\/json(?:\s*;|$)/i.test(response.headers.get('content-type') || ''))
      throw new Error('Invalid search settings');
    return { settings: publicSearchSettings(await response.json()).yandex, error: '' };
  } catch {
    return { settings: null, error: 'Настройки поисковых систем недоступны' };
  }
}

async function loadSearchRegions(): Promise<{ regions: SearchRegion[]; error: string }> {
  try {
    const response = await pythonApi('/api/search/regions');
    if (!response.ok || !/^application\/json(?:\s*;|$)/i.test(response.headers.get('content-type') || '')) throw new Error('Invalid search regions');
    return { regions: publicSearchRegions(await response.json()), error: '' };
  } catch {
    return { regions: [], error: 'Справочник регионов недоступен' };
  }
}

export async function proxyJson(request: Request, path: ApiPath, method: string): Promise<Response> {
  if (!validPath(path)) return json({ detail: 'Некорректное подключение' }, 400);
  if (!['GET', 'POST', 'PUT', 'DELETE'].includes(method)) return json({ detail: 'Недопустимый метод' }, 405);
  const searchSettingsPath = path === '/api/search/settings' || path === '/api/search/settings/credentials';
  if (searchSettingsPath && !(path === '/api/search/settings' ? ['GET', 'PUT'].includes(method) : method === 'DELETE'))
    return json({ detail: 'Недопустимый метод' }, 405);
  const seoSettingsPath = path === '/api/seo/settings' || path === '/api/seo/settings/credentials' ||
    path === '/api/seo/settings/test';
  if (seoSettingsPath) {
    const allowed = path === '/api/seo/settings' ? ['GET', 'PUT']
      : path === '/api/seo/settings/credentials' ? ['DELETE'] : ['POST'];
    if (!allowed.includes(method)) return json({ detail: 'Недопустимый метод' }, 405);
  }
  // The connection probe and the cancel action are bodyless POSTs: neither
  // carries a payload, and the probe triggers one upstream chat call.
  const bodylessPost = path === '/api/seo/settings/test' ||
    (path.startsWith('/api/seo/analyses/') && path.endsWith('/cancel'));
  let body: string | undefined;
  if (method !== 'GET') {
    const origin = request.headers.get('origin');
    if (origin && origin !== new URL(request.url).origin) return json({ detail: 'Недопустимый источник запроса' }, 403);
    const declared = request.headers.get('content-length');
    if (declared && Number(declared) > MAX_BODY_BYTES) return json({ detail: 'Запрос слишком большой' }, 413);
    if (method === 'DELETE') {
      if (await request.text()) return json({ detail: 'Удаление не принимает тело запроса' }, 400);
    } else if (!bodylessPost) {
      if (!/^application\/json(?:\s*;|$)/i.test(request.headers.get('content-type') || '')) return json({ detail: 'Ожидается JSON' }, 415);
      body = await request.text();
      if (new TextEncoder().encode(body).byteLength > MAX_BODY_BYTES) return json({ detail: 'Запрос слишком большой' }, 413);
      try { JSON.parse(body); }
      catch { return json({ detail: 'Некорректный JSON' }, 400); }
    }
  }
  let upstream: Response;
  try {
    upstream = await pythonApi(path, { method, headers: body === undefined ? undefined : { 'content-type': 'application/json' }, body });
  } catch {
    return json({ detail: 'Python API недоступен' }, 502);
  }
  if (method === 'DELETE' && upstream.status === 204 && !searchSettingsPath && !seoSettingsPath) return new Response(null, { status: 204, headers: { 'cache-control': 'no-store' } });
  if (!/^application\/json(?:\s*;|$)/i.test(upstream.headers.get('content-type') || '')) return json({ detail: 'Некорректный ответ Python API' }, 502);
  try {
    const value: unknown = await upstream.json();
    if (!upstream.ok) {
      if (searchSettingsPath) return json({ detail: 'Ошибка настроек поисковой системы' }, upstream.status);
      if (seoSettingsPath) return json({ detail: 'Ошибка настроек служебной LLM' }, upstream.status);
      const detail = record(value).detail;
      return json({ detail: typeof detail === 'string' ? detail : 'Ошибка Python API' }, upstream.status);
    }
    if (path === '/api/runs' && method === 'POST') return json(publicRunCreated(value), upstream.status);
    if ((path === '/api/runs' || path.startsWith('/api/runs?cursor=')) && method === 'GET') return json(publicRunList(value), upstream.status);
    if (path.startsWith('/api/runs/') && method === 'GET') return json(publicRunSnapshot(value), upstream.status);
    if (path === '/api/seo/settings' || path === '/api/seo/settings/credentials')
      return json(publicSeoSettings(value), upstream.status);
    if (path === '/api/seo/settings/test') return json(publicSeoSettingsTest(value), upstream.status);
    if (path === '/api/seo/analyses' && method === 'POST') return json(publicSeoAnalysisCreated(value), upstream.status);
    if ((path === '/api/seo/analyses' || path.startsWith('/api/seo/analyses?cursor=')) && method === 'GET')
      return json(publicSeoHistory(value), upstream.status);
    const seoRows = /^\/api\/seo\/analyses\/[^/]+\/rows\?kind=(model|search)/.exec(path);
    if (seoRows && method === 'GET') return json(publicSeoRows(value, seoRows[1] as SeoRowsKind), upstream.status);
    if (/^\/api\/seo\/analyses\/[^/]+\/trace(?:\?|$)/.test(path) && method === 'GET')
      return json(publicSeoTracePage(value), upstream.status);
    if (path.startsWith('/api/seo/analyses/') && method === 'GET') return json(publicSeoSnapshot(value), upstream.status);
    if (path.endsWith('/cancel') && method === 'POST') return json(publicSeoSnapshot(value), upstream.status);
    if (path === '/api/search' && method === 'POST') return json(publicSearchCreated(value), upstream.status);
    if (path === '/api/search/regions' && method === 'GET') return json(publicSearchRegions(value), upstream.status);
    if (searchSettingsPath) return json(publicSearchSettings(value), upstream.status);
    if (path.startsWith('/api/search/') && method === 'GET') return json(publicSearchSnapshot(value), upstream.status);
    if (path === '/api/providers' && method === 'GET') {
      if (!Array.isArray(value)) throw new Error('Invalid providers');
      return json(value.map(publicProvider), upstream.status);
    }
    if (path === '/api/providers/settings' && method === 'GET') {
      if (!Array.isArray(value)) throw new Error('Invalid settings providers');
      return json(value.map(publicSettingsProvider), upstream.status);
    }
    if (path === '/api/providers/settings/file' && method === 'GET') return json(publicConfigurationFile(value), upstream.status);
    if (path.startsWith('/api/providers/settings/') && method === 'DELETE') return json({ deleted: record(value).deleted === true }, upstream.status);
    if (path.startsWith('/api/providers/settings') && method !== 'DELETE') return json(publicSettingsProvider(value), upstream.status);
    if (path === '/api/form' && method === 'GET') return json(publicForm(value), upstream.status);
    if (path.startsWith('/api/providers/') && method === 'DELETE') return json({ deleted: record(value).deleted === true }, upstream.status);
    if (path.startsWith('/api/providers') && method !== 'DELETE') return json(publicProvider(value), upstream.status);
    if (path === '/api/check') return json(publicCheck(value), upstream.status);
    throw new Error('Unknown response');
  } catch {
    return json({ detail: 'Некорректный ответ Python API' }, 502);
  }
}

export async function proxyCsv(request: Request, path: ApiPath): Promise<Response> {
  if (!validPath(path) || !path.endsWith('/export.csv')) return json({ detail: 'Некорректный прогон' }, 400);
  if (request.method !== 'GET') return json({ detail: 'Недопустимый метод' }, 405);
  let upstream: Response;
  try { upstream = await pythonApi(path); }
  catch { return json({ detail: 'Python API недоступен' }, 502); }
  if (!upstream.ok) {
    if (!/^application\/json(?:\s*;|$)/i.test(upstream.headers.get('content-type') || ''))
      return json({ detail: 'Некорректный ответ Python API' }, 502);
    try {
      const detail = record(await upstream.json()).detail;
      return json({ detail: typeof detail === 'string' ? detail : 'Ошибка Python API' }, upstream.status);
    } catch { return json({ detail: 'Некорректный ответ Python API' }, 502); }
  }
  if (!/^text\/csv(?:\s*;|$)/i.test(upstream.headers.get('content-type') || ''))
    return json({ detail: 'Некорректный ответ Python API' }, 502);
  const declared = upstream.headers.get('content-length');
  if (declared && Number(declared) > MAX_CSV_BYTES) return json({ detail: 'Результат слишком большой' }, 502);
  const body = new Uint8Array(await upstream.arrayBuffer());
  if (body.byteLength > MAX_CSV_BYTES) return json({ detail: 'Результат слишком большой' }, 502);
  const rawFilename = upstream.headers.get('content-disposition') || '';
  const date = /^attachment; filename="ai-serp-results-(\d{4}-\d{2}-\d{2})\.csv"$/.exec(rawFilename)?.[1]
    || new Date().toISOString().slice(0, 10);
  return new Response(body, { status: 200, headers: {
    'content-type': 'text/csv; charset=utf-8', 'cache-control': 'no-store',
    'content-disposition': `attachment; filename="ai-serp-results-${date}.csv"`
  } });
}
