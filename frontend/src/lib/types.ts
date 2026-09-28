export type ApiPath =
  | '/api/providers' | '/api/check' | '/api/form' | '/api/providers/settings'
  | '/api/search' | '/api/search/regions' | '/api/search/settings' | '/api/search/settings/credentials'
  | '/api/runs' | `/api/runs?cursor=${string}` | `/api/runs/${string}`
  | '/api/seo/settings' | '/api/seo/settings/credentials' | '/api/seo/settings/test'
  | '/api/seo/analyses' | `/api/seo/analyses?cursor=${string}` | `/api/seo/analyses/${string}`
  | `/api/providers/settings/${string}` | `/api/providers/${string}` | `/api/search/${string}`;

export type SettingsModel = { id: string; model: string; name: string };
export type SettingsProvider = {
  id: string;
  name: string;
  kind: string;
  endpoint: string;
  configured: boolean;
  models: SettingsModel[];
};

export type FormConfig = {
  limits: { max_prompts: number; max_providers: number; max_prompt_length: number; max_brand_length: number; max_domain_length: number };
  new_provider_fields: string[];
  default_provider_ids: string[];
  scope_options: { value: string; label: string }[];
};

export type PublicProvider = {
  id: string;
  name: string;
  kind: string;
  endpoint: string | null;
  model: string;
  scope?: string;
  configured: boolean;
  editable_fields: string[];
  can_reset: boolean;
  can_delete: boolean;
  status_label: string;
  delete_label: string;
  delete_prompt: string;
  delete_success: string;
};

export type CheckRequest = {
  brand: string;
  domain: string;
  prompts_text: string;
  provider_ids: string[];
};

export type CheckResult = {
  prompt: string;
  answer: string | null;
  mentioned: boolean | null;
  error: string | null;
  status: 'error' | 'mentioned' | 'absent';
};

export type ProviderCheck = {
  provider_id: string;
  provider_name: string;
  summary: { successful: number; failed: number; mentioned: number };
  results: CheckResult[];
};

export type CheckSummary = { successful: number; failed: number; mentioned: number; mention_percent: number | null; visibility_label: string; mentions_label: string; errors_label: string };
export type CheckRow = CheckResult & { provider_name: string };
export type CheckResponse = { brand: string; domain: string; checks: ProviderCheck[]; summary: CheckSummary; rows: CheckRow[] };

export type SearchRegion = { id: number; name: string };

export type YandexSearchSettings = {
  enabled: boolean;
  folder_id: string | null;
  has_api_key: boolean;
  api_key_source: 'ui' | 'env' | 'none';
  folder_id_source: 'ui' | 'env' | 'none';
};

export type SearchJobStatus = 'pending' | 'done';
export type SearchRowStatus = 'submitting' | 'waiting' | 'found' | 'absent' | 'error';

export type SearchCreated = { id: string; total: number; status: SearchJobStatus };

export type SearchRow = {
  prompt: string;
  region_id: number;
  region_name: string;
  status: SearchRowStatus;
  position: number | null;
  url: string | null;
  error: string | null;
};

export type SearchSummary = { successful: number; found: number; failed: number };

export type SearchSnapshot = {
  id: string;
  domain: string;
  regions: number[];
  total: number;
  completed: number;
  status: SearchJobStatus;
  summary: SearchSummary;
  results: SearchRow[];
};

export type RunStatus = 'pending' | 'done' | 'interrupted';
export type RunCreated = { id: string; status: RunStatus };
export type RunHistoryItem = { id: string; created_at: string; status: RunStatus; prompts: string[] };
export type RunHistoryPage = { items: RunHistoryItem[]; next_cursor: string | null };
export type RunSummaryRow = {
  prompt: string; source: string; language: string; region: string; ai_answer: string;
  site_found: string; position: string; brand_found: string; status: string;
};
export type RunModelRow = {
  provider_id: string; prompt_index: number; provider_name: string; prompt: string;
  status: string; answer: string | null; mentioned: boolean | null; error: string | null;
};
export type RunSearchRow = {
  search_index: number; prompt_index: number; region_index: number; prompt: string;
  region_id: number; region_name: string; status: string; position: number | null;
  url: string | null; error: string | null;
};
export type RunSnapshot = {
  id: string; created_at: string; finished_at: string | null; status: RunStatus;
  brand: string; domain: string; prompts: string[]; provider_ids: string[]; regions: number[];
  models: RunModelRow[]; search: RunSearchRow[]; summary_rows: RunSummaryRow[];
};

/** Per-field origin of a resolved SEO setting: UI override, environment, or unset. */
export type SeoSource = 'ui' | 'env' | 'none';

/** Public projection of the service-LLM settings; the key is only a boolean here. */
export type SeoSettings = {
  endpoint: string | null;
  model: string | null;
  has_api_key: boolean;
  endpoint_source: SeoSource;
  model_source: SeoSource;
  api_key_source: SeoSource;
};

