// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Page from '../../routes/+page.svelte';
import type {
  FormConfig, PublicProvider, SeoAgent, SeoAnalysisSnapshot, SeoHistoryPage, SeoMetric, SeoTraceStep
} from '$lib/types';

const form: FormConfig = {
  limits: { max_prompts: 20, max_providers: 5, max_prompt_length: 500, max_brand_length: 200, max_domain_length: 253 },
  new_provider_fields: [], default_provider_ids: ['model-1'], scope_options: []
};

const provider: PublicProvider = {
  id: 'model-1', name: 'Модель', kind: 'custom', endpoint: null, model: 'test-model', configured: true,
  editable_fields: [], can_reset: false, can_delete: true,
  status_label: '', delete_label: '', delete_prompt: '', delete_success: ''
};

const data = { providers: [provider], form, loadError: '' };

const emptyHistory: SeoHistoryPage = { items: [], next_cursor: null };

function snapshot(status: SeoAnalysisSnapshot['status'], overrides: Partial<SeoAnalysisSnapshot> = {}): SeoAnalysisSnapshot {
  return {
    id: 'seo-1', created_at: '2026-09-28T00:00:00Z', updated_at: '2026-09-28T00:00:00Z',
    finished_at: null,
    input: { url: 'https://example.ru', host: 'example.ru', sphere: 'Цветы', seeds: ['а', 'б', 'в'], services: ['с'], connection_ids: ['model-1'] },
    estimate: { search_upper: 23, model_upper: 20, generated_limit: 20, connections: 1 },
    company_name: 'Ромашка', services: ['с'], pages: [],
    stages: [{ stage: 1, status: 'running', error: null, counters: {}, updated_at: '2026-09-28T00:00:00Z' }],
    candidates: [], queries: [], summary: null,
    counters: { queries: 0, search_rows: 0, model_rows: 0, search_errors: 0, model_errors: 0 },
    readiness: {
      report_ready: false, summary_ready: false, queries_ready: false, has_submitted_search_rows: false,
      has_unsubmitted_search_rows: false, has_unfinished_model_rows: false, search_rows: 0, model_rows: 0
    },
    aggregates: { site: { search: {}, ai: {} }, competitors: [], categories: {}, services: {}, counts: {} },
    ...overrides,
    status
  } as unknown as SeoAnalysisSnapshot;
}

function response(value: unknown, ok = true) {
  return { ok, json: async () => value };
}

function metricOf(denominator: number, successes: number, average: number | null = null): SeoMetric {
  return {
    denominator, successes,
    share: denominator > 0 ? Math.round((successes / denominator) * 10_000) / 10_000 : null,
    average_position: average
  };
}

/** A terminal analysis with real aggregates, detail rows and a saved answer. */
function completedSnapshot(overrides: Partial<SeoAnalysisSnapshot> = {}): SeoAnalysisSnapshot {
  return snapshot('completed', {
    finished_at: '2026-09-28T01:00:00Z',
    summary: 'Ромашка упоминается в половине ответов.',
    counters: { queries: 4, search_rows: 4, model_rows: 4, search_errors: 0, model_errors: 0 },
    aggregates: {
      site: {
        search: { overall: metricOf(4, 2, 3.5), branded: metricOf(1, 1, 2), unbranded: metricOf(3, 1, 5) },
        ai: {
          'model-1': {
            name: metricOf(4, 2), host: metricOf(4, 1), combined: metricOf(4, 3),
            branded: { name: metricOf(1, 1), host: metricOf(1, 1), combined: metricOf(1, 1) },
            unbranded: { name: metricOf(3, 1), host: metricOf(3, 0), combined: metricOf(3, 2) }
          }
        }
      },
      competitors: [],
      categories: {
        commercial: { search: metricOf(2, 2, 2), ai: { 'model-1': metricOf(2, 2) } },
        informational: { search: metricOf(1, 0), ai: { 'model-1': metricOf(1, 0) } },
        comparative: { search: metricOf(0, 0), ai: { 'model-1': metricOf(0, 0) } }
      },
      services: { 'Доставка цветов': { search: metricOf(2, 1, 4), ai: { 'model-1': metricOf(2, 1) } } },
      counts: { queries: 4, search_rows: 4, model_rows: 4, search_errors: 0, model_errors: 0 }
    },
    ...overrides
  });
}

