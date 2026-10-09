// @vitest-environment jsdom
import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import ChatMessage from './ChatMessage.svelte';
import type { ChatMessage as ChatMessageData } from '$lib/types';

function textMessage(
  text: string | null,
  overrides: Partial<ChatMessageData> = {},
): ChatMessageData {
  return {
    id: 'm1',
    seq: 1,
    role: 'user',
    kind: 'text',
    text,
    payload: null,
    created_at: '2026-10-07T10:00:00Z',
    ...overrides,
  };
}

describe('ChatMessage', () => {
  it('renders the text of the message', () => {
    render(ChatMessage, { props: { message: textMessage('проверь сайт example.ru') } });
    expect(screen.getByText('проверь сайт example.ru')).toBeTruthy();
  });

  it('renders a text message without interpreting markup', () => {
    render(ChatMessage, { props: { message: textMessage('<b>привет</b>') } });
    expect(screen.queryByText('привет', { selector: 'b' })).toBeNull();
    expect(screen.getByText('<b>привет</b>')).toBeTruthy();
  });

  it('labels the author of the message', () => {
    const view = render(ChatMessage, {
      props: { message: textMessage('вопрос', { role: 'assistant' }) },
    });
    expect(view.container.textContent).toContain('Ассистент');
    view.unmount();

    render(ChatMessage, { props: { message: textMessage('ответ', { role: 'user' }) } });
    expect(screen.getByText('Вы')).toBeTruthy();
  });

  it('keeps the line breaks of a multi-line answer', () => {
    const { container } = render(ChatMessage, {
      props: { message: textMessage('первая\nвторая') },
    });
    expect(container.querySelector('[data-chat-message-text]')?.textContent).toBe('первая\nвторая');
  });

  it('renders nothing for a card message without text', () => {
    const { container } = render(ChatMessage, {
      props: { message: textMessage(null, { kind: 'proposal' }) },
    });
    expect(container.querySelector('[data-chat-message]')).toBeNull();
  });
});
