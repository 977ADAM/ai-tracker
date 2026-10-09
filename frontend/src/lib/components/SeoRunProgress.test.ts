// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import SeoRunProgress from './SeoRunProgress.svelte';
import type { SeoAgent, SeoAnalysisSnapshot, SeoStage, SeoTraceStep } from '$lib/types';

function stage(
  stageNumber: number,
  status: SeoStage['status'],
  error: string | null = null,
): SeoStage {
  return { stage: stageNumber, status, error, counters: {}, updated_at: '2026-09-28T00:00:00Z' };
}

/** The six pending rows the backend answers with for a pre-agent analysis. */
const legacyAgents: SeoAgent[] = [
  'supervisor',
  'site',
  'competitors',
  'queries',
  'checks',
  'report',
].map((agent) => ({ agent, status: 'pending' as const, error: null, updated_at: null }));

const agentRows: SeoAgent[] = [
  { agent: 'supervisor', status: 'running', error: null, updated_at: '2026-09-28T00:05:00Z' },
  { agent: 'site', status: 'done', error: null, updated_at: '2026-09-28T00:03:00Z' },
  { agent: 'competitors', status: 'waiting', error: null, updated_at: '2026-09-28T00:04:00Z' },
  { agent: 'queries', status: 'pending', error: null, updated_at: null },
  { agent: 'checks', status: 'pending', error: null, updated_at: null },
  { agent: 'report', status: 'pending', error: null, updated_at: null },
];

const budget = {
  pages: { used: 2, limit: 20 },
  searches: { used: 4, limit: 43 },
  model_answers: { used: 0, limit: 40 },
  tool_calls: { used: 5, limit: 120 },
  handoffs: { used: 2, limit: 15 },
  seed_searches: 3,
  model_rows: 0,
  steps: 7,
  agent_steps: { supervisor: 3, site: 4 },
};

function snapshot(overrides: Partial<SeoAnalysisSnapshot> = {}): SeoAnalysisSnapshot {
  return {
    id: 'seo-1',
    status: 'running',
    created_at: '2026-09-28T00:00:00Z',
    updated_at: '2026-09-28T00:00:00Z',
    finished_at: null,
    input: {
      url: 'https://example.ru',
      host: 'example.ru',
      sphere: 'Цветы',
      seeds: ['а', 'б', 'в'],
      services: ['с'],
      connection_ids: ['model-1', 'model-2'],
    },
    estimate: { search_upper: 23, model_upper: 40, generated_limit: 20, connections: 2 },
    company_name: 'Ромашка',
    services: ['с'],
    pages: [],
    stages: [
      stage(1, 'done'),
      stage(2, 'error', 'Ключевые выдачи недоступны'),
      stage(3, 'running'),
    ],
    candidates: [],
    queries: [],
    counters: { queries: 12, search_rows: 4, model_rows: 6, search_errors: 1, model_errors: 2 },
    readiness: {
      report_ready: false,
      summary_ready: false,
      queries_ready: true,
      has_submitted_search_rows: true,
      has_unsubmitted_search_rows: true,
      has_unfinished_model_rows: true,
      search_rows: 12,
      model_rows: 24,
    },
    aggregates: {
      site: { search: {}, ai: {} },
      competitors: [],
      categories: {},
      services: {},
      sources: [],
      counts: {},
    },
    ...overrides,
  } as unknown as SeoAnalysisSnapshot;
}