const historyItem = {
  id: 'seo-9', created_at: '2026-09-28T00:00:00Z', finished_at: '2026-09-28T01:00:00Z',
  status: 'completed' as const, sphere: 'Цветы', host: 'example.ru', company_name: 'Ромашка',
  counters: { queries: 4, search_rows: 4, model_rows: 4, search_errors: 0, model_errors: 0 }
};

const savedRows = {
  model: [{
    query_index: 0, connection_id: 'model-1', provider_name: 'Модель', status: 'found',
    answer: 'Ромашка рекомендует доставку', name_mentioned: true, host_mentioned: false,
    error: null, query: 'купить цветы', category: 'commercial', service: 'Доставка цветов'
  }],
  search: [{
    query_index: 0, query: 'купить цветы', category: 'commercial', service: 'Доставка цветов',
    status: 'found', site_position: 3, site_url: 'https://example.ru/catalog', error: null
  }]
};

/** The six pending rows the backend answers with for a pre-agent analysis. */
const legacyAgents: SeoAgent[] = ['supervisor', 'site', 'competitors', 'queries', 'checks', 'report']
  .map((agent) => ({ agent, status: 'pending' as const, error: null, updated_at: null }));

/** A live agent run: the supervisor works while the specialists wait. */
const agentRows: SeoAgent[] = [
  { agent: 'supervisor', status: 'running', error: null, updated_at: '2026-09-28T00:05:00Z' },
  { agent: 'site', status: 'done', error: null, updated_at: '2026-09-28T00:03:00Z' },
  { agent: 'competitors', status: 'waiting', error: null, updated_at: '2026-09-28T00:04:00Z' },
  { agent: 'queries', status: 'pending', error: null, updated_at: null },
  { agent: 'checks', status: 'pending', error: null, updated_at: null },
  { agent: 'report', status: 'pending', error: null, updated_at: null }
];

const agentBudget = {
  pages: { used: 2, limit: 20 }, searches: { used: 4, limit: 43 },
  model_answers: { used: 0, limit: 40 }, tool_calls: { used: 5, limit: 120 },
  handoffs: { used: 2, limit: 15 }, seed_searches: 3, model_rows: 0, steps: 7,
  agent_steps: { supervisor: 3, site: 4 }
};

const traceSteps: SeoTraceStep[] = [{
  step_index: 1, agent: 'supervisor', kind: 'handoff', name: 'handoff_to',
  arguments: { agent: 'site' }, result_summary: '{"status":"accepted"}', status: 'done',
  error: null, created_at: '2026-09-28T00:01:00Z'
}];

const traceTail: SeoTraceStep[] = [{
  step_index: 2, agent: 'site', kind: 'tool', name: 'fetch_site',
  arguments: { max_pages: 2 }, result_summary: '{"pages":2}', status: 'done',
  error: null, created_at: '2026-09-28T00:02:00Z'
}];

