// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import ChatProposal from './ChatProposal.svelte';
import { MAX_CONNECTIONS } from '$lib/seo-form';
import type { ChatMessage, ChatProposal as ChatProposalPayload, PublicProvider } from '$lib/types';

function provider(id: string, overrides: Partial<PublicProvider> = {}): PublicProvider {
  return {
    id,
    name: `Провайдер ${id}`,
    kind: 'openai',
    endpoint: null,
    model: `model-${id}`,
    configured: true,
    editable_fields: [],
    can_reset: true,
    can_delete: true,
    status_label: 'Не настроено',
    delete_label: `Удалить ${id}`,
    delete_prompt: 'Удалить подключение?',
    delete_success: 'Подключение удалено',
    ...overrides,
  };
}

function proposal(overrides: Partial<ChatProposalPayload> = {}): ChatProposalPayload {
  return {
    status: 'pending',
    url: 'https://example.ru',
    sphere: 'Доставка цветов',
    seeds: ['купить цветы', 'доставка букетов', 'заказать розы'],
    services: ['Сборка букетов на заказ'],
    connection_ids: ['a'],
    search_upper: 5,
    model_upper: 5,
    generated_limit: 2,
    ...overrides,
  };
}

function proposalMessage(overrides: Partial<ChatProposalPayload> = {}): ChatMessage {
  return {
    id: 'm-1',
    seq: 3,
    role: 'assistant',
    kind: 'proposal',
    text: 'Проверьте параметры и подтвердите запуск словом «да».',
    payload: proposal(overrides),
    created_at: '2026-10-07T10:00:00Z',
  };
}

describe('ChatProposal', () => {
  it('shows the collected parameters and the estimate', () => {
    render(ChatProposal, {
      props: {
        message: proposalMessage(),
        providers: [provider('a'), provider('b')],
        onToggle: vi.fn(),
      },
    });
    expect(screen.getByText('https://example.ru')).toBeTruthy();
    expect(screen.getByText('Доставка цветов')).toBeTruthy();
    expect(screen.getByText('купить цветы')).toBeTruthy();
    expect(screen.getByText('Сборка букетов на заказ')).toBeTruthy();
    expect(screen.getByText(/5/)).toBeTruthy();
    expect(screen.getByText(/не больше 5 поисковых запросов и 5 ответов моделей/i)).toBeTruthy();
  });

  it('takes the estimate from the payload instead of the constants', () => {
    render(ChatProposal, {
      props: {
        message: proposalMessage({ search_upper: 7, model_upper: 3 }),
        providers: [provider('a')],
        onToggle: vi.fn(),
      },
    });
    expect(screen.getByText(/не больше 7 поисковых запросов и 3 ответов моделей/i)).toBeTruthy();
    expect(screen.queryByText(/не больше 5 поисковых запросов/)).toBeNull();
  });

  it('marks the selected connections and reports a toggle', async () => {
    const onToggle = vi.fn();
    render(ChatProposal, {
      props: {
        message: proposalMessage({ connection_ids: ['a'] }),
        providers: [provider('a'), provider('b')],
        onToggle,
      },
    });
    expect((screen.getByRole('checkbox', { name: /a/ }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole('checkbox', { name: /b/ }) as HTMLInputElement).checked).toBe(false);

    const second = screen.getByRole('checkbox', { name: /b/ });
    await fireEvent.click(second);
    expect(onToggle).toHaveBeenCalledWith('b');
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it('renders only configured providers and never more than MAX_CONNECTIONS chips', () => {
    const providers = [
      provider('1'),
      provider('2'),
      provider('3'),
      provider('4'),
      provider('5'),
      provider('6'),
      provider('7', { configured: false }),
    ];
    render(ChatProposal, { props: { message: proposalMessage(), providers, onToggle: vi.fn() } });
    expect(screen.getAllByRole('checkbox')).toHaveLength(MAX_CONNECTIONS);
    expect(screen.queryByText('Провайдер 7')).toBeNull();
  });

  it('renders a superseded proposal as inactive', async () => {
    const onToggle = vi.fn();
    render(ChatProposal, {
      props: {
        message: proposalMessage({ status: 'superseded' }),
        providers: [provider('a')],
        onToggle,
      },
    });
    expect(screen.getByText(/устарел/i)).toBeTruthy();
    const box = screen.getByRole('checkbox') as HTMLInputElement;
    expect(box.disabled).toBe(true);
    await fireEvent.click(box);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it('marks a confirmed proposal', () => {
    render(ChatProposal, {
      props: {
        message: proposalMessage({ status: 'confirmed' }),
        providers: [provider('a')],
        onToggle: vi.fn(),
      },
    });
    expect(screen.getByText('Подтверждено')).toBeTruthy();
  });

  it('blocks the chips while the card is busy', async () => {
    const onToggle = vi.fn();
    render(ChatProposal, {
      props: { message: proposalMessage(), providers: [provider('a')], onToggle, busy: true },
    });
    const box = screen.getByRole('checkbox') as HTMLInputElement;
    expect(box.disabled).toBe(true);
    await fireEvent.click(box);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it('does not repeat the confirmation hint owned by the assistant text', () => {
    render(ChatProposal, {
      props: { message: proposalMessage(), providers: [provider('a')], onToggle: vi.fn() },
    });
    expect(screen.queryByText(/словом «да»/i)).toBeNull();
    expect(screen.queryByText(/подтвердите запуск/i)).toBeNull();
  });

  it('renders nothing for a message that carries no proposal payload', () => {
    const text: ChatMessage = { ...proposalMessage(), kind: 'text', payload: null };
    const first = render(ChatProposal, {
      props: { message: text, providers: [provider('a')], onToggle: vi.fn() },
    });
    expect(first.container.querySelector('[data-chat-proposal]')).toBeNull();
    first.unmount();

    const run: ChatMessage = { ...proposalMessage(), kind: 'run', payload: { analysis_id: 'a-1' } };
    const second = render(ChatProposal, {
      props: { message: run, providers: [provider('a')], onToggle: vi.fn() },
    });
    expect(second.container.querySelector('[data-chat-proposal]')).toBeNull();
    second.unmount();

    const broken: ChatMessage = { ...proposalMessage(), payload: { analysis_id: 'a-1' } };
    const third = render(ChatProposal, {
      props: { message: broken, providers: [provider('a')], onToggle: vi.fn() },
    });
    expect(third.container.querySelector('[data-chat-proposal]')).toBeNull();
    expect(screen.queryByRole('checkbox')).toBeNull();
  });
});
