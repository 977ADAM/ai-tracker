// @vitest-environment jsdom
import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import SearchReport from './SearchReport.svelte';
import type { SearchRow, SearchSnapshot } from '$lib/types';

function row(overrides: Partial<SearchRow>): SearchRow {
  return {
    prompt: 'цветы',
    region_id: 1,
    region_name: 'Москва и Московская область',
    status: 'waiting',
    position: null,
    url: null,
    error: null,
    ...overrides
  };
}

function snapshot(results: SearchRow[], overrides: Partial<SearchSnapshot> = {}): SearchSnapshot {
  const completed = results.filter((item) => item.status === 'found' || item.status === 'absent' || item.status === 'error').length;
  return {
    id: 'job-1',
    domain: 'example.ru',
    regions: [1],
    total: results.length,
    completed,
    status: completed === results.length ? 'done' : 'pending',
    summary: {
      successful: results.filter((item) => item.status === 'found' || item.status === 'absent').length,
      found: results.filter((item) => item.status === 'found').length,
      failed: results.filter((item) => item.status === 'error').length
    },
    results,
    ...overrides
  };
}

function rows(): HTMLElement[] {
  return screen.getAllByRole('row').slice(1);
}

describe('SearchReport', () => {
  it('shows the aggregate counts of the job', () => {
    render(SearchReport, {
      props: {
        snapshot: snapshot([
          row({ status: 'found', position: 2, url: 'https://shop.example.ru/page' }),
          row({ status: 'absent', region_id: 213, region_name: 'Москва' }),
          row({ status: 'error', region_id: 65, region_name: 'Новосибирск', error: 'Не удалось получить выдачу Яндекса' })
        ])
      }
    });

    expect(screen.getByText('Найдено в первой десятке')).toBeTruthy();
    expect(screen.getByText(/Готово 3 из 3/)).toBeTruthy();
    const article = screen.getByText('Найдено в первой десятке').closest('article') as HTMLElement;
    expect(within(article).getByText('1')).toBeTruthy();
  });

  it('shows the rank and the link of a found pair', () => {
    render(SearchReport, { props: { snapshot: snapshot([row({ status: 'found', position: 2, url: 'https://shop.example.ru/page' })]) } });

    const found = rows()[0];
    expect(found.textContent).toContain('Сайт в первой десятке');
    expect(found.textContent).toContain('2');
    expect(within(found).getByRole('link').getAttribute('href')).toBe('https://shop.example.ru/page');
  });

  it('never renders a failed pair as an absent site', () => {
    render(SearchReport, {
      props: { snapshot: snapshot([row({ status: 'error', error: 'Не удалось получить выдачу Яндекса' })]) }
    });

    const failed = rows()[0];
    expect(failed.textContent).toContain('Ошибка запроса');
    expect(failed.textContent).toContain('Не удалось получить выдачу Яндекса');
    expect(failed.textContent).not.toContain('не найден');
    expect(failed.getAttribute('data-status')).toBe('error');
  });

  it('distinguishes a pending pair from an absent one', () => {
    render(SearchReport, {
      props: { snapshot: snapshot([row({ status: 'waiting' }), row({ status: 'absent', region_id: 213, region_name: 'Москва' })], { completed: 1, status: 'pending' }) }
    });

    expect(rows()[0].textContent).toContain('Яндекс считает');
    expect(rows()[1].textContent).toContain('Сайт не найден в первой десятке');
    expect(screen.getByText(/Яндекс ещё считает/)).toBeTruthy();
  });

  it('shows a search error without inventing results', () => {
    render(SearchReport, { props: { snapshot: null, error: 'Не удалось запустить поиск' } });

    expect(screen.getByRole('alert').textContent).toBe('Не удалось запустить поиск');
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('explains an empty state before anything ran', () => {
    render(SearchReport, { props: {} });

    expect(screen.getByText('Поиск в Яндексе не запускался')).toBeTruthy();
  });
});
