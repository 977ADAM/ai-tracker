export type ApiPath =
  | '/api/providers' | '/api/check' | '/api/form' | '/api/providers/settings'
  | '/api/search' | '/api/search/regions' | '/api/search/settings' | '/api/search/settings/credentials'
  | '/api/runs' | `/api/runs?cursor=${string}` | `/api/runs/${string}`
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
