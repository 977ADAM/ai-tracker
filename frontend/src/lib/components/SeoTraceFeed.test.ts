// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import SeoTraceFeed from './SeoTraceFeed.svelte';
import type { SeoTraceStep } from '$lib/types';

const handoff: SeoTraceStep = {
  step_index: 1, agent: 'supervisor', kind: 'handoff', name: 'handoff_to',
  arguments: { agent: 'site' }, result_summary: '{"status":"accepted"}', status: 'done',
  error: null, created_at: '2026-09-28T10:01:00Z'
};

const fetchStep: SeoTraceStep = {
  step_index: 2, agent: 'site', kind: 'tool', name: 'fetch_site',
  arguments: { max_pages: 2 }, result_summary: null, status: 'rejected',
  error: 'Лимит прогона исчерпан', created_at: '2026-09-28T10:02:00Z'
};

const modelStep: SeoTraceStep = {
  step_index: 3, agent: 'checks', kind: 'model', name: 'checks',
  arguments: {}, result_summary: '{"status":"done"}', status: 'running',
  error: null, created_at: '2026-09-28T10:03:00Z'
};

function step(index: number): HTMLElement {
  return document.querySelector(`[data-trace-step="${index}"]`) as HTMLElement;
}

function toggle(): HTMLElement {
  return screen.getByRole('button', { name: /Показать трассу|Скрыть трассу/ });
}

async function open(): Promise<void> {
  await fireEvent.click(toggle());
}

describe('SeoTraceFeed', () => {
  it('renders the steps in trace order with agent, kind, tool, arguments, result and status', async () => {
    render(SeoTraceFeed, { props: { steps: [handoff, fetchStep, modelStep] } });
    await open();
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(3);
    expect(items.map((item) => item.getAttribute('data-trace-step'))).toEqual(['1', '2', '3']);

    expect(step(1).textContent).toContain('#1');
    expect(step(1).textContent).toContain('Супервизор');
    expect(step(1).textContent).toContain('Передача управления');
    expect(step(1).textContent).toContain('handoff_to');
    expect(step(1).textContent).toContain('{"agent":"site"}');
    expect(step(1).textContent).toContain('{"status":"accepted"}');
    expect(step(1).textContent).toContain('Готово');

    expect(step(2).textContent).toContain('Агент сайта');
    expect(step(2).textContent).toContain('Инструмент');
    expect(step(2).textContent).toContain('Отклонён');
    expect(step(2).querySelector('[data-trace-result]')?.textContent?.trim()).toBe('—');
    expect(step(2).querySelector('[data-trace-step-error]')?.textContent).toContain('Лимит прогона исчерпан');

    expect(step(3).querySelector('[data-trace-arguments]')?.textContent?.trim()).toBe('—');
    expect(step(3).textContent).toContain('Модель');
    expect(step(3).textContent).toContain('Выполняется');
    expect(step(3).getAttribute('data-trace-status')).toBe('running');
  });

  it('shows an empty state when no step is saved yet', () => {
    render(SeoTraceFeed, { props: { steps: [] } });
    expect(screen.getByText('Шаги трассы пока не записаны.')).toBeTruthy();
    expect(screen.queryAllByRole('listitem')).toHaveLength(0);
    expect(document.querySelector('[data-trace-empty]')).toBeTruthy();
  });

  it('loads more through the cursor button and disables it while a page is in flight', async () => {
    const onMore = vi.fn();
    const view = render(SeoTraceFeed, { props: { steps: [handoff], nextCursor: 'cur_1', onMore } });
    await open();
    await fireEvent.click(screen.getByRole('button', { name: 'Показать ещё' }));
    expect(onMore).toHaveBeenCalledTimes(1);
    view.unmount();

    render(SeoTraceFeed, { props: { steps: [handoff], nextCursor: 'cur_1', loading: true, onMore } });
    await open();
    const button = screen.getByRole('button', { name: 'Загружаем…' }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it('hides the cursor button without a next page and reports a safe load error', async () => {
    const view = render(SeoTraceFeed, { props: { steps: [handoff], nextCursor: null } });
    await open();
    expect(screen.queryByRole('button', { name: 'Показать ещё' })).toBeNull();
    view.unmount();

    // A load error is worth showing even while the feed itself is folded.
    render(SeoTraceFeed, { props: { steps: [], error: 'Не удалось загрузить трассу' } });
    expect(screen.getByRole('alert').textContent).toContain('Не удалось загрузить трассу');
  });

  it('starts folded, opens and closes on the toggle, and counts the steps', async () => {
    render(SeoTraceFeed, { props: { steps: [handoff, fetchStep] } });

    expect(toggle().getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByRole('listitem')).toBeNull();
    expect(document.querySelector('[data-trace-summary]')?.textContent).toContain('2 шага');

    await open();
    expect(toggle().getAttribute('aria-expanded')).toBe('true');
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    expect(document.querySelector('[data-trace-body]')).toBeTruthy();

    await fireEvent.click(toggle());
    expect(toggle().getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByRole('listitem')).toBeNull();
  });

  it('shortens long safe arguments instead of dumping them', async () => {
    const long = { text: 'я'.repeat(400) };
    render(SeoTraceFeed, { props: { steps: [{ ...fetchStep, arguments: long }] } });
    await open();
    const shown = step(2).querySelector('[data-trace-arguments]')?.textContent ?? '';
    expect(shown.endsWith('…')).toBe(true);
    expect(shown.length).toBeLessThanOrEqual(160);
  });
});
