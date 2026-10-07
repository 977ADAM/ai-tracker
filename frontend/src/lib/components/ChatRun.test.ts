// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import ChatRun from './ChatRun.svelte';
import type { SeoAnalysisSnapshot, SeoSearchRow, SeoStage, SeoTraceStep } from '$lib/types';

function stage(stageNumber: number, status: SeoStage['status'], error: string | null = null): SeoStage {
  return { stage: stageNumber, status, error, counters: {}, updated_at: '2026-10-07T10:00:00Z' };
}

/** The six pending rows the backend answers with for a pre-agent analysis. */
const legacyAgents = ['supervisor', 'site', 'competitors', 'queries', 'checks', 'report']
  .map((agent) => ({ agent, status: 'pending' as const, error: null, updated_at: null }));

function snapshot(overrides: Partial<SeoAnalysisSnapshot> = {}): SeoAnalysisSnapshot {
  return {
    id: 'a-1', status: 'running', created_at: '2026-10-07T10:00:00Z', updated_at: '2026-10-07T10:00:00Z',
    finished_at: null,
    input: {
      url: 'https://example.ru', host: 'example.ru', sphere: 'Доставка цветов',
      seeds: ['купить цветы', 'доставка букетов', 'заказать розы'], services: ['Сборка букетов'],
      connection_ids: ['model-1']
    },
    estimate: { search_upper: 23, model_upper: 40, generated_limit: 20, connections: 1 },
    company_name: 'Ромашка', services: ['Сборка букетов'], pages: [],
    stages: [stage(1, 'done'), stage(2, 'running')],
    agents: legacyAgents,
    candidates: [], queries: [], summary: null, conclusions: null,
    counters: { queries: 12, search_rows: 4, model_rows: 6, search_errors: 1, model_errors: 2 },
    readiness: {
      report_ready: false, summary_ready: false, queries_ready: true, has_submitted_search_rows: true,
      has_unsubmitted_search_rows: true, has_unfinished_model_rows: true, search_rows: 12, model_rows: 24
    },
    aggregates: { site: { search: {}, ai: {} }, competitors: [], categories: {}, services: {}, counts: {} },
    ...overrides
  } as unknown as SeoAnalysisSnapshot;
}

function searchRow(query: string): SeoSearchRow {
  return {
    query_index: 1, query, category: null, service: null, status: 'found',
    site_position: 3, site_url: 'https://example.ru/page', error: null
  };
}

function traceStep(name: string): SeoTraceStep {
  return {
    step_index: 1, agent: 'supervisor', kind: 'tool', name, arguments: { url: 'https://example.ru' },
    result_summary: 'Готово', status: 'done', error: null, created_at: '2026-10-07T10:00:00Z'
  };
}

function runProps(overrides: Record<string, unknown> = {}) {
  return {
    snapshot: snapshot(),
    analysisId: 'a-1',
    onCancel: vi.fn(),
    onMoreRows: vi.fn(),
    onMoreTrace: vi.fn(),
    onOpenReport: vi.fn(),
    ...overrides
  };
}

describe('ChatRun', () => {
  it('shows progress while the run is going', () => {
    render(ChatRun, { props: runProps({ snapshot: snapshot() }) });
    expect(screen.getByText('Прогон SEO-анализа')).toBeTruthy();
    expect(screen.queryByText('Отчёт SEO-анализа')).toBeNull();
  });

  it('collapses the report until it is opened', async () => {
    render(ChatRun, { props: runProps({ snapshot: snapshot({ status: 'completed' }) }) });
    expect(screen.queryByText('Отчёт SEO-анализа')).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: /открыть отчёт/i }));
    expect(screen.getByText('Отчёт SEO-анализа')).toBeTruthy();
  });

  it('hides the report again on a second click', async () => {
    const { container } = render(ChatRun, { props: runProps({ snapshot: snapshot({ status: 'completed' }) }) });
    const toggle = screen.getByRole('button', { name: /открыть отчёт/i });
    await fireEvent.click(toggle);
    expect(container.querySelector('[data-seo-report]')).not.toBeNull();

    await fireEvent.click(screen.getByRole('button', { name: /скрыть отчёт/i }));
    expect(container.querySelector('[data-seo-report]')).toBeNull();
    expect(screen.queryByText('Отчёт SEO-анализа')).toBeNull();
  });

  it('asks the parent for the report only when the report is opened', async () => {
    const onOpenReport = vi.fn();
    render(ChatRun, { props: runProps({ snapshot: snapshot({ status: 'completed' }), onOpenReport }) });
    expect(onOpenReport).not.toHaveBeenCalled();

    await fireEvent.click(screen.getByRole('button', { name: /открыть отчёт/i }));
    expect(onOpenReport).toHaveBeenCalledTimes(1);

    await fireEvent.click(screen.getByRole('button', { name: /скрыть отчёт/i }));
    await fireEvent.click(screen.getByRole('button', { name: /открыть отчёт/i }));
    expect(onOpenReport).toHaveBeenCalledTimes(2);
  });

  it('cancels the run from the progress card', async () => {
    const onCancel = vi.fn();
    render(ChatRun, { props: runProps({ snapshot: snapshot(), onCancel }) });
    await fireEvent.click(screen.getByRole('button', { name: 'Отменить анализ' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('shows the trace of the run', async () => {
    const { container } = render(ChatRun, {
      props: runProps({ traces: { steps: [traceStep('site_fetch')], cursor: null, loading: false, error: '' } })
    });
    expect(container.querySelector('[data-trace-feed]')).not.toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: /показать трассу/i }));
    expect(screen.getByText('site_fetch')).toBeTruthy();
  });

  it('names every terminal state', () => {
    for (const [status, label, note] of [
      ['completed', 'Завершён', /Анализ завершён/],
      ['failed', 'Ошибка', /ошибки этапа/],
      ['interrupted', 'Прерван', /прерван перезапуском/],
      ['cancelled', 'Отменён', /Анализ отменён/]
    ] as const) {
      const view = render(ChatRun, { props: runProps({ snapshot: snapshot({ status }) }) });
      expect(view.container.querySelector('[data-run-status]')?.textContent?.trim()).toBe(label);
      expect(screen.getByText(note)).toBeTruthy();
      expect(screen.queryByText('Прогон SEO-анализа')).toBeTruthy();
      expect(screen.getByRole('button', { name: /открыть отчёт/i })).toBeTruthy();
      view.unmount();
    }
  });

  it('shows a loading placeholder until the snapshot arrives', () => {
    const { container } = render(ChatRun, { props: runProps({ snapshot: null }) });
    expect(screen.getByText('Загружаем прогон…')).toBeTruthy();
    expect(container.querySelector('[data-chat-run]')).not.toBeNull();
    expect(screen.queryByText('Прогон SEO-анализа')).toBeNull();
    expect(screen.queryByText('Отчёт SEO-анализа')).toBeNull();
  });

  it('renders the saved rows inside the opened report', async () => {
    render(ChatRun, {
      props: runProps({
        snapshot: snapshot({ status: 'completed' }),
        rows: { model: [], search: [searchRow('купить цветы в Москве')] }
      })
    });
    await fireEvent.click(screen.getByRole('button', { name: /открыть отчёт/i }));
    expect(screen.getByText('купить цветы в Москве')).toBeTruthy();
  });
});
