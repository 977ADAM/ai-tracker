// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import ChatFeed from './ChatFeed.svelte';
import { MAX_CONNECTIONS } from '$lib/seo-form';
import type {
  ChatMessage, ChatProposal as ChatProposalPayload, PublicProvider, SeoAnalysisSnapshot, SeoSearchRow, SeoStage
} from '$lib/types';

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
    ...overrides
  };
}

function proposal(overrides: Partial<ChatProposalPayload> = {}): ChatProposalPayload {
  return {
    status: 'pending',
    url: 'https://example.ru',
    sphere: 'Доставка цветов',
    seeds: ['купить цветы'],
    services: ['Сборка букетов'],
    connection_ids: ['a'],
    search_upper: 5,
    model_upper: 5,
    generated_limit: 2,
    ...overrides
  };
}

function textMessage(text: string, id = `m-${text}`): ChatMessage {
  return { id, seq: 1, role: 'user', kind: 'text', text, payload: null, created_at: '2026-10-07T10:00:00Z' };
}

function proposalMessage(id = 'm-proposal'): ChatMessage {
  return {
    id, seq: 2, role: 'assistant', kind: 'proposal', text: null, payload: proposal(),
    created_at: '2026-10-07T10:00:00Z'
  };
}

function runMessage(analysisId: string, id = 'm-run'): ChatMessage {
  return {
    id, seq: 3, role: 'assistant', kind: 'run', text: null, payload: { analysis_id: analysisId },
    created_at: '2026-10-07T10:00:00Z'
  };
}

function stage(stageNumber: number, status: SeoStage['status']): SeoStage {
  return { stage: stageNumber, status, error: null, counters: {}, updated_at: '2026-10-07T10:00:00Z' };
}

function snapshot(overrides: Partial<SeoAnalysisSnapshot> = {}): SeoAnalysisSnapshot {
  return {
    id: 'a-1', status: 'running', created_at: '2026-10-07T10:00:00Z', updated_at: '2026-10-07T10:00:00Z',
    finished_at: null,
    input: {
      url: 'https://example.ru', host: 'example.ru', sphere: 'Доставка цветов',
      seeds: ['купить цветы'], services: ['Сборка букетов'], connection_ids: ['a']
    },
    estimate: { search_upper: 23, model_upper: 40, generated_limit: 20, connections: 1 },
    company_name: 'Ромашка', services: ['Сборка букетов'], pages: [],
    stages: [stage(1, 'running')],
    agents: ['supervisor', 'site', 'competitors', 'queries', 'checks', 'report']
      .map((agent) => ({ agent, status: 'pending' as const, error: null, updated_at: null })),
    candidates: [], queries: [],
    counters: { queries: 12, search_rows: 4, model_rows: 6, search_errors: 1, model_errors: 2 },
    readiness: {
      report_ready: false, summary_ready: false, queries_ready: true, has_submitted_search_rows: true,
      has_unsubmitted_search_rows: true, has_unfinished_model_rows: true, search_rows: 12, model_rows: 24
    },
    aggregates: { site: { search: {}, ai: {} }, competitors: [], categories: {}, services: {}, counts: {} },
    ...overrides
  } as unknown as SeoAnalysisSnapshot;
}

function searchRow(query: string): SeoSearchRow {
  return {
    query_index: 1, query, category: null, service: null, status: 'found',
    site_position: 3, site_url: null, error: null
  };
}

function feedProps(messages: ChatMessage[], overrides: Record<string, unknown> = {}) {
  return {
    messages,
    providers: [provider('a')],
    // The default run of the helper is loaded, so its card is the live one.
    snapshots: { 'a-1': snapshot() },
    onToggleConnection: vi.fn(),
    onCancel: vi.fn(),
    onLoadRows: vi.fn(),
    onLoadTrace: vi.fn(),
    onOpenReport: vi.fn(),
    onLoadOlder: vi.fn(),
    ...overrides
  };
}

