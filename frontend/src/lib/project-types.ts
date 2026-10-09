export type ProjectQuery = { text: string; category: string | null };
export type Competitor = { brand: string; site_url: string };
export type ProjectInput = {
  name: string;
  brand: string;
  site_url: string;
  competitors: Competitor[];
  queries: ProjectQuery[];
  connection_ids: string[];
  yandex_enabled: boolean;
  yandex_region: number;
};
export type Project = ProjectInput & {
  id: string;
  revision: number;
  created_at: string;
  updated_at: string;
};
export type SentimentCounts = {
  positive: number;
  neutral: number;
  negative: number;
  unknown: number;
};
export type Metric = {
  denominator: number;
  successes: number;
  share: number | null;
  average_position: number | null;
};
export type Visibility = {
  successful: number;
  mentioned: number;
  visibility: number | null;
  sentiment: SentimentCounts;
};
export type Progress = {
  model_done: number;
  model_total: number;
  sentiment_done: number;
  sentiment_total: number;
  search_done: number;
  search_total: number;
};
export type Aggregates = Visibility & {
  planned: number;
  model_errors: number;
  search_errors: number;
  progress: Progress;
  models: (Visibility & {
    connection_id: string;
    name: string;
    planned: number;
    position: Record<string, Metric>;
    citation: Metric;
  })[];
  queries: (ProjectQuery & Visibility)[];
  competitors: (Competitor & Omit<Visibility, 'sentiment'>)[];
  sources: { domain: string; answers: number; citations: number }[];
  search: (Competitor & {
    successful: number;
    found: number;
    visibility: number | null;
    average_position: number | null;
  })[];
};
export type Comparison = {
  visibility_delta: number | null;
  mentioned_delta: number | null;
  sentiment_delta: Omit<SentimentCounts, 'unknown'> | null;
  reason: string | null;
  previous_id?: string;
};
export type ConnectionSnapshot = {
  connection_id: string;
  name: string;
  kind: string;
  endpoint: string;
  model: string;
  answer_mode: string;
  thinking_disabled: boolean;
};
export type Measurement = {
  id: string;
  project_id: string;
  status: string;
  incomplete: boolean;
  created_at: string;
  finished_at: string | null;
  estimate: { model_calls: number; sentiment_calls: number; search_calls: number };
  snapshot: {
    project: ProjectInput;
    connections: ConnectionSnapshot[];
    classifier: { endpoint: string; model: string; prompt_version: string };
    yandex: { region: number; mode: string } | null;
    metric_version: string;
  };
  progress: Progress;
  aggregates: Aggregates;
  comparison: Comparison;
};
export type MeasurementSummary = Pick<
  Measurement,
  'id' | 'status' | 'created_at' | 'finished_at' | 'aggregates' | 'comparison' | 'progress'
>;
export type ProjectSummary = Project & {
  connections: { connection_id: string; name: string }[];
  latest_measurement: MeasurementSummary | null;
  active_measurement: MeasurementSummary | null;
};
export type Page<T> = { items: T[]; cursor: string | null };
export type Citation = {
  url: string;
  title: string | null;
  cited_text: string | null;
  block_index: number;
  order: number;
};
export type ModelRow = {
  query_index: number;
  connection_id: string;
  query: string;
  category: string | null;
  provider_name: string;
  status: string;
  answer: string | null;
  brand_mentioned: boolean;
  domain_mentioned: boolean;
  sentiment_status: string;
  sentiment: { label: string; evidence: string } | null;
  error: string | null;
  sentiment_error: string | null;
  answer_mode: string;
  citations: Citation[];
};
export type SearchRow = {
  query_index: number;
  query: string;
  status: string;
  documents: { url: string; title: string }[];
  error: string | null;
};
export type RowsPage = Page<ModelRow | SearchRow> & { kind: string };
