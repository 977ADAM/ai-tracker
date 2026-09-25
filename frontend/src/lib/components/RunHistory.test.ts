// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import RunHistory from './RunHistory.svelte';
import type { RunHistoryItem } from '$lib/types';

const items: RunHistoryItem[] = [
  { id: 'new', created_at: '2026-09-25T18:17:00Z', status: 'pending', prompts: ['первый', 'второй'] },
  { id: 'old', created_at: '2026-09-23T14:24:00Z', status: 'done', prompts: ['маркетинг'] }
];

describe('RunHistory', () => {
  it('shows newest first, view actions and disabled deletion for an active run', async () => {
    const onView = vi.fn();
    render(RunHistory, { props: { items, nextCursor: 'cursor', onView, onDelete: vi.fn(), onMore: vi.fn() } });
    const rows = screen.getAllByRole('row').slice(1);
    expect(rows[0].textContent).toContain('первый, второй');
    expect(rows[1].textContent).toContain('маркетинг');
    expect(screen.getByRole('button', { name: 'Удалить прогон new' }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByRole('button', { name: 'Удалить прогон old' }).hasAttribute('disabled')).toBe(false);
    await fireEvent.click(screen.getAllByRole('button', { name: 'Посмотреть задачу' })[1]);
    expect(onView).toHaveBeenCalledWith('old');
    expect(screen.getByRole('button', { name: 'Показать ещё' })).toBeTruthy();
  });
});
