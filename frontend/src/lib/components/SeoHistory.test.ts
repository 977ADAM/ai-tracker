// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SeoHistory from './SeoHistory.svelte';
import type { SeoHistoryItem } from '$lib/types';

function item(overrides: Partial<SeoHistoryItem> & { id: string }): SeoHistoryItem {
  return {
    created_at: '2026-09-28T10:00:00Z', finished_at: '2026-09-28T11:00:00Z', status: 'completed',
    sphere: 'Цветы', host: 'example.ru', company_name: 'Ромашка',
    counters: { queries: 12, search_rows: 15, model_rows: 12, search_errors: 0, model_errors: 0 },
    ...overrides
  };
}

const history: SeoHistoryItem[] = [
  item({ id: 'fresh', created_at: '2026-09-28T18:00:00Z', status: 'running', finished_at: null, sphere: 'Свежий прогон' }),
  item({ id: 'done', created_at: '2026-09-27T09:00:00Z', status: 'completed', sphere: 'Завершённый прогон' }),
  item({ id: 'cancelled', created_at: '2026-09-26T09:00:00Z', status: 'cancelled', sphere: 'Отменённый прогон' })
];

afterEach(() => {
  vi.restoreAllMocks();
});

describe('SeoHistory', () => {
  it('renders the saved analyses newest first with their status and counters', () => {
    render(SeoHistory, { props: { items: history, nextCursor: null, onView: vi.fn(), onDelete: vi.fn(), onMore: vi.fn() } });
    const rows = screen.getAllByRole('row').slice(1);
    expect(rows[0].textContent).toContain('Свежий прогон');
    expect(rows[0].textContent).toContain('Выполняется');
    expect(rows[1].textContent).toContain('Завершённый прогон');
    expect(rows[1].textContent).toContain('Завершён');
    expect(rows[1].textContent).toContain('запросов 12');
    expect(rows[2].textContent).toContain('Отменён');
    expect(screen.getByRole('table', { name: 'SEO-история' })).toBeTruthy();
  });

  it('opens a saved report without any other request', async () => {
    const onView = vi.fn();
    render(SeoHistory, { props: { items: history, nextCursor: null, onView, onDelete: vi.fn(), onMore: vi.fn() } });
    await fireEvent.click(screen.getAllByRole('button', { name: 'Открыть отчёт' })[1]);
    expect(onView).toHaveBeenCalledWith('done');
    expect(onView).toHaveBeenCalledTimes(1);
  });

  it('deletes only terminal analyses and asks for confirmation first', async () => {
    const onDelete = vi.fn();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(SeoHistory, { props: { items: history, nextCursor: null, onView: vi.fn(), onDelete, onMore: vi.fn() } });

    const running = screen.getByRole('button', { name: 'Удалить анализ fresh' }) as HTMLButtonElement;
    expect(running.disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'Удалить анализ cancelled' }).hasAttribute('disabled')).toBe(false);

    await fireEvent.click(screen.getByRole('button', { name: 'Удалить анализ done' }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledWith('done');
  });

  it('keeps the entry when the confirmation is declined', async () => {
    const onDelete = vi.fn();
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(SeoHistory, { props: { items: history, nextCursor: null, onView: vi.fn(), onDelete, onMore: vi.fn() } });
    await fireEvent.click(screen.getByRole('button', { name: 'Удалить анализ done' }));
    expect(onDelete).not.toHaveBeenCalled();
  });

  it('loads the next page through the cursor', async () => {
    const onMore = vi.fn();
    const view = render(SeoHistory, { props: { items: history, nextCursor: 'cursor-1', onView: vi.fn(), onDelete: vi.fn(), onMore } });
    await fireEvent.click(screen.getByRole('button', { name: 'Показать ещё' }));
    expect(onMore).toHaveBeenCalledTimes(1);
    view.unmount();

    render(SeoHistory, { props: { items: history, nextCursor: 'cursor-1', onView: vi.fn(), onDelete: vi.fn(), onMore, loading: true } });
    expect((screen.getByRole('button', { name: 'Загружаем…' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows the empty state and a safe history error', () => {
    const view = render(SeoHistory, { props: { items: [], nextCursor: null, onView: vi.fn(), onDelete: vi.fn(), onMore: vi.fn() } });
    expect(screen.getByText('Сохранённых SEO-анализов пока нет.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Показать ещё' })).toBeNull();
    view.unmount();

    render(SeoHistory, { props: {
      items: [], nextCursor: null, onView: vi.fn(), onDelete: vi.fn(), onMore: vi.fn(),
      error: 'Не удалось загрузить SEO-историю'
    } });
    expect(screen.getByRole('alert').textContent).toContain('Не удалось загрузить SEO-историю');
    expect(screen.getByText('Сохранённых SEO-анализов пока нет.')).toBeTruthy();
  });
});
