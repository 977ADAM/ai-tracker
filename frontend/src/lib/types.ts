export type ApiPath =
  | '/api/config'
  | '/api/providers'
  | '/api/providers/settings'
  | '/api/search/settings'
  | '/api/search/settings/credentials'
  | '/api/seo/settings'
  | '/api/seo/settings/credentials'
  | '/api/seo/settings/test'
  | `/api/providers/settings/${string}`
  | `/api/providers/${string}`;

export type SettingsModel = { id: string; model: string; name: string };
export type SettingsProvider = {
  id: string;
  name: string;
  kind: string;
  endpoint: string;
  configured: boolean;
  models: SettingsModel[];
};

export type PublicProvider = {
  answer_mode?: string;
  id: string;
  name: string;
  kind: string;
  endpoint: string | null;
  model: string;
  configured: boolean;
  editable_fields: string[];
  can_reset: boolean;
  can_delete: boolean;
  status_label: string;
  delete_label: string;
  delete_prompt: string;
  delete_success: string;
};

export type YandexSearchSettings = {
  enabled: boolean;
  folder_id: string | null;
  has_api_key: boolean;
  api_key_source: 'ui' | 'env' | 'none';
  folder_id_source: 'ui' | 'env' | 'none';
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

/** The availability probe: whether one chat completion succeeded. */
export type SeoSettingsTest = {
  ok: boolean;
  model: string | null;
  error: string | null;
};
