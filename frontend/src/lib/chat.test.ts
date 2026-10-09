import { describe, expect, it } from 'vitest';
import { messageText, statusLabel } from './chat';
import type { ChatMessage, ChatSummary } from './types';

function chat(overrides: Partial<ChatSummary> = {}): ChatSummary {
  return {
    id: '1',
    title: 'Цветы',
    updated_at: '2026-10-07T10:00:00Z',
    running: false,
    ...overrides,
  };
}

function message(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'm1',
    seq: 1,
    role: 'assistant',
    kind: 'text',
    text: 'привет',
    payload: null,
    created_at: '2026-10-07T10:00:00Z',
    ...overrides,
  };
}

describe('statusLabel', () => {
  it('marks the chat whose run is still going', () => {
    expect(statusLabel(chat({ running: true }))).toBe('Идёт прогон');
  });

  it('marks every other chat as ready', () => {
    expect(statusLabel(chat({ running: false }))).toBe('Готов');
  });
});

describe('messageText', () => {
  it('returns the text of a text message unchanged', () => {
    expect(messageText(message({ text: 'проверь сайт' }))).toBe('проверь сайт');
  });

  it('trims the edges and keeps the line breaks inside', () => {
    expect(messageText(message({ text: '  первая\nвторая  ' }))).toBe('первая\nвторая');
  });

  it('has no text for an empty text or a card message', () => {
    expect(messageText(message({ text: '' }))).toBeNull();
    expect(messageText(message({ text: '   ' }))).toBeNull();
    expect(messageText(message({ text: null }))).toBeNull();
    expect(messageText(message({ kind: 'proposal', text: null }))).toBeNull();
  });
});
