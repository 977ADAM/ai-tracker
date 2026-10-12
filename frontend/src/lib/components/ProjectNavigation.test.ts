// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, expect, it, vi } from 'vitest';
import Page from '../../routes/+page.svelte';
import ProjectHeader from './ProjectHeader.svelte';
import ProjectCard from './ProjectCard.svelte';
import type { ProjectSummary } from '$lib/project-types';

vi.mock('$app/paths', () => ({ base: '/clustering/tracker' }));
afterEach(cleanup);
const project: ProjectSummary = {
  id: 'p1',
  name: 'Pizza',
  brand: 'Pizza',
  site_url: 'https://example.com',
  queries: [],
  competitors: [],
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
it.each([false, true])(
  'keeps project creation beneath the base path (populated: %s)',
  (populated) => {
    render(Page, {
      data: { projects: { items: populated ? [project] : [], cursor: null }, projectsError: '' },
    });
    expect(screen.getByRole('link', { name: /Создать проект/ }).getAttribute('href')).toBe(
      '/clustering/tracker/projects/new',
    );
  },
);
it('keeps project card navigation beneath the base path', () => {
  render(ProjectCard, { project });
  expect(screen.getByRole('link', { name: 'Pizza' }).getAttribute('href')).toBe(
    '/clustering/tracker/projects/p1',
  );
});
it('keeps breadcrumbs and project settings beneath the base path', () => {
  render(ProjectHeader, { project, onStart: () => {}, onRename: async () => {} });
  expect(screen.getByRole('link', { name: 'Главная' }).getAttribute('href')).toBe(
    '/clustering/tracker/',
  );
  expect(screen.getByRole('link', { name: 'Проекты' }).getAttribute('href')).toBe(
    '/clustering/tracker/',
  );
  expect(screen.getByRole('link', { name: 'Настройки' }).getAttribute('href')).toBe(
    '/clustering/tracker/projects/p1/settings',
  );
});