describe('ChatFeed', () => {
  it('routes each message kind to its card', () => {
    render(ChatFeed, { props: feedProps([textMessage('привет'), proposalMessage(), runMessage('a-1')]) });
    expect(screen.getByText('привет')).toBeTruthy();
    expect(screen.getByText('https://example.ru')).toBeTruthy();
    expect(screen.getByText('Прогон SEO-анализа')).toBeTruthy();
  });

  it('keeps the order of the messages', () => {
    const { container } = render(ChatFeed, {
      props: feedProps([textMessage('первое', 'm-1'), runMessage('a-1', 'm-2'), textMessage('третье', 'm-3')])
    });
    const feed = container.querySelector('[data-chat-feed]') as HTMLElement;
    const first = feed.textContent?.indexOf('первое') ?? -1;
    const middle = feed.textContent?.indexOf('Прогон SEO-анализа') ?? -1;
    const last = feed.textContent?.indexOf('третье') ?? -1;
    expect(first).toBeGreaterThanOrEqual(0);
    expect(middle).toBeGreaterThan(first);
    expect(last).toBeGreaterThan(middle);
  });

  it('skips a message with an unknown kind', () => {
    const unknown = { ...textMessage('неизвестное'), kind: 'mystery' } as unknown as ChatMessage;
    const { container } = render(ChatFeed, { props: feedProps([unknown]) });
    expect(screen.queryByText('неизвестное')).toBeNull();
    expect(container.querySelector('[data-chat-message]')).toBeNull();
  });

  it('takes the run snapshot from the snapshots map', () => {
    render(ChatFeed, {
      props: feedProps([runMessage('a-1')], { snapshots: { 'a-1': snapshot({ status: 'running' }) } })
    });
    expect(screen.getByText('Прогон SEO-анализа')).toBeTruthy();
    expect(screen.queryByText('Загружаем прогон…')).toBeNull();
  });

  it('shows the run placeholder while its snapshot is not loaded yet', () => {
    render(ChatFeed, { props: feedProps([runMessage('a-1')], { snapshots: {} }) });
    expect(screen.getByText('Загружаем прогон…')).toBeTruthy();
  });

  it('skips a run message without an analysis id', () => {
    const broken = { ...runMessage('a-1'), payload: null } as ChatMessage;
    const { container } = render(ChatFeed, { props: feedProps([broken]) });
    expect(container.querySelector('[data-chat-run]')).toBeNull();
    expect(container.querySelector('[data-chat-feed]')?.textContent).not.toContain('Прогон SEO-анализа');
  });

  it('forwards a connection toggle with the id of its message', async () => {
    const onToggleConnection = vi.fn();
    render(ChatFeed, { props: feedProps([proposalMessage('m-7')], { onToggleConnection }) });
    await fireEvent.click(screen.getByRole('checkbox', { name: /Провайдер a/ }));
    expect(onToggleConnection).toHaveBeenCalledWith('m-7', 'a');
    expect(onToggleConnection).toHaveBeenCalledTimes(1);
  });

  it('forwards a cancellation with the id of the analysis', async () => {
    const onCancel = vi.fn();
    render(ChatFeed, {
      props: feedProps([runMessage('a-1')], { snapshots: { 'a-1': snapshot() }, onCancel })
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Отменить анализ' }));
    expect(onCancel).toHaveBeenCalledWith('a-1');
  });

  it('opens the report of the run that was clicked', async () => {
    const onOpenReport = vi.fn();
    render(ChatFeed, {
      props: feedProps([runMessage('a-1')], {
        snapshots: { 'a-1': snapshot({ status: 'completed' }) },
        onOpenReport
      })
    });
    await fireEvent.click(screen.getByRole('button', { name: /открыть отчёт/i }));
    expect(onOpenReport).toHaveBeenCalledWith('a-1');
    expect(screen.getByText('Отчёт SEO-анализа')).toBeTruthy();
  });

  it('pages the report rows with the cursor of its analysis', async () => {
    const onLoadRows = vi.fn();
    render(ChatFeed, {
      props: feedProps([runMessage('a-1')], {
        snapshots: { 'a-1': snapshot({ status: 'completed' }) },
        rows: { 'a-1': { model: [], search: [searchRow('купить цветы')] } },
        cursors: { 'a-1': { model: null, search: 'next-1' } },
        onLoadRows
      })
    });
    await fireEvent.click(screen.getByRole('button', { name: /открыть отчёт/i }));
    await fireEvent.click(screen.getByRole('button', { name: 'Показать ещё' }));
    expect(onLoadRows).toHaveBeenCalledWith('a-1', 'search', 'next-1');
  });

  it('shows the earlier-messages button only when the parent has a cursor', async () => {
    const onLoadOlder = vi.fn();
    const view = render(ChatFeed, { props: feedProps([textMessage('привет')], { onLoadOlder }) });
    expect(screen.queryByRole('button', { name: /показать более ранние/i })).toBeNull();

    await view.rerender({ olderCursor: 4 });
    await fireEvent.click(screen.getByRole('button', { name: /показать более ранние/i }));
    expect(onLoadOlder).toHaveBeenCalledTimes(1);
  });

  it('disables the earlier-messages button while the page loads', async () => {
    render(ChatFeed, { props: feedProps([textMessage('привет')], { olderCursor: 4, loadingOlder: true }) });
    expect((screen.getByRole('button', { name: /загружаем/i }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('starts at the newest message when the chat opens', async () => {
    const saved = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollHeight');
    Object.defineProperty(HTMLElement.prototype, 'scrollHeight', { configurable: true, get: () => 480 });
    try {
      const view = render(ChatFeed, { props: feedProps([textMessage('последнее', 'm-1')]) });
      const feed = view.container.querySelector('[data-chat-feed]') as HTMLElement;
      await waitFor(() => expect(feed.scrollTop).toBe(480));
    } finally {
      if (saved) Object.defineProperty(HTMLElement.prototype, 'scrollHeight', saved);
      else Reflect.deleteProperty(HTMLElement.prototype, 'scrollHeight');
    }
  });

  it('scrolls to the newest message when one is added', async () => {
    const view = render(ChatFeed, { props: feedProps([textMessage('первое', 'm-1')]) });
    const feed = view.container.querySelector('[data-chat-feed]') as HTMLElement;
    Object.defineProperty(feed, 'scrollHeight', { value: 640, configurable: true });

    await view.rerender({ messages: [textMessage('первое', 'm-1'), textMessage('второе', 'm-2')] });
    await waitFor(() => expect(feed.scrollTop).toBe(640));
  });

  it('does not jump to the bottom when earlier messages are prepended', async () => {
    const view = render(ChatFeed, { props: feedProps([textMessage('второе', 'm-2')]) });
    const feed = view.container.querySelector('[data-chat-feed]') as HTMLElement;
    Object.defineProperty(feed, 'scrollHeight', { value: 640, configurable: true });
    feed.scrollTop = 120;

    await view.rerender({ messages: [textMessage('первое', 'm-1'), textMessage('второе', 'm-2')] });
    expect(feed.scrollTop).toBe(120);
  });

  it('shows a placeholder for an empty feed', () => {
    render(ChatFeed, { props: feedProps([]) });
    expect(screen.getByText(/Сообщений пока нет/)).toBeTruthy();
  });
});

describe('ChatFeed providers', () => {
  it('never offers more connection chips than the run limit', () => {
    const many = Array.from({ length: MAX_CONNECTIONS + 3 }, (_, index) => provider(`p-${index}`));
    render(ChatFeed, { props: feedProps([proposalMessage()], { providers: many }) });
    expect(screen.getAllByRole('checkbox')).toHaveLength(MAX_CONNECTIONS);
  });
});
