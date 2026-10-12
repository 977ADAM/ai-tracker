// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ProjectWizard from './ProjectWizard.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/paths', () => ({ base: '', resolve: (path: string) => path }));
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

it('prevents manual competitor edits while generation can replace the list', async () => {
  let completeSearch!: (value: Response) => void;
  vi.stubGlobal('fetch', async (path: string, init: RequestInit) => {
    if (!path.endsWith('/generate')) return new Response(JSON.stringify(project));
    const { kind } = JSON.parse(String(init.body));
    if (kind === 'queries')
      return new Response(
        JSON.stringify({
          kind,
          proposal: { queries: [{ text: 'Pizza?', category: null }] },
          sources: [],
        }),
      );
    return new Promise<Response>((resolve) => {
      completeSearch = resolve;
    });
  });
  const { fireEvent } = await import('@testing-library/svelte');
  render(ProjectWizard, { initial: project, providers: [] });
  await waitFor(() =>
    expect(screen.getByLabelText('Промпт 1').getAttribute('aria-label')).toBe('Промпт 1'),
  );
  await waitFor(() =>
    expect((screen.getByRole('button', { name: '✓ Далее' }) as HTMLButtonElement).disabled).toBe(
      false,
    ),
  );
  await fireEvent.click(screen.getByRole('button', { name: '✓ Далее' }));
  await waitFor(() => expect(completeSearch).toBeTypeOf('function'));
  const input = screen.getByLabelText('Бренд или сайт конкурента') as HTMLInputElement;
  try {
    expect(input.disabled).toBe(true);
  } finally {
    completeSearch(
      new Response(
        JSON.stringify({ kind: 'competitors', proposal: { competitors: [] }, sources: [] }),
      ),
    );
  }
  await waitFor(() => expect(input.disabled).toBe(false));
});

it('prevents deleting competitors while regeneration can restore them', async () => {
  let completeSearch!: (value: Response) => void;
  vi.stubGlobal('fetch', async (path: string) => {
    if (!path.endsWith('/generate')) return new Response(JSON.stringify(project));
    return new Promise<Response>((resolve) => {
      completeSearch = resolve;
    });
  });
  const { fireEvent } = await import('@testing-library/svelte');
  render(ProjectWizard, {
    initial: {
      ...project,
      queries: [{ text: 'Pizza?', category: null }],
      connection_ids: ['m1'],
      competitors: [{ brand: 'Pizza Hut', site_url: '' }],
    },
    providers: [],
  });
  await fireEvent.click(screen.getByRole('button', { name: /Конкуренты/ }));
  await fireEvent.click(screen.getByRole('button', { name: '✧ Сгенерировать' }));
  await waitFor(() => expect(completeSearch).toBeTypeOf('function'));
  try {
    expect(
      (screen.getByRole('button', { name: 'Удалить конкурента 1' }) as HTMLButtonElement).disabled,
    ).toBe(true);
  } finally {
    completeSearch(
      new Response(
        JSON.stringify({ kind: 'competitors', proposal: { competitors: [] }, sources: [] }),
      ),
    );
  }
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: 'Удалить конкурента 1' })).toBeNull(),
  );
});
