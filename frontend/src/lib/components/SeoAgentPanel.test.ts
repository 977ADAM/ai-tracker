// @vitest-environment jsdom
import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import SeoAgentPanel from './SeoAgentPanel.svelte';
import type { SeoAgent, SeoAnalysisSnapshot } from '$lib/types';

const agents: SeoAgent[] = [
  { agent: 'supervisor', status: 'done', error: null, updated_at: '2026-09-28T00:10:00Z' },
  { agent: 'site', status: 'error', error: 'Сайт недоступен', updated_at: '2026-09-28T00:03:00Z' },
  { agent: 'competitors', status: 'waiting', error: null, updated_at: '2026-09-28T00:05:00Z' },
  { agent: 'queries', status: 'running', error: null, updated_at: '2026-09-28T00:06:00Z' },
  { agent: 'checks', status: 'skipped', error: null, updated_at: '2026-09-28T00:07:00Z' },
  { agent: 'report', status: 'pending', error: null, updated_at: null }
];

function snapshot(overrides: Partial<SeoAnalysisSnapshot> = {}): SeoAnalysisSnapshot {
  return {
    id: 'seo-1', status: 'running', created_at: '2026-09-28T00:00:00Z', updated_at: '2026-09-28T00:10:00Z',
    finished_at: null,
    input: { url: 'https://example.ru', host: 'example.ru', sphere: 'Цветы', seeds: ['а', 'б', 'в'], services: ['с'], connection_ids: ['model-1'] },
    estimate: { search_upper: 43, model_upper: 40, generated_limit: 40, connections: 1 },
    company_name: 'Ромашка', services: ['с'], pages: [], stages: [],
    agents,
    budget: {
      pages: { used: 3, limit: 20 }, searches: { used: 5, limit: 43 },
      model_answers: { used: 4, limit: 40 }, tool_calls: { used: 9, limit: 120 },
      handoffs: { used: 5, limit: 15 }, seed_searches: 3, model_rows: 4, steps: 12,
      agent_steps: { supervisor: 4, site: 3 }
    },
    budget_exhausted: false,
    candidates: [], queries: [], summary: null, conclusions: null,
    counters: { queries: 4, search_rows: 4, model_rows: 4, search_errors: 0, model_errors: 0 },
    readiness: {
      report_ready: false, summary_ready: false, queries_ready: true, has_submitted_search_rows: true,
      has_unsubmitted_search_rows: false, has_unfinished_model_rows: false, search_rows: 4, model_rows: 4
    },
    aggregates: { site: { search: {} as never, ai: {} }, competitors: [], categories: {}, services: {}, counts: {} as never },
    ...overrides
  } as unknown as SeoAnalysisSnapshot;
}

function agent(id: string): HTMLElement {
  return document.querySelector(`[data-agent="${id}"]`) as HTMLElement;
}

function status(id: string): string {
  return document.querySelector(`[data-agent-status="${id}"]`)?.textContent?.trim() ?? '';
}

function budget(key: string): string {
  return document.querySelector(`[data-budget-used="${key}"]`)?.textContent?.trim() ?? '';
}

describe('SeoAgentPanel', () => {
  it('renders the six agents with Russian labels, statuses, errors and step counts', () => {
    render(SeoAgentPanel, { props: { snapshot: snapshot() } });
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(6);
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringContaining('Супервизор'),
      expect.stringContaining('Агент сайта'),
      expect.stringContaining('Агент конкурентов'),
      expect.stringContaining('Агент запросов'),
      expect.stringContaining('Агент проверок'),
      expect.stringContaining('Агент отчёта')
    ]);

    expect(status('supervisor')).toBe('Готово');
    expect(status('site')).toBe('Ошибка');
    expect(status('competitors')).toBe('Ждёт');
    expect(status('queries')).toBe('Выполняется');
    expect(status('checks')).toBe('Пропущен');
    expect(status('report')).toBe('Ожидает');

    expect(agent('supervisor').textContent).toContain('Шагов: 4');
    expect(agent('site').textContent).toContain('Шагов: 3');
    expect(agent('site').textContent).toContain('Сайт недоступен');
    expect(agent('report').textContent).toContain('Шагов: 0');
    expect(agent('site').querySelector('[data-agent-error]')?.textContent).toContain('Сайт недоступен');
  });

  it('shows every missing agent as pending instead of dropping it', () => {
    render(SeoAgentPanel, { props: { snapshot: snapshot({ agents: [] }) } });
    expect(screen.getAllByRole('listitem')).toHaveLength(6);
    for (const id of ['supervisor', 'site', 'competitors', 'queries', 'checks', 'report']) {
      expect(status(id)).toBe('Ожидает');
    }
  });

  it('renders the spent budgets as used over limit plus the raw counters', () => {
    render(SeoAgentPanel, { props: { snapshot: snapshot() } });
    expect(document.querySelector('[data-agent-panel]')).toBeTruthy();
    expect(budget('pages')).toBe('3 / 20');
    expect(budget('searches')).toBe('5 / 43');
    expect(budget('model_answers')).toBe('4 / 40');
    expect(budget('tool_calls')).toBe('9 / 120');
    expect(budget('handoffs')).toBe('5 / 15');
    expect(budget('seed_searches')).toBe('3');
    expect(budget('steps')).toBe('12');
    expect(screen.getByLabelText('Израсходовано').textContent).toContain('Вызовы инструментов');
  });

  it('marks the run as stopped by the budget only when the flag is set', () => {
    const view = render(SeoAgentPanel, { props: { snapshot: snapshot() } });
    expect(document.querySelector('[data-budget-exhausted]')).toBeNull();
    view.unmount();

    render(SeoAgentPanel, { props: { snapshot: snapshot({ budget_exhausted: true }) } });
    expect(screen.getByRole('status').textContent).toContain('остановлен по лимиту');
  });
});