export type SeoSettingsTest = { ok: boolean; model: string | null; error: string | null };

export type SeoAnalysisStatus = 'running' | 'completed' | 'failed' | 'interrupted' | 'cancelled';
export type SeoStageStatus = 'pending' | 'running' | 'done' | 'error' | 'skipped';
export type SeoRowStatus =
  | 'pending' | 'submitting' | 'waiting' | 'found' | 'absent' | 'error' | 'interrupted' | 'cancelled';
export type SeoRowsKind = 'model' | 'search';

export type SeoEstimate = {
  search_upper: number;
  model_upper: number;
  generated_limit: number;
  connections: number;
};

export type SeoAnalysisCreated = { id: string; status: 'running'; estimate: SeoEstimate };

export type SeoAnalysisInput = {
  url: string;
  host: string;
  sphere: string;
  seeds: string[];
  services: string[];
  connection_ids: string[];
};

export type SeoPage = { url: string; title: string };

export type SeoStage = {
  stage: number;
  status: SeoStageStatus;
  error: string | null;
  counters: Record<string, number>;
  updated_at: string;
};

export type SeoCandidate = {
  host: string;
  title: string;
  occurrences: number;
  average_position: number;
  seed_indexes: number[];
  recurring: boolean;
};

export type SeoQueryFlags = {
  mentions_company_name: boolean;
  mentions_company_host: boolean;
  mentions_candidate_host: boolean;
  branded: boolean;
};

export type SeoQuery = {
  index: number;
  text: string;
  category: string;
  service: string | null;
  flags: SeoQueryFlags;
};

export type SeoCounts = {
  queries: number;
  search_rows: number;
  model_rows: number;
  search_errors: number;
  model_errors: number;
};

export type SeoReadiness = {
  report_ready: boolean;
  summary_ready: boolean;
  queries_ready: boolean;
  has_submitted_search_rows: boolean;
  has_unsubmitted_search_rows: boolean;
  has_unfinished_model_rows: boolean;
  search_rows: number;
  model_rows: number;
};

/** One share; `share` and `average_position` are null for an empty denominator. */
export type SeoMetric = {
  denominator: number;
  successes: number;
  share: number | null;
  average_position: number | null;
};

export type SeoSearchMetrics = { overall: SeoMetric; branded: SeoMetric; unbranded: SeoMetric };
export type SeoSiteAiMetrics = { name: SeoMetric; host: SeoMetric; combined: SeoMetric };
export type SeoSiteAiBlock = SeoSiteAiMetrics & {
  branded: SeoSiteAiMetrics;
  unbranded: SeoSiteAiMetrics;
};
export type SeoSiteAggregates = {
  search: SeoSearchMetrics;
  ai: Record<string, SeoSiteAiBlock>;
};
export type SeoCompetitorAggregates = {
  host: string;
  title: string;
  occurrences: number;
  average_position: number;
  seed_indexes: number[];
  search: SeoSearchMetrics;
  ai: Record<string, Record<string, SeoMetric>>;
};
export type SeoCategoryAggregates = { search: SeoMetric; ai: Record<string, SeoMetric> };
export type SeoAggregates = {
  site: SeoSiteAggregates;
  competitors: SeoCompetitorAggregates[];
  categories: Record<string, SeoCategoryAggregates>;
  services: Record<string, SeoCategoryAggregates>;
  counts: SeoCounts;
};

/** Saved analysis without model answers and without Yandex operation IDs. */
export type SeoAnalysisSnapshot = {
  id: string;
  status: SeoAnalysisStatus;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  input: SeoAnalysisInput;
  estimate: SeoEstimate;
  company_name: string;
  services: string[];
  pages: SeoPage[];
  stages: SeoStage[];
  candidates: SeoCandidate[];
  queries: SeoQuery[];
  summary: string | null;
  counters: SeoCounts;
  readiness: SeoReadiness;
  aggregates: SeoAggregates;
};

export type SeoHistoryItem = {
  id: string;
  created_at: string;
  finished_at: string | null;
  status: SeoAnalysisStatus;
  sphere: string;
  host: string;
  company_name: string;
  counters: SeoCounts;
};

export type SeoHistoryPage = { items: SeoHistoryItem[]; next_cursor: string | null };

export type SeoSearchRow = {
  query_index: number;
  query: string | null;
  category: string | null;
  service: string | null;
  status: SeoRowStatus;
  site_position: number | null;
  site_url: string | null;
  error: string | null;
};

/** Model answers are served only by the paginated detail resource. */
export type SeoModelRow = {
  query_index: number;
  connection_id: string;
  provider_name: string;
  status: SeoRowStatus;
  answer: string | null;
  name_mentioned: boolean | null;
  host_mentioned: boolean | null;
  error: string | null;
  query: string | null;
  category: string | null;
  service: string | null;
};

export type SeoRow = SeoSearchRow | SeoModelRow;
export type SeoRowsPage = { items: SeoRow[]; next_cursor: string | null };
