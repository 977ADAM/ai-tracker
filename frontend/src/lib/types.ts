export type ApiPath = '/api/providers' | '/api/check' | '/api/form' | '/api/providers/settings' | `/api/providers/settings/${string}` | `/api/providers/${string}`;

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
