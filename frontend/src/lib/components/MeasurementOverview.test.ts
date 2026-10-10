// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/svelte';
import { afterEach, expect, it } from 'vitest';
import type { Aggregates, Comparison } from '$lib/project-types';
import MeasurementOverview from './MeasurementOverview.svelte';

afterEach(cleanup);
const aggregates: Aggregates = {
  successful: 10,
  planned: 10,
  mentioned: 8,
  visibility: 0.8,
  sentiment: { positive: 2, neutral: 4, negative: 0, unknown: 2 },
  model_errors: 0,
  search_errors: 0,
  models: [],
  queries: [],
  competitors: [],
  sources: [],
  search: [],
  progress: {
    model_done: 10,
    model_total: 10,
    sentiment_done: 8,
    sentiment_total: 8,
    search_done: 0,
    search_total: 0,
  },
};
const comparison: Comparison = {
  visibility_delta: null,
  mentioned_delta: null,
  sentiment_delta: null,
  reason: null,
};
it('accounts for unknown sentiment and answers without a brand in the chart', () => {
  render(MeasurementOverview, { aggregates, comparison });
  expect(screen.getByText('80%')).toBeTruthy();
  const chart = within(screen.getByRole('region', { name: 'Распределение ответов' }));
  expect(chart.getByText('Не определена').parentElement?.textContent).toContain('2');
  expect(chart.getByText('Без упоминания бренда').parentElement?.textContent).toContain('2');
  expect(chart.getAllByText('· 20%')).toHaveLength(3);
  expect(chart.getByText('· 40%')).toBeTruthy();
});
it('does not draw percentages when all responses failed', () => {
  render(MeasurementOverview, {
    aggregates: {
      ...aggregates,
      successful: 0,
      mentioned: 0,
      visibility: null,
      sentiment: { positive: 0, neutral: 0, negative: 0, unknown: 0 },
    },
    comparison,
  });
  expect(screen.getByText('График появится после получения успешных ответов.')).toBeTruthy();
  expect(screen.queryByText('· 0%')).toBeNull();
});
