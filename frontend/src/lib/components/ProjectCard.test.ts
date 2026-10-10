// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, expect, it, vi } from 'vitest';
import ProjectCard from './ProjectCard.svelte';
import type { ProjectSummary } from '$lib/project-types';

afterEach(cleanup);

const emptyProject: ProjectSummary = {
  id: 'empty',
  name: 'Авито',
  brand: 'Авито',
  site_url: 'https://avito.ru',
  competitors: [],
  queries: [],
  connection_ids: [],
  connections: [],
  yandex_enabled: false,
  yandex_region: 213,
  revision: 1,
  created_at: '',
  updated_at: '',
  latest_measurement: null,
  active_measurement: null,
};

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
  expect(screen.getByText('Изменения — к предыдущему замеру')).toBeTruthy();
  expect(screen.getByText('Всего упоминаний').parentElement?.textContent).toContain('32 из 75');
  expect(screen.getByText('+1').className).toContain('text-red-600');
  expect(
    screen.getByTitle('Последний завершённый замер: 09.10.2026 15:00 · московское время'),
  ).toBeTruthy();
  expect(screen.getByText('Положительных')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Запустить замер' })).toBeTruthy();
});

it('offers one explicit first measurement action instead of empty metrics', async () => {
  const onStart = vi.fn();
  render(ProjectCard, { project: emptyProject, onStart });
  expect(screen.getByText('Запустите первый замер')).toBeTruthy();
  expect(screen.queryByText('Всего упоминаний')).toBeNull();
  expect(screen.getAllByRole('button', { name: 'Запустить замер' })).toHaveLength(1);
  await fireEvent.click(screen.getByRole('button', { name: 'Запустить замер' }));
  expect(onStart).toHaveBeenCalledTimes(1);
});

it('prevents another launch while the first request is pending', () => {
  render(ProjectCard, { project: emptyProject, busy: true });
  expect((screen.getByRole('button', { name: 'Запускаем…' }) as HTMLButtonElement).disabled).toBe(
    true,
  );
});

it('shows first measurement progress without offering a duplicate launch', () => {
  render(ProjectCard, {
    project: {
      ...emptyProject,
      active_measurement: {
        id: 'running',
        aggregates: {
          model_errors: 0,
          search_errors: 0,
          progress: {
            model_done: 2,
            model_total: 10,
            sentiment_done: 0,
            sentiment_total: 0,
            search_done: 0,
            search_total: 0,
          },
          models: [],
          queries: [],
          competitors: [],
          sources: [],
          search: [],
          successful: 2,
          planned: 10,
          mentioned: 0,
          visibility: null,
          sentiment: { positive: 0, neutral: 0, negative: 0, unknown: 0 },
        },
        comparison: {
          visibility_delta: null,
          mentioned_delta: null,
          sentiment_delta: null,
          reason: null,
        },
        status: 'running',
        created_at: '',
        finished_at: null,
        progress: {
          model_done: 2,
          model_total: 10,
          sentiment_done: 0,
          sentiment_total: 0,
          search_done: 0,
          search_total: 0,
        },
      },
    },
  });
  expect(screen.getByText('Первый замер выполняется')).toBeTruthy();
  expect(screen.getByRole('status').textContent).toContain('Получено 2 из 10 ответов');
  expect(screen.queryByRole('button', { name: 'Запустить замер' })).toBeNull();
});

it('loads a local provider logo and retains the full connection name', () => {
  const { container } = render(ProjectCard, {
    project: { ...emptyProject, connections: [{ connection_id: 'd1', name: 'DeepSeek · Flash' }] },
  });
  expect(screen.getByLabelText('DeepSeek · Flash')).toBeTruthy();
  expect(container.querySelector('img')?.getAttribute('src')).toContain(
    '/providers/deepseek-color.svg',
  );
});
