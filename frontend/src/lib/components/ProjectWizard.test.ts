// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ProjectWizard from './ProjectWizard.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/paths', () => ({ resolve: (path: string) => path }));
const project = {
  id: 'p1',
  name: 'Додо',
  brand: 'Додопицца',
  site_url: 'https://example.ru',
  include_subdomains: false,
  brand_description: 'Сеть пиццерий',
  brand_aliases: [],
  queries: [],
  competitors: [],
  connection_ids: [],
  yandex_enabled: false,
  yandex_region: 213,
  revision: 1,
  created_at: 'now',
  updated_at: 'now',
};
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '');
  };
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it('generates on opening an unfinished step and displays the search sources', async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(project)))
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          kind: 'queries',
          sources: [{ url: 'https://example.ru/about', title: 'О компании' }],
          proposal: { queries: [{ text: 'Где заказать пиццу?', category: null }] },
        }),
      ),
    );
  vi.stubGlobal('fetch', fetch);
  render(ProjectWizard, { initial: project, providers: [] });
  await waitFor(() =>
    expect(screen.getByRole('link', { name: 'О компании' }).getAttribute('href')).toBe(
      'https://example.ru/about',
    ),
  );
  expect(fetch.mock.calls[0][0]).toBe('/api/projects/p1');
  expect(fetch.mock.calls[1][0]).toBe('/api/projects/p1/generate');
});
it('uses save labels when configuring an existing project', () => {
  render(ProjectWizard, {
    initial: { ...project, queries: [{ text: 'Пицца?', category: null }], connection_ids: ['m1'] },
    providers: [],
  });
  expect(screen.getByRole('button', { name: 'Сохранить проект ›' })).toBeTruthy();
  expect(screen.getByRole('button', { name: '↻ Сохранить и запустить проверку' })).toBeTruthy();
});