describe('SeoRunProgress', () => {
  it('renders the six named stages with their saved statuses', () => {
    render(SeoRunProgress, { props: { snapshot: snapshot(), onCancel: vi.fn() } });
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(6);
    expect(items[0].textContent).toContain('Анализ сайта');
    expect(items[4].textContent).toContain('Анализ результатов');
    expect(items[5].textContent).toContain('Отчёт');
    expect(items[0].textContent).toContain('Готово');
    expect(items[2].textContent).toContain('Выполняется');
    expect(items[5].textContent).toContain('Ожидает');
  });

  it('shows the analysis state, the counters and the partial source errors', () => {
    render(SeoRunProgress, { props: { snapshot: snapshot(), onCancel: vi.fn() } });
    expect(document.querySelector('[data-analysis-status]')?.textContent?.trim()).toBe(
      'Выполняется',
    );
    expect(screen.getByLabelText('Счётчики строк').textContent).toContain('Запросы: 12');
    expect(screen.getByLabelText('Счётчики строк').textContent).toContain('ошибок 1');
    expect(screen.getByLabelText('Счётчики строк').textContent).toContain('ошибок 2');

    const error = screen.getByRole('alert');
    expect(error.textContent).toContain('Поиск конкурентов');
    expect(error.textContent).toContain('Ключевые выдачи недоступны');
  });

  it('shows the actual K and K x M once the queries are generated', () => {
    render(SeoRunProgress, { props: { snapshot: snapshot(), onCancel: vi.fn() } });
    const estimate = screen.getByLabelText('Фактическая оценка вызовов').textContent ?? '';
    expect(estimate).toContain('12 запросов');
    expect(estimate).toContain('15 поисковых');
    expect(estimate).toContain('не больше 5 модельных за прогон');
  });

  it('hides the actual estimate until the queries exist', () => {
    render(SeoRunProgress, {
      props: {
        snapshot: snapshot({
          readiness: { ...snapshot().readiness, queries_ready: false },
          counters: {
            queries: 0,
            search_rows: 0,
            model_rows: 0,
            search_errors: 0,
            model_errors: 0,
          },
          stages: [stage(1, 'running')],
        }),
        onCancel: vi.fn(),
      },
    });
    expect(screen.queryByLabelText('Фактическая оценка вызовов')).toBeNull();
  });

  it('offers the cancel action only while the analysis runs', async () => {
    const onCancel = vi.fn();
    const view = render(SeoRunProgress, { props: { snapshot: snapshot(), onCancel } });
    await fireEvent.click(screen.getByRole('button', { name: 'Отменить анализ' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    view.unmount();
    render(SeoRunProgress, { props: { snapshot: snapshot({ status: 'completed' }), onCancel } });
    expect(screen.queryByRole('button', { name: 'Отменить анализ' })).toBeNull();
    expect(screen.getByText(/Анализ завершён/)).toBeTruthy();
  });

  it('disables the cancel button while a cancellation is in flight', () => {
    render(SeoRunProgress, {
      props: { snapshot: snapshot(), cancelling: true, onCancel: vi.fn() },
    });
    expect((screen.getByRole('button', { name: /Отменяем/ }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it('names every terminal state', () => {
    for (const [status, label, note] of [
      ['completed', 'Завершён', /Анализ завершён/],
      ['failed', 'Ошибка', /ошибки этапа/],
      ['interrupted', 'Прерван', /прерван перезапуском/],
      ['cancelled', 'Отменён', /отменён/],
    ] as const) {
      const view = render(SeoRunProgress, {
        props: { snapshot: snapshot({ status }), onCancel: vi.fn() },
      });
      expect(document.querySelector('[data-analysis-status]')?.textContent?.trim()).toBe(label);
      expect(screen.getByText(note)).toBeTruthy();
      view.unmount();
    }
  });

  it('keeps the six-stage list for a pre-agent analysis with six pending agents', () => {
    render(SeoRunProgress, {
      props: {
        snapshot: snapshot({ agents: legacyAgents, budget: budget, budget_exhausted: false }),
        onCancel: vi.fn(),
      },
    });
    expect(document.querySelector('[data-agent-panel]')).toBeNull();
    const stages = document.querySelectorAll('[data-stage]');
    expect(stages).toHaveLength(6);
    expect(stages[0].textContent).toContain('Анализ сайта');
    expect(stages[0].textContent).toContain('Готово');
    expect(stages[2].textContent).toContain('Выполняется');
    expect(document.querySelector('[data-stage="2"]')?.textContent).toContain(
      'Ключевые выдачи недоступны',
    );
  });

  it('shows the agent panel and the budget once any agent has real state', () => {
    render(SeoRunProgress, {
      props: {
        snapshot: snapshot({ agents: agentRows, budget: budget, budget_exhausted: false }),
        onCancel: vi.fn(),
      },
    });
    expect(document.querySelector('[data-agent-panel]')).toBeTruthy();
    expect(document.querySelectorAll('[data-stage]')).toHaveLength(0);
    expect(document.querySelector('[data-agent-status="supervisor"]')?.textContent?.trim()).toBe(
      'Выполняется',
    );
    expect(document.querySelector('[data-budget-used="tool_calls"]')?.textContent?.trim()).toBe(
      '5 / 120',
    );
  });

  it('renders the trace feed and loads the next trace page through the cursor', async () => {
    const onTraceMore = vi.fn();
    const trace: SeoTraceStep[] = [
      {
        step_index: 1,
        agent: 'supervisor',
        kind: 'handoff',
        name: 'handoff_to',
        arguments: { agent: 'site' },
        result_summary: '{"status":"accepted"}',
        status: 'done',
        error: null,
        created_at: '2026-09-28T00:01:00Z',
      },
    ];
    render(SeoRunProgress, {
      props: {
        snapshot: snapshot({ agents: legacyAgents }),
        trace,
        traceCursor: 'cur_1',
        onTraceMore,
        onCancel: vi.fn(),
      },
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Показать трассу' }));
    expect(document.querySelector('[data-trace-step="1"]')?.textContent).toContain('handoff_to');

    await fireEvent.click(screen.getByRole('button', { name: 'Показать ещё' }));
    expect(onTraceMore).toHaveBeenCalledTimes(1);
  });

  it('shows the empty trace state and a safe trace error', () => {
    render(SeoRunProgress, {
      props: {
        snapshot: snapshot({ agents: legacyAgents }),
        traceError: 'Не удалось загрузить трассу',
        onCancel: vi.fn(),
      },
    });
    expect(screen.getByText('Шаги трассы пока не записаны.')).toBeTruthy();
    expect(screen.getByText('Не удалось загрузить трассу')).toBeTruthy();
  });
});
