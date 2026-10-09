// @vitest-environment jsdom
import { render, screen } from '@testing-library/svelte';
import { expect, it } from 'vitest';
import ProjectCard from './ProjectCard.svelte';

it('shows truthful visibility, sentiment and partial coverage', () => {
  render(ProjectCard, {
    project: {
      id: 'p1',
      name: 'Пицца',
      brand: 'Додопицца',
      site_url: 'https://example.ru',
      competitors: [],
      queries: [],
      connection_ids: [],
      yandex_enabled: false,
      yandex_region: 213,
      revision: 1,
      created_at: '',
      updated_at: '',
      connections: [],
      active_measurement: null,
      latest_measurement: {
        id: 'r1',
        status: 'completed',
        created_at: '2026-10-09T12:00:00Z',
        finished_at: null,
        progress: {
          model_done: 75,
          model_total: 75,
          sentiment_done: 32,
          sentiment_total: 32,
          search_done: 0,
          search_total: 0,
        },
        aggregates: {
          model_errors: 0,
          search_errors: 0,
          progress: {
            model_done: 75,
            model_total: 75,
            sentiment_done: 32,
            sentiment_total: 32,
            search_done: 0,
            search_total: 0,
          },
          models: [],
          queries: [],
          competitors: [],
          sources: [],
          search: [],
          successful: 75,
          planned: 75,
          mentioned: 32,
          visibility: 32 / 75,
          sentiment: { positive: 12, neutral: 19, negative: 1, unknown: 0 },
        },
        comparison: {
          visibility_delta: -4,
          mentioned_delta: -3,
          sentiment_delta: { positive: -4, neutral: 0, negative: 1 },
          reason: null,
        },
      },
    },
  });
  expect(screen.getByText('43%')).toBeTruthy();
  expect(screen.getByText('32 из 75')).toBeTruthy();
  expect(screen.getByText('Положительных')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Запустить замер' })).toBeTruthy();
});