function stubFetch(handler: (input: string, init?: RequestInit) => unknown) {
  const fetch = vi.fn(async (input: string, init?: RequestInit) => {
    const value = handler(input, init);
    if (value instanceof Error) throw value;
    return value;
  });
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

/** The default upstream: an empty history, a created analysis, and a running snapshot. */
function stubRunning() {
  return stubFetch((input, init) => {
    if (input === '/api/seo/analyses' && !init) return response(emptyHistory);
    if (input === '/api/seo/analyses' && init?.method === 'POST')
      return response({ id: 'seo-1', status: 'running', estimate: { search_upper: 23, model_upper: 20, generated_limit: 20, connections: 1 } });
    if (input === '/api/seo/analyses/seo-1') return response(snapshot('running'));
    throw new Error(`Unexpected request: ${input}`);
  });
}

/** A running agent analysis whose trace has a second page behind a cursor. */
function stubRunningWithAgents() {
  return stubFetch((input, init) => {
    if (input === '/api/seo/analyses' && !init) return response(emptyHistory);
    if (input === '/api/seo/analyses' && init?.method === 'POST')
      return response({ id: 'seo-1', status: 'running', estimate: { search_upper: 43, model_upper: 40, generated_limit: 40, connections: 1 } });
    if (input === '/api/seo/analyses/seo-1')
      return response(snapshot('running', { agents: agentRows, budget: agentBudget, budget_exhausted: false }));
    if (input === '/api/seo/analyses/seo-1/trace') return response({ items: traceSteps, next_cursor: 'cur_1' });
    if (input === '/api/seo/analyses/seo-1/trace?cursor=cur_1') return response({ items: traceTail, next_cursor: null });
    throw new Error(`Unexpected request: ${input}`);
  });
}

async function fillForm() {
  await fireEvent.input(screen.getByRole('textbox', { name: /Адрес главной страницы/ }), { target: { value: 'https://example.ru' } });
  await fireEvent.input(screen.getByRole('textbox', { name: /Сфера бизнеса/ }), { target: { value: 'Цветы' } });
  await fireEvent.input(screen.getByRole('textbox', { name: /Первый ключевой запрос/ }), { target: { value: 'купить цветы' } });
  await fireEvent.input(screen.getByRole('textbox', { name: /Второй ключевой запрос/ }), { target: { value: 'доставка букетов' } });
  await fireEvent.input(screen.getByRole('textbox', { name: /Третий ключевой запрос/ }), { target: { value: 'цветочный магазин' } });
  await fireEvent.input(screen.getByRole('textbox', { name: /Услуги/ }), { target: { value: 'Доставка цветов' } });
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('SEO run page', () => {
  it('shows the SEO form and the empty state instead of the old brand-check form', async () => {
    stubFetch((input) => {
      if (input === '/api/seo/analyses') return response(emptyHistory);
      throw new Error(`Unexpected request: ${input}`);
    });
    render(Page, { props: { data } });
    expect(screen.getByRole('textbox', { name: /Адрес главной страницы/ })).toBeTruthy();
    expect(screen.queryByRole('textbox', { name: /Вопросы клиентов/ })).toBeNull();
    expect(screen.getByText('Пока нет SEO-анализа')).toBeTruthy();
    await waitFor(() => expect(screen.queryByText('Прогон SEO-анализа')).toBeNull());
  });

  it('creates the analysis and shows the run screen immediately', async () => {
    const fetch = stubRunning();
    render(Page, { props: { data } });
    await fillForm();
    await fireEvent.click(screen.getByRole('button', { name: /Запустить анализ/ }));

    await waitFor(() => expect(screen.getByText('Прогон SEO-анализа')).toBeTruthy());
    const post = fetch.mock.calls.find(([path, init]) => path === '/api/seo/analyses' && init?.method === 'POST')!;
    expect(JSON.parse(post[1]!.body as string)).toEqual({
      url: 'https://example.ru',
      sphere: 'Цветы',
      seeds: ['купить цветы', 'доставка букетов', 'цветочный магазин'],
      services: ['Доставка цветов'],
      connection_ids: ['model-1']
    });
  });

  it('validates the form before creating anything', async () => {
    const fetch = stubRunning();
    render(Page, { props: { data } });
    await fireEvent.click(screen.getByRole('button', { name: /Запустить анализ/ }));
    expect(screen.getByRole('alert').textContent).toMatch(/адрес главной страницы/i);
    expect(fetch.mock.calls.filter(([path, init]) => path === '/api/seo/analyses' && init?.method === 'POST')).toHaveLength(0);
  });

  it('polls every 30 seconds and stops on a terminal state', async () => {
    vi.useFakeTimers();
    let polls = 0;
    const fetch = stubFetch((input, init) => {
      if (input === '/api/seo/analyses' && !init) return response(emptyHistory);
      if (input === '/api/seo/analyses' && init?.method === 'POST')
        return response({ id: 'seo-1', status: 'running', estimate: { search_upper: 23, model_upper: 20, generated_limit: 20, connections: 1 } });
      if (input === '/api/seo/analyses/seo-1') {
        polls += 1;
        return response(polls >= 2
          ? snapshot('completed', { finished_at: '2026-09-28T01:00:00Z' })
          : snapshot('running'));
      }
      throw new Error(`Unexpected request: ${input}`);
    });
    render(Page, { props: { data } });
    await fillForm();
    await fireEvent.click(screen.getByRole('button', { name: /Запустить анализ/ }));
    await vi.waitFor(() => expect(screen.getByText('Прогон SEO-анализа')).toBeTruthy());
    expect(polls).toBe(1);

    await vi.advanceTimersByTimeAsync(30_000);
    expect(polls).toBe(2);
    await vi.waitFor(() => expect(screen.getByText(/Анализ завершён/)).toBeTruthy());

    await vi.advanceTimersByTimeAsync(90_000);
    expect(polls).toBe(2);
    expect(fetch.mock.calls.some(([path]) => path === '/api/seo/analyses/seo-1')).toBe(true);
  });

  it('recovers a running analysis from the first history page after a reload', async () => {
    const fetch = stubFetch((input, init) => {
      if (input === '/api/seo/analyses' && !init) return response({
        items: [{
          id: 'seo-1', created_at: '2026-09-28T00:00:00Z', finished_at: null, status: 'running',
          sphere: 'Цветы', host: 'example.ru', company_name: 'Ромашка',
          counters: { queries: 0, search_rows: 0, model_rows: 0, search_errors: 0, model_errors: 0 }
        }],
        next_cursor: null
      });
      if (input === '/api/seo/analyses/seo-1') return response(snapshot('running'));
      throw new Error(`Unexpected request: ${input}`);
    });
    render(Page, { props: { data } });
    await waitFor(() => expect(screen.getByText('Прогон SEO-анализа')).toBeTruthy());
    expect(screen.getByText('Анализ seo-1')).toBeTruthy();
    expect(fetch.mock.calls.filter(([path]) => path === '/api/seo/analyses/seo-1')).toHaveLength(1);
    expect(fetch.mock.calls.some(([path, init]) => path === '/api/seo/analyses' && init?.method === 'POST')).toBe(false);
    // A pre-agent analysis has no steps, so no trace resource is requested for it.
    expect(fetch.mock.calls.filter(([path]) => String(path).endsWith('/trace'))).toHaveLength(0);
  });

  it('loads the agent trace and pages it through the cursor', async () => {
    const fetch = stubRunningWithAgents();
    render(Page, { props: { data } });
    await fillForm();
    await fireEvent.click(screen.getByRole('button', { name: /Запустить анализ/ }));

    await waitFor(() => expect(document.querySelector('[data-agent-panel]')).toBeTruthy());
    // The trace arrives folded: the header counts the steps, the toggle shows them.
    await waitFor(() => expect(document.querySelector('[data-trace-summary]')?.textContent).toContain('1 шаг'));
    expect(document.querySelector('[data-trace-step="1"]')).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'Показать трассу' }));
    await waitFor(() => expect(document.querySelector('[data-trace-step="1"]')?.textContent).toContain('handoff_to'));
    expect(document.querySelector('[data-agent-status="supervisor"]')?.textContent?.trim()).toBe('Выполняется');
    expect(document.querySelector('[data-budget-used="tool_calls"]')?.textContent?.trim()).toBe('5 / 120');

    await fireEvent.click(screen.getByRole('button', { name: 'Показать ещё' }));
    await waitFor(() => expect(document.querySelector('[data-trace-step="2"]')?.textContent).toContain('fetch_site'));
    expect(fetch.mock.calls.some(([path]) => path === '/api/seo/analyses/seo-1/trace?cursor=cur_1')).toBe(true);
  });

  it('keeps the run screen when the agent trace fails', async () => {
    stubFetch((input, init) => {
      if (input === '/api/seo/analyses' && !init) return response(emptyHistory);
      if (input === '/api/seo/analyses' && init?.method === 'POST')
        return response({ id: 'seo-1', status: 'running', estimate: { search_upper: 43, model_upper: 40, generated_limit: 40, connections: 1 } });
      if (input === '/api/seo/analyses/seo-1')
        return response(snapshot('running', { agents: agentRows, budget: agentBudget, budget_exhausted: false }));
      if (input === '/api/seo/analyses/seo-1/trace') return response({ detail: 'Некорректная страница трассы' }, false);
      throw new Error(`Unexpected request: ${input}`);
    });
    render(Page, { props: { data } });
    await fillForm();
    await fireEvent.click(screen.getByRole('button', { name: /Запустить анализ/ }));

    await waitFor(() => expect(screen.getByText('Некорректная страница трассы')).toBeTruthy());
    expect(document.querySelector('[data-agent-panel]')).toBeTruthy();
    expect(screen.getByText('Прогон SEO-анализа')).toBeTruthy();
  });

  it('ignores a terminal analysis found in the history', async () => {
    stubFetch((input) => {
      if (input === '/api/seo/analyses') return response({
        items: [{
          id: 'seo-9', created_at: '2026-09-28T00:00:00Z', finished_at: '2026-09-28T01:00:00Z', status: 'completed',
          sphere: 'Цветы', host: 'example.ru', company_name: 'Ромашка',
          counters: { queries: 12, search_rows: 12, model_rows: 12, search_errors: 0, model_errors: 0 }
        }],
        next_cursor: null
      });
      throw new Error(`Unexpected request: ${input}`);
    });
    render(Page, { props: { data } });
    await waitFor(() => expect(screen.getByText('Пока нет SEO-анализа')).toBeTruthy());
    expect(screen.queryByText('Прогон SEO-анализа')).toBeNull();
  });

  it('sends a bodyless cancel request and stops polling', async () => {
    const fetch = stubFetch((input, init) => {
      if (input === '/api/seo/analyses' && !init) return response(emptyHistory);
      if (input === '/api/seo/analyses' && init?.method === 'POST')
        return response({ id: 'seo-1', status: 'running', estimate: { search_upper: 23, model_upper: 20, generated_limit: 20, connections: 1 } });
      if (input === '/api/seo/analyses/seo-1' && init?.method === 'POST') return response(snapshot('cancelled'));
      if (input === '/api/seo/analyses/seo-1/cancel' && init?.method === 'POST') return response(snapshot('cancelled'));
      if (input === '/api/seo/analyses/seo-1') return response(snapshot('running'));
      throw new Error(`Unexpected request: ${input}`);
    });
    render(Page, { props: { data } });
    await fillForm();
    await fireEvent.click(screen.getByRole('button', { name: /Запустить анализ/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Отменить анализ' })).toBeTruthy());

    await fireEvent.click(screen.getByRole('button', { name: 'Отменить анализ' }));
    await waitFor(() => expect(screen.getByText(/Анализ отменён/)).toBeTruthy());
    const cancel = fetch.mock.calls.find(([path, init]) => path === '/api/seo/analyses/seo-1/cancel' && init?.method === 'POST')!;
    expect(cancel[1]!.body).toBeUndefined();
    expect(document.querySelector('[data-analysis-status]')?.textContent?.trim()).toBe('Отменён');
    expect(screen.queryByRole('button', { name: 'Отменить анализ' })).toBeNull();
  });

  it('shows a safe message when the creation fails', async () => {
    stubFetch((input, init) => {
      if (input === '/api/seo/analyses' && !init) return response(emptyHistory);
      if (input === '/api/seo/analyses' && init?.method === 'POST') return response({ detail: 'Яндекс отключён' }, false);
      throw new Error(`Unexpected request: ${input}`);
    });
    render(Page, { props: { data } });
    await fillForm();
    await fireEvent.click(screen.getByRole('button', { name: /Запустить анализ/ }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Яндекс отключён'));
    expect(screen.getByText('Пока нет SEO-анализа')).toBeTruthy();
  });

  it('keeps the run screen when the status refresh fails', async () => {
    stubFetch((input, init) => {
      if (input === '/api/seo/analyses' && !init) return response(emptyHistory);
      if (input === '/api/seo/analyses' && init?.method === 'POST')
        return response({ id: 'seo-1', status: 'running', estimate: { search_upper: 23, model_upper: 20, generated_limit: 20, connections: 1 } });
      if (input === '/api/seo/analyses/seo-1') return response({ detail: 'Python API недоступен' }, false);
      throw new Error(`Unexpected request: ${input}`);
    });
    render(Page, { props: { data } });
    await fillForm();
    await fireEvent.click(screen.getByRole('button', { name: /Запустить анализ/ }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Python API недоступен'));
  });

  it('opens a saved report from the SEO history without any new paid call', async () => {
    const fetch = stubFetch((input, init) => {
      if (input === '/api/seo/analyses' && !init) return response({ items: [historyItem], next_cursor: null });
      if (input === '/api/seo/analyses/seo-9') return response(completedSnapshot({
        id: 'seo-9', input: { ...completedSnapshot().input, connection_ids: ['model-1'] }
      }));
      if (input === '/api/seo/analyses/seo-9/rows?kind=model') return response({ items: savedRows.model, next_cursor: null });
      if (input === '/api/seo/analyses/seo-9/rows?kind=search') return response({ items: savedRows.search, next_cursor: null });
      throw new Error(`Unexpected request: ${input}`);
    });
    render(Page, { props: { data } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Открыть отчёт' })).toBeTruthy());

    await fireEvent.click(screen.getByRole('button', { name: 'Открыть отчёт' }));
    await waitFor(() => expect(screen.getByText('Отчёт SEO-анализа')).toBeTruthy());

    expect(document.querySelector('[data-metric="site-overall"]')?.textContent?.trim()).toBe('50 %');
    expect(document.querySelector('[data-metric="category-comparative"]')?.textContent?.trim()).toBe('—');
    await waitFor(() => expect(screen.getByText('Ромашка рекомендует доставку')).toBeTruthy());
    expect(screen.getByRole('link', { name: 'https://example.ru/catalog' })).toBeTruthy();
    // Opening a saved analysis must not start another run or reach an external API.
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
    expect(screen.getByText('Прогон SEO-анализа')).toBeTruthy();
  });

  it('loads the next SEO history page through the cursor', async () => {
    stubFetch((input) => {
      if (input === '/api/seo/analyses') return response({ items: [historyItem], next_cursor: 'cursor-1' });
      if (input === '/api/seo/analyses?cursor=cursor-1')
        return response({ items: [{ ...historyItem, id: 'seo-8', sphere: 'Старый прогон' }], next_cursor: null });
      throw new Error(`Unexpected request: ${input}`);
    });
    render(Page, { props: { data } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Показать ещё' })).toBeTruthy());
    await fireEvent.click(screen.getByRole('button', { name: 'Показать ещё' }));
    await waitFor(() => expect(screen.getByText('Старый прогон')).toBeTruthy());
    expect(screen.queryByRole('button', { name: 'Показать ещё' })).toBeNull();
  });

  it('deletes a terminal analysis from the history after a confirmation', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const fetch = stubFetch((input, init) => {
      if (input === '/api/seo/analyses' && !init) return response({ items: [historyItem], next_cursor: null });
      if (input === '/api/seo/analyses/seo-9' && init?.method === 'DELETE') return response(null);
      throw new Error(`Unexpected request: ${input}`);
    });
    render(Page, { props: { data } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Удалить анализ seo-9' })).toBeTruthy());

    await fireEvent.click(screen.getByRole('button', { name: 'Удалить анализ seo-9' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Удалить анализ seo-9' })).toBeNull());

    expect(confirm).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls.some(([path, init]) => path === '/api/seo/analyses/seo-9' && init?.method === 'DELETE')).toBe(true);
    expect(screen.getByText('Сохранённых SEO-анализов пока нет.')).toBeTruthy();
    confirm.mockRestore();
  });

  it('shows history and detail errors without breaking the form', async () => {
    stubFetch((input) => {
      if (input === '/api/seo/analyses') return response({ items: [historyItem], next_cursor: null });
      if (input === '/api/seo/analyses/seo-9') return response(completedSnapshot({ id: 'seo-9' }));
      if (input.startsWith('/api/seo/analyses/seo-9/rows'))
        return response({ detail: 'Некорректный ответ Python API' }, false);
      throw new Error(`Unexpected request: ${input}`);
    });
    render(Page, { props: { data } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Открыть отчёт' })).toBeTruthy());
    await fireEvent.click(screen.getByRole('button', { name: 'Открыть отчёт' }));

    await waitFor(() => expect(screen.getByText('Отчёт SEO-анализа')).toBeTruthy());
    // The metrics from the snapshot stay readable even when the detail page fails.
    expect(document.querySelector('[data-metric="site-overall"]')?.textContent?.trim()).toBe('50 %');
    await waitFor(() => expect(screen.getAllByRole('alert').some((item) => item.textContent?.includes('Некорректный ответ Python API'))).toBe(true));
    expect((screen.getByRole('button', { name: /Запустить анализ/ }) as HTMLButtonElement).disabled).toBe(false);
  });
});
