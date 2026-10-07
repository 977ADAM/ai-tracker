// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ChatSidebar from './ChatSidebar.svelte';
import type { ChatSummary } from '$lib/types';

function chat(overrides: Partial<ChatSummary> & { id: string }): ChatSummary {
  return { title: 'Новый чат', updated_at: '2026-10-07T10:00:00Z', running: false, ...overrides };
}

const chats: ChatSummary[] = [
  chat({ id: '1', title: 'Цветы' }),
  chat({ id: '2', title: 'Доставка', running: true })
];

function handlers() {
  return { onSelect: vi.fn(), onCreate: vi.fn(), onDelete: vi.fn() };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ChatSidebar', () => {
  it('lists chats and reports the active one', () => {
    render(ChatSidebar, { props: { chats, activeId: '1', ...handlers() } });
    expect(screen.getByText('Цветы')).toBeTruthy();
    expect(screen.getByText('Доставка')).toBeTruthy();
    expect(screen.getByRole('button', { name: /новый чат/i })).toBeTruthy();
  });

  it('opens a chat and creates one without touching the others', async () => {
    const props = handlers();
    render(ChatSidebar, { props: { chats, activeId: '1', ...props } });

    await fireEvent.click(screen.getByRole('button', { name: 'Открыть чат Доставка' }));
    expect(props.onSelect).toHaveBeenCalledWith('2');
    expect(props.onSelect).toHaveBeenCalledTimes(1);

    await fireEvent.click(screen.getByRole('button', { name: /новый чат/i }));
    expect(props.onCreate).toHaveBeenCalledTimes(1);
    expect(props.onDelete).not.toHaveBeenCalled();
  });

  it('marks the active chat and its running state', () => {
    render(ChatSidebar, { props: { chats, activeId: '1', ...handlers() } });
    expect(screen.getByRole('button', { name: 'Открыть чат Цветы' }).getAttribute('aria-current')).toBe('true');
    expect(screen.getByRole('button', { name: 'Открыть чат Доставка' }).getAttribute('aria-current')).toBeNull();
    expect(screen.getByText('Идёт прогон')).toBeTruthy();
    expect(screen.getByText('Готов')).toBeTruthy();
    expect(screen.getByRole('list', { name: 'Чаты' })).toBeTruthy();
  });

  it('deletes a chat only after confirmation and blocks the running one', async () => {
    const props = handlers();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(ChatSidebar, { props: { chats, activeId: null, ...props } });

    const running = screen.getByRole('button', { name: 'Удалить чат 2' }) as HTMLButtonElement;
    expect(running.disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'Удалить чат 1' }).hasAttribute('disabled')).toBe(false);

    await fireEvent.click(screen.getByRole('button', { name: 'Удалить чат 1' }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(props.onDelete).toHaveBeenCalledWith('1');
    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it('keeps the chat when the confirmation is declined', async () => {
    const props = handlers();
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(ChatSidebar, { props: { chats, activeId: null, ...props } });
    await fireEvent.click(screen.getByRole('button', { name: 'Удалить чат 1' }));
    expect(props.onDelete).not.toHaveBeenCalled();
  });

  it('locks every action while the page is busy and shows the empty state', () => {
    const props = handlers();
    const view = render(ChatSidebar, { props: { chats, activeId: '1', ...props } });
    view.unmount();

    render(ChatSidebar, { props: { chats: [], activeId: null, busy: true, ...props } });
    expect(screen.getByText('Чатов пока нет.')).toBeTruthy();
    for (const button of screen.getAllByRole('button')) {
      expect((button as HTMLButtonElement).disabled).toBe(true);
    }
    expect(props.onCreate).not.toHaveBeenCalled();
  });
});
