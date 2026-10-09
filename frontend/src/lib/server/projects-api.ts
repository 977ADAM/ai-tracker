import { apiOrigin, sameOriginRequest } from './python-api';
import type {
  Project,
  ProjectInput,
  ProjectSummary,
  Measurement,
  Aggregates,
  Progress,
  Metric,
  Comparison,
  ModelRow,
  SearchRow,
  Page,
} from '$lib/project-types';

function obj(v: unknown): Record<string, unknown> {
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error('Некорректный ответ API');
  return v as Record<string, unknown>;
}
function str(v: unknown): string {
  if (typeof v !== 'string') throw new Error('Некорректный ответ API');
  return v;
}
function num(v: unknown): number {
  if (typeof v !== 'number' || !Number.isFinite(v)) throw new Error('Некорректный ответ API');
  return v;
}
function bool(v: unknown): boolean {
  if (typeof v !== 'boolean') throw new Error('Некорректный ответ API');
  return v;
}
function nullable(v: unknown): string | null {
  return v == null ? null : str(v);
}
function share(v: unknown): number | null {
  return v == null ? null : num(v);
}
function arr<T>(v: unknown, parse: (v: unknown) => T): T[] {
  if (!Array.isArray(v)) throw new Error('Некорректный ответ API');
  return v.map(parse);
}
const competitor = (v: unknown) => {
  const r = obj(v);
  return { brand: str(r.brand), site_url: str(r.site_url) };
};
const query = (v: unknown) => {
  const r = obj(v);
  return { text: str(r.text), category: nullable(r.category) };
};
function publicInput(v: unknown): ProjectInput {
  const r = obj(v);
  return {
    name: str(r.name),
    brand: str(r.brand),
    site_url: str(r.site_url),
    brand_description: r.brand_description === undefined ? '' : str(r.brand_description),
    brand_aliases: r.brand_aliases === undefined ? [] : arr(r.brand_aliases, str),
    competitors: arr(r.competitors, competitor),
    queries: arr(r.queries, query),
    connection_ids: arr(r.connection_ids, str),
    yandex_enabled: bool(r.yandex_enabled),
    yandex_region: num(r.yandex_region),
  };
}
export function publicProject(v: unknown): Project {
  const r = obj(v);
  return {
    ...publicInput(r),
    id: str(r.id),
    revision: num(r.revision),
    created_at: str(r.created_at),
    updated_at: str(r.updated_at),
  };
}
function sentiment(v: unknown) {
  const r = obj(v);
  return {
    positive: num(r.positive),
    neutral: num(r.neutral),
    negative: num(r.negative),
    unknown: num(r.unknown),
  };
}
function visibility(v: unknown) {
  const r = obj(v);
  return {
    successful: num(r.successful),
    mentioned: num(r.mentioned),
    visibility: share(r.visibility),
    sentiment: sentiment(r.sentiment),
  };
}
function progress(v: unknown): Progress {
  const r = obj(v);
  return {
    model_done: num(r.model_done),
    model_total: num(r.model_total),
    sentiment_done: num(r.sentiment_done),
    sentiment_total: num(r.sentiment_total),
    search_done: num(r.search_done),
    search_total: num(r.search_total),
  };
}
function metric(v: unknown): Metric {
  const r = obj(v);
  return {
    denominator: num(r.denominator),
    successes: num(r.successes),
    share: share(r.share),
    average_position: share(r.average_position),
  };
}
function report(v: unknown): Aggregates {
  const r = obj(v);
  return {
    ...visibility(r),
    planned: num(r.planned),
    model_errors: num(r.model_errors),
    search_errors: num(r.search_errors),
    progress: progress(r.progress),
    models: arr(r.models, (v) => {
      const m = obj(v),
        p = obj(m.position);
      return {
        ...visibility(m),
        connection_id: str(m.connection_id),
        name: str(m.name),
        planned: num(m.planned),
        citation: metric(m.citation),
        position: Object.fromEntries(
          ['first', 'early', 'late', 'absent', 'ahead'].map((k) => [k, metric(p[k])]),
        ),
      };
    }),
    queries: arr(r.queries, (v) => ({ ...query(v), ...visibility(v) })),
    competitors: arr(r.competitors, (v) => {
      const c = obj(v);
      return {
        ...competitor(c),
        successful: num(c.successful),
        mentioned: num(c.mentioned),
        visibility: share(c.visibility),
      };
    }),
    sources: arr(r.sources, (v) => {
      const s = obj(v);
      return { domain: str(s.domain), answers: num(s.answers), citations: num(s.citations) };
    }),
    search: arr(r.search, (v) => {
      const s = obj(v);
      return {
        ...competitor(s),
        successful: num(s.successful),
        found: num(s.found),
        visibility: share(s.visibility),
        average_position: share(s.average_position),
      };
    }),
  };
}
function comparison(v: unknown): Comparison {
  const r = obj(v),
    s = r.sentiment_delta == null ? null : obj(r.sentiment_delta);
  return {
    visibility_delta: share(r.visibility_delta),
    mentioned_delta: share(r.mentioned_delta),
    sentiment_delta: s
      ? { positive: num(s.positive), neutral: num(s.neutral), negative: num(s.negative) }
      : null,
    reason: nullable(r.reason),
    ...(r.previous_id ? { previous_id: str(r.previous_id) } : {}),
  };
}
export function publicMeasurement(v: unknown): Measurement {
  const r = obj(v),
    s = obj(r.snapshot),
    c = obj(s.classifier),
    y = s.yandex == null ? null : obj(s.yandex),
    e = obj(r.estimate);
  return {
    id: str(r.id),
    project_id: str(r.project_id),
    status: str(r.status),
    incomplete: bool(r.incomplete),
    created_at: str(r.created_at),
    finished_at: nullable(r.finished_at),
    estimate: {
      model_calls: num(e.model_calls),
      sentiment_calls: num(e.sentiment_calls),
      search_calls: num(e.search_calls),
    },
    snapshot: {
      project: publicInput(s.project),
      connections: arr(s.connections, (v) => {
        const c = obj(v);
        return {
          connection_id: str(c.connection_id),
          name: str(c.name),
          kind: str(c.kind),
          endpoint: str(c.endpoint),
          model: str(c.model),
          answer_mode: str(c.answer_mode),
          thinking_disabled: bool(c.thinking_disabled),
        };
      }),
      classifier: {
        endpoint: str(c.endpoint),
        model: str(c.model),
        prompt_version: str(c.prompt_version),
      },
      yandex: y ? { region: num(y.region), mode: str(y.mode) } : null,
      metric_version: str(s.metric_version),
    },
    progress: progress(r.progress),
    aggregates: report(r.aggregates),
    comparison: comparison(r.comparison),
  };
}
export function publicProjectSummary(v: unknown): ProjectSummary {
  const r = obj(v);
  return {
    ...publicProject(r),
    connections: arr(r.connections, (v) => {
      const c = obj(v);
      return { connection_id: str(c.connection_id), name: str(c.name) };
    }),
    latest_measurement:
      r.latest_measurement == null ? null : publicMeasurement(r.latest_measurement),
    active_measurement:
      r.active_measurement == null ? null : publicMeasurement(r.active_measurement),
  };
}
function page<T>(v: unknown, parse: (v: unknown) => T): Page<T> {
  const r = obj(v);
  return { items: arr(r.items, parse), cursor: nullable(r.cursor) };
}
function safeUrl(v: unknown): string {
  const s = str(v),
    u = new URL(s);
  if (!['http:', 'https:'].includes(u.protocol) || u.username || u.password)
    throw new Error('Некорректный URL');
  return s;
}
function modelRow(v: unknown): ModelRow {
  const r = obj(v),
    s = r.sentiment == null ? null : obj(r.sentiment);
  return {
    query_index: num(r.query_index),
    connection_id: str(r.connection_id),
    query: str(r.query),
    category: nullable(r.category),
    provider_name: str(r.provider_name),
    status: str(r.status),
    answer: nullable(r.answer),
    brand_mentioned: bool(r.brand_mentioned),
    domain_mentioned: bool(r.domain_mentioned),
    sentiment_status: str(r.sentiment_status),
    sentiment: s ? { label: str(s.label), evidence: str(s.evidence) } : null,
    error: nullable(r.error),
    sentiment_error: nullable(r.sentiment_error),
    answer_mode: str(r.answer_mode),
    citations: arr(r.citations, (v) => {
      const c = obj(v);
      return {
        url: safeUrl(c.url),
        title: nullable(c.title),
        cited_text: nullable(c.cited_text),
        block_index: num(c.block_index),
        order: num(c.order),
      };
    }),
  };
}
function searchRow(v: unknown): SearchRow {
  const r = obj(v);
  return {
    query_index: num(r.query_index),
    query: str(r.query),
    status: str(r.status),
    error: nullable(r.error),
    documents: arr(r.documents, (v) => {
      const d = obj(v);
      return { url: safeUrl(d.url), title: str(d.title) };
    }),
  };
}
export function projectPath(id?: string): string {
  if (id != null && !/^[a-zA-Z0-9_-]{1,100}$/.test(id)) throw new Error('Некорректный проект');
  return '/api/projects' + (id ? '/' + id : '');
}
const pathPattern =
  /^\/api\/(?:projects(?:\/[a-zA-Z0-9_-]{1,100}(?:\/(?:measurements|generate))?)?|measurements\/[a-zA-Z0-9_-]{1,100}(?:\/rows|\/cancel)?)(?:\?[^#]*)?$/;
function validatePath(path: string, method: string) {
  if (!pathPattern.test(path)) throw new Error('Некорректный путь');
  const u = new URL(path, 'http://local'),
    keys = [...u.searchParams.keys()];
  if (
    keys.some((k) => !['cursor', 'kind', 'limit'].includes(k)) ||
    keys.some((k) => u.searchParams.getAll(k).length !== 1)
  )
    throw new Error('Некорректная страница');
  const row = u.pathname.endsWith('/rows');
  if (
    u.searchParams.has('limit') &&
    (!/^[1-9]\d?$|^100$/.test(u.searchParams.get('limit')!) || method !== 'GET')
  )
    throw new Error('Некорректный размер страницы');
  if (
    u.searchParams.has('kind') &&
    (!row || !['model', 'search'].includes(u.searchParams.get('kind')!))
  )
    throw new Error('Некорректная детализация');
  if ((u.searchParams.get('cursor') || '').length > 1000) throw new Error('Некорректный курсор');
  const collection = u.pathname === '/api/projects';
  const history = u.pathname.endsWith('/measurements');
  const cancel = u.pathname.endsWith('/cancel');
  const generate = u.pathname.endsWith('/generate');
  const allowed = row
    ? ['GET']
    : cancel || generate
      ? ['POST']
      : history || collection
        ? ['GET', 'POST']
        : u.pathname.startsWith('/api/projects/')
          ? ['GET', 'PUT', 'DELETE']
          : ['GET', 'DELETE'];
  if (!allowed.includes(method) || (method !== 'GET' && u.search))
    throw new Error('Недопустимый метод');
}
function projection(path: string, value: unknown, method: string): unknown {
  const u = new URL(path, 'http://local');
  if (u.pathname.endsWith('/generate')) {
    const r = obj(value),
      p = obj(r.proposal);
    const kind = str(r.kind);
    if (kind === 'description')
      return {
        kind,
        proposal: {
          brand_description: str(p.brand_description),
          brand_aliases: arr(p.brand_aliases, str),
        },
      };
    if (kind === 'queries') return { kind, proposal: { queries: arr(p.queries, query) } };
    if (kind === 'competitors')
      return { kind, proposal: { competitors: arr(p.competitors, competitor) } };
    throw new Error('Некорректное предложение');
  }
  if (u.pathname.endsWith('/cancel')) return publicMeasurement(value);
  if (u.pathname.endsWith('/rows')) {
    const r = obj(value);
    return {
      ...page<ModelRow | SearchRow>(
        r,
        u.searchParams.get('kind') === 'search' ? searchRow : modelRow,
      ),
      kind: str(r.kind),
    };
  }
  if (u.pathname.endsWith('/measurements')) {
    if (method === 'GET') return page(value, publicMeasurement);
    const r = obj(value),
      e = obj(r.estimate);
    return {
      id: str(r.id),
      project_id: str(r.project_id),
      status: str(r.status),
      estimate: {
        model_calls: num(e.model_calls),
        sentiment_calls: num(e.sentiment_calls),
        search_calls: num(e.search_calls),
      },
    };
  }
  if (u.pathname === '/api/projects')
    return method === 'GET' ? page(value, publicProjectSummary) : publicProject(value);
  return u.pathname.startsWith('/api/projects/') ? publicProject(value) : publicMeasurement(value);
}
async function upstream(path: string, init: RequestInit = {}) {
  const response = await fetch(apiOrigin() + path, {
    ...init,
    redirect: 'error',
    signal: AbortSignal.timeout(path.endsWith('/generate') ? 125000 : 10000),
  });
  if (response.status === 204) return { response, value: null };
  const text = await response.text();
  if (new TextEncoder().encode(text).length > 5 * 1024 * 1024)
    throw new Error('Ответ слишком большой');
  return { response, value: JSON.parse(text) as unknown };
}
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
export async function proxyProjects(
  request: Request,
  path: string,
  method: string,
): Promise<Response> {
  try {
    validatePath(path, method);
  } catch {
    return json({ detail: 'Некорректный запрос' }, 400);
  }
  let body: string | undefined;
  if (method !== 'GET') {
    if (!sameOriginRequest(request)) return json({ detail: 'Недопустимый источник запроса' }, 403);
    const bodyless =
      method === 'DELETE' ||
      (method === 'POST' && (path.endsWith('/measurements') || path.endsWith('/cancel')));
    if (Number(request.headers.get('content-length')) > 65536)
      return json({ detail: 'Запрос слишком большой' }, 413);
    body = await request.text();
    if (new TextEncoder().encode(body).length > 65536)
      return json({ detail: 'Запрос слишком большой' }, 413);
    if (bodyless) {
      if (body) return json({ detail: 'Запрос не принимает тело' }, 400);
      body = undefined;
    } else {
      if (!/^application\/json(?:\s*;|$)/i.test(request.headers.get('content-type') || ''))
        return json({ detail: 'Ожидается JSON' }, 415);
      try {
        JSON.parse(body);
      } catch {
        return json({ detail: 'Некорректный JSON' }, 400);
      }
    }
  }
  try {
    const { response, value } = await upstream(path, {
      method,
      body,
      headers: body ? { 'content-type': 'application/json' } : undefined,
    });
    if (response.status === 204) return new Response(null, { status: 204 });
    if (!response.ok) {
      const r = obj(value);
      return json(
        { detail: typeof r.detail === 'string' ? r.detail : 'Не удалось выполнить запрос' },
        response.status,
      );
    }
    return json(projection(path, value, method), response.status);
  } catch {
    return json({ detail: 'API проекта недоступен' }, 502);
  }
}
export async function getProjectsResource<T>(path: string, parse: (v: unknown) => T): Promise<T> {
  validatePath(path, 'GET');
  const { response, value } = await upstream(path);
  if (!response.ok) throw new Error('Не удалось загрузить проект');
  return parse(value);
}
export async function loadProjectsData(cursor: string | null = null) {
  try {
    const projects = await getProjectsResource(
      '/api/projects' + (cursor ? '?cursor=' + encodeURIComponent(cursor) : ''),
      (v) => page(v, publicProjectSummary),
    );
    return { projects, projectsError: '' };
  } catch {
    return {
      projects: { items: [] as ProjectSummary[], cursor: null },
      projectsError: 'Не удалось загрузить проекты. Проверьте Python API.',
    };
  }
}
export async function loadProjectData(id: string) {
  const project = await getProjectsResource(projectPath(id), publicProject);
  const history = await getProjectsResource(projectPath(id) + '/measurements', (v) =>
    page(v, publicMeasurement),
  );
  return { project, history };
}
