export type ApiPath = '/api/providers' | '/api/check' | `/api/providers/${string}`;

export type PublicProvider = {
  id: string;
  name: string;
  kind: string;
  endpoint: string | null;
  model: string;
  scope?: string;
  configured: boolean;
};

export type CheckRequest = {
  brand: string;
  domain: string;
  prompts: string[];
  provider_ids: string[];
};

export type CheckResult = {
  prompt: string;
  answer: string | null;
  mentioned: boolean | null;
  error: string | null;
};

export type ProviderCheck = {
  provider_id: string;
  provider_name: string;
  summary: { successful: number; failed: number; mentioned: number };
  results: CheckResult[];
};

export type CheckResponse = { brand: string; domain: string; checks: ProviderCheck[] };
