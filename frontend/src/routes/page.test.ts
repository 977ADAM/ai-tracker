// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Page from './+page.svelte';
import type {
  ChatMessage, ChatPage, ChatProposal, ChatSummary, PublicProvider, SeoAnalysisSnapshot,
  SeoSearchRow, SeoStage, SeoTraceStep
} from '$lib/types';

const STAMP = '2026-10-07T10:00:00Z';

function provider(id: string): PublicProvider {
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
    delete_success: 'Подключение удалено'
  };
}

function chat(overrides: Partial<ChatSummary> = {}): ChatSummary {
  return { id: 'c1', title: 'Цветы', updated_at: STAMP, running: false, ...overrides };
}

function textMessage(text: string, id = 'm1'): ChatMessage {
  return { id, seq: 1, role: 'user', kind: 'text', text, payload: null, created_at: STAMP };
}

function runMessage(analysisId: string, id = 'm-run'): ChatMessage {
  return {
    id, seq: 2, role: 'assistant', kind: 'run', text: null,
    payload: { analysis_id: analysisId }, created_at: STAMP
  };
}

function proposal(connectionIds: string[]): ChatProposal {
  return {
    status: 'pending', url: 'https://example.ru', sphere: 'Доставка цветов',
    seeds: ['купить цветы'], services: ['Сборка букетов'], connection_ids: connectionIds,
    search_upper: 5, model_upper: 5, generated_limit: 2
  };
}

function proposalMessage(connectionIds: string[] = [], id = 'm-proposal'): ChatMessage {
  return {
    id, seq: 2, role: 'assistant', kind: 'proposal', text: null,
    payload: proposal(connectionIds), created_at: STAMP
  };
}

function stage(number: number, status: SeoStage['status']): SeoStage {
  return { stage: number, status, error: null, counters: {}, updated_at: STAMP };
}

function snapshot(overrides: Partial<SeoAnalysisSnapshot> = {}): SeoAnalysisSnapshot {
  return {
    id: 'a-1', status: 'running', created_at: STAMP, updated_at: STAMP, finished_at: null,
    input: {
      url: 'https://example.ru', host: 'example.ru', sphere: 'Доставка цветов',
      seeds: ['купить цветы'], services: ['Сборка букетов'], connection_ids: ['model-1']
    },
    estimate: { search_upper: 5, model_upper: 5, generated_limit: 2, connections: 1 },
    company_name: 'Ромашка', services: ['Сборка букетов'], pages: [],
    stages: [stage(1, 'running')],
    agents: ['supervisor', 'site', 'competitors', 'queries', 'checks', 'report']
      .map((agent) => ({ agent, status: 'pending' as const, error: null, updated_at: null })),
    candidates: [], queries: [], summary: null, conclusions: null,
    counters: { queries: 1, search_rows: 1, model_rows: 1, search_errors: 0, model_errors: 0 },
    readiness: {
      report_ready: false, summary_ready: false, queries_ready: true, has_submitted_search_rows: false,
      has_unsubmitted_search_rows: false, has_unfinished_model_rows: false, search_rows: 1, model_rows: 1
    },
    aggregates: { site: { search: {}, ai: {} }, competitors: [], categories: {}, services: {}, counts: {} },
    ...overrides
  } as unknown as SeoAnalysisSnapshot;
}

function searchRow(query: string): SeoSearchRow {
  return {
    query_index: 1, query, category: null, service: null, status: 'found',
    site_position: 3, site_url: 'https://example.ru/page', error: null
  };
}

function traceStep(index: number, name: string): SeoTraceStep {
  return {
    step_index: index, agent: 'site', kind: 'tool', name, arguments: {}, result_summary: 'Готово',
    status: 'running', error: null, created_at: STAMP
  };
}

function chatPage(overrides: Partial<ChatPage> = {}): ChatPage {
  return { chat: chat(), messages: [], next_cursor: null, ...overrides };
}

function pageData(overrides: Record<string, unknown> = {}) {
  return {
    providers: [provider('a')],
    chats: [] as ChatSummary[],
    chatsError: '',
    loadError: '',
    ...overrides
  };
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status, headers: { 'content-type': 'application/json' }
  });
}

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>;

/** A fetch stub routed by URL and method; every `Response` is built by the test. */
function stubFetch(handler: Handler) {
  const mock = vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
    Promise.resolve(handler(String(input), init ?? {})));
  vi.stubGlobal('fetch', mock);
  return mock;
}

function calls(mock: ReturnType<typeof stubFetch>, fragment: string) {
  return mock.mock.calls.filter(([url]) => String(url).includes(fragment));
}

/**
 * Snapshot requests only. The trace, rows and cancel endpoints all share the
 * `/api/seo/analyses/{id}` prefix, so a plain `includes` would count them too.
 */
function snapshotCalls(mock: ReturnType<typeof stubFetch>, id: string) {
  return mock.mock.calls.filter(([url]) => String(url).endsWith(`/api/seo/analyses/${id}`));
}

function pollTimers(spy: { mock: { calls: unknown[][] } }): number {
  return spy.mock.calls.filter((call) => call[1] === 30_000).length;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('chat page', () => {
  it('renders the chat screen and no analysis form', () => {
    render(Page, { props: { data: pageData({ chats: [] }) } });
    expect(screen.getByRole('textbox')).toBeTruthy();
    expect(screen.queryByLabelText(/адрес главной страницы/i)).toBeNull();
    expect(screen.queryByRole('button', { name: /запустить анализ/i })).toBeNull();
  });

  it('shows the empty state and says the chat is created by the first message', () => {
    render(Page, { props: { data: pageData({ chats: [] }) } });
    expect(screen.getByText(/чат созда[её]тся при отправке первого сообщения/i)).toBeTruthy();
    expect(screen.getByText('Чатов пока нет.')).toBeTruthy();
  });

  it('keeps the screen working when the chat list is unavailable', () => {
    render(Page, { props: { data: pageData({ chats: [], chatsError: 'Список чатов недоступен' }) } });
    expect(screen.getByText('Список чатов недоступен')).toBeTruthy();
    expect(screen.getByRole('textbox')).toBeTruthy();
  });

  it('opens the freshest chat and loads its messages', async () => {
    const mock = stubFetch((url) => {
      if (url.includes('/api/seo/chats/')) {
        return jsonResponse(chatPage({ chat: chat({ id: 'c1' }), messages: [textMessage('привет')] }));
      }
      return jsonResponse({ detail: 'Нет маршрута' }, 404);
    });
    render(Page, { props: { data: pageData({ chats: [chat({ id: 'c1' })] }) } });

    await waitFor(() => expect(screen.getByText('привет')).toBeTruthy());
    expect(String(mock.mock.calls[0][0])).toContain('/api/seo/chats/c1');
  });

  it('creates a chat on the first message and posts it', async () => {
    const mock = stubFetch((url) => {
      if (url.endsWith('/api/seo/chats')) return jsonResponse({ chat: chat() }, 201);
      if (url.endsWith('/messages')) {
        return jsonResponse({ chat: chat(), messages: [textMessage('привет')] });
      }
      return jsonResponse({ detail: 'Нет маршрута' }, 404);
    });
    render(Page, { props: { data: pageData({ chats: [] }) } });
    const box = screen.getByRole('textbox');
    await fireEvent.input(box, { target: { value: 'привет' } });
    await fireEvent.keyDown(box, { key: 'Enter' });

    await waitFor(() => expect(mock).toHaveBeenCalledTimes(2));
    expect(String(mock.mock.calls[0][0])).toContain('/api/seo/chats');
    expect(mock.mock.calls[0][1]?.method).toBe('POST');
    expect(String(mock.mock.calls[1][0])).toContain('/messages');
    expect(mock.mock.calls[1][1]?.method).toBe('POST');
    await waitFor(() => expect(screen.getByText('привет')).toBeTruthy());
  });

  it('keeps the typed text and explains a failed send', async () => {
    stubFetch((url) => {
      if (url.endsWith('/api/seo/chats')) return jsonResponse({ chat: chat() }, 201);
      if (url.endsWith('/messages')) return jsonResponse({ detail: 'Python API недоступен' }, 502);
      return jsonResponse({ detail: 'Нет маршрута' }, 404);
    });
    render(Page, { props: { data: pageData({ chats: [] }) } });
    const box = screen.getByRole('textbox') as HTMLTextAreaElement;
    await fireEvent.input(box, { target: { value: 'проверь сайт' } });
    await fireEvent.keyDown(box, { key: 'Enter' });

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    expect(screen.getByRole('alert').textContent).toContain('Python API недоступен');
    expect(box.value).toBe('проверь сайт');
  });

  it('restores a running analysis when a chat is opened', async () => {
    const mock = stubFetch((url) => {
      if (url.includes('/api/seo/analyses/a-1/trace')) return jsonResponse({ items: [], next_cursor: null });
      if (url.includes('/api/seo/analyses/a-1')) return jsonResponse(snapshot({ status: 'running' }));
      if (url.includes('/api/seo/chats/')) {
        return jsonResponse(chatPage({
          chat: chat({ id: 'c1', running: true }), messages: [runMessage('a-1')]
        }));
      }
      return jsonResponse({ detail: 'Нет маршрута' }, 404);
    });
    render(Page, { props: { data: pageData({ chats: [chat({ id: 'c1', running: true })] }) } });

    await waitFor(() => expect(screen.getByText('Прогон SEO-анализа')).toBeTruthy());
    expect(snapshotCalls(mock, 'a-1')).toHaveLength(1);
    expect(screen.getByText('Идёт прогон')).toBeTruthy();
  });

  it('does not poll a run that is already finished', async () => {
    const timeout = vi.spyOn(globalThis, 'setTimeout');
    const mock = stubFetch((url) => {
      if (url.includes('/api/seo/analyses/a-1')) return jsonResponse(snapshot({ status: 'completed' }));
      if (url.includes('/api/seo/chats/')) {
        return jsonResponse(chatPage({
          chat: chat({ id: 'c1', running: true }), messages: [runMessage('a-1')]
        }));
      }
      return jsonResponse({ detail: 'Нет маршрута' }, 404);
    });
    render(Page, { props: { data: pageData({ chats: [chat({ id: 'c1', running: true })] }) } });

    await waitFor(() => expect(snapshotCalls(mock, 'a-1')).toHaveLength(1));
    await waitFor(() => expect(screen.getByText('Прогон SEO-анализа')).toBeTruthy());
    expect(pollTimers(timeout)).toBe(0);
    await waitFor(() => expect(screen.getByText('Готов')).toBeTruthy());
  });

  it('polls a running analysis on the existing 30-second interval and stops once it is finished', async () => {
    const timeout = vi.spyOn(globalThis, 'setTimeout');
    let analysis = snapshot({ status: 'running' });
    const mock = stubFetch((url) => {
      if (url.includes('/api/seo/analyses/a-1/trace')) return jsonResponse({ items: [], next_cursor: null });
      if (url.includes('/api/seo/analyses/a-1')) return jsonResponse(analysis);
      if (url.includes('/api/seo/chats/')) {
        return jsonResponse(chatPage({
          chat: chat({ id: 'c1', running: true }), messages: [runMessage('a-1')]
        }));
      }
      return jsonResponse({ detail: 'Нет маршрута' }, 404);
    });
    render(Page, { props: { data: pageData({ chats: [chat({ id: 'c1', running: true })] }) } });

    await waitFor(() => expect(snapshotCalls(mock, 'a-1')).toHaveLength(1));
    await screen.findByText('Прогон SEO-анализа');
    expect(screen.getByText('Идёт прогон')).toBeTruthy();
    const scheduled = timeout.mock.calls.filter((call) => call[1] === 30_000);
    expect(scheduled).toHaveLength(1);

    analysis = snapshot({ status: 'completed' });
    (scheduled[0][0] as () => void)();
    await waitFor(() => expect(snapshotCalls(mock, 'a-1')).toHaveLength(2));
    await waitFor(() => expect(screen.getByText('Готов')).toBeTruthy());
    expect(pollTimers(timeout)).toBe(1);
  });

  it('ignores a snapshot that arrives after the chat was left', async () => {
    const timeout = vi.spyOn(globalThis, 'setTimeout');
    let release: (value: Response) => void = () => {};
    const pending = new Promise<Response>((resolve) => { release = resolve; });
    const mock = stubFetch((url) => {
      if (url.includes('/api/seo/analyses/a-1')) return pending;
      if (url.includes('/api/seo/chats/')) {
        return jsonResponse(chatPage({ chat: chat({ id: 'c1' }), messages: [runMessage('a-1')] }));
      }
      return jsonResponse({ detail: 'Нет маршрута' }, 404);
    });
    render(Page, { props: { data: pageData({ chats: [chat({ id: 'c1' })] }) } });

    await waitFor(() => expect(snapshotCalls(mock, 'a-1')).toHaveLength(1));
    await fireEvent.click(screen.getByRole('button', { name: /новый чат/i }));
    release(jsonResponse(snapshot({ status: 'running' })));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(pollTimers(timeout)).toBe(0);
    expect(screen.queryByText('Прогон SEO-анализа')).toBeNull();
  });

  it('loads the first pages of the rows and the trace when the report is opened', async () => {
    const mock = stubFetch((url) => {
      if (url.includes('/api/seo/analyses/a-1/rows')) {
      return jsonResponse({ items: url.includes('kind=search') ? [searchRow('купить цветы')] : [], next_cursor: null });
    }
      if (url.includes('/api/seo/analyses/a-1/trace')) return jsonResponse({ items: [], next_cursor: null });
      if (url.includes('/api/seo/analyses/a-1')) return jsonResponse(snapshot({ status: 'completed' }));
      if (url.includes('/api/seo/chats/')) {
        return jsonResponse(chatPage({ messages: [runMessage('a-1')] }));
      }
      return jsonResponse({ detail: 'Нет маршрута' }, 404);
    });
    render(Page, { props: { data: pageData({ chats: [chat({ id: 'c1' })] }) } });

    const toggle = await screen.findByRole('button', { name: /открыть отчёт/i });
    await fireEvent.click(toggle);

    await waitFor(() => expect(calls(mock, '/rows?kind=search')).toHaveLength(1));
    expect(calls(mock, '/rows?kind=model')).toHaveLength(1);
    const trace = calls(mock, '/api/seo/analyses/a-1/trace');
    expect(trace).toHaveLength(1);
    expect(String(trace[0][0])).not.toContain('cursor=');
  });

  it('keeps the agent trace of a running run up to date while it polls', async () => {
    const timeout = vi.spyOn(globalThis, 'setTimeout');
    const mock = stubFetch((url) => {
      if (url.includes('/api/seo/analyses/a-1/trace')) {
        return jsonResponse({ items: [traceStep(1, 'site_crawl')], next_cursor: null });
      }
      if (url.includes('/api/seo/analyses/a-1')) return jsonResponse(snapshot({ status: 'running' }));
      if (url.includes('/api/seo/chats/')) {
        return jsonResponse(chatPage({
          chat: chat({ id: 'c1', running: true }), messages: [runMessage('a-1')]
        }));
      }
      return jsonResponse({ detail: 'Нет маршрута' }, 404);
    });
    render(Page, { props: { data: pageData({ chats: [chat({ id: 'c1', running: true })] }) } });

    // The first trace page is requested as soon as the running run appears.
    await waitFor(() => expect(calls(mock, '/trace')).toHaveLength(1));
    const first = calls(mock, '/trace')[0];
    expect(String(first[0])).toContain('/api/seo/analyses/a-1/trace');
    expect(String(first[0])).not.toContain('cursor=');

    // The steps reach the live card through the feed's `traces` map.
    await screen.findByText('Прогон SEO-анализа');
    await waitFor(() => expect(screen.getByText('1 шаг')).toBeTruthy());
    await fireEvent.click(screen.getByRole('button', { name: /показать трассу/i }));
    expect(screen.getByText('site_crawl')).toBeTruthy();

    // The 30-second poll refreshes that same first page, so new steps appear.
    const scheduled = timeout.mock.calls.filter((call) => call[1] === 30_000);
    expect(scheduled).toHaveLength(1);
    (scheduled[0][0] as () => void)();
    await waitFor(() => expect(calls(mock, '/trace')).toHaveLength(2));
    expect(String(calls(mock, '/trace')[1][0])).not.toContain('cursor=');
  });

  it('does not collapse a trace the user paged deeper when a running run is polled', async () => {
    const timeout = vi.spyOn(globalThis, 'setTimeout');
    const mock = stubFetch((url) => {
      if (url.includes('/api/seo/analyses/a-1/trace')) {
        return url.includes('cursor=p1')
          ? jsonResponse({ items: [traceStep(2, 'deep_step')], next_cursor: null })
          : jsonResponse({ items: [traceStep(1, 'first_step')], next_cursor: 'p1' });
      }
      if (url.includes('/api/seo/analyses/a-1')) return jsonResponse(snapshot({ status: 'running' }));
      if (url.includes('/api/seo/chats/')) {
        return jsonResponse(chatPage({
          chat: chat({ id: 'c1', running: true }), messages: [runMessage('a-1')]
        }));
      }
      return jsonResponse({ detail: 'Нет маршрута' }, 404);
    });
    render(Page, { props: { data: pageData({ chats: [chat({ id: 'c1', running: true })] }) } });

    await screen.findByText('Прогон SEO-анализа');
    await waitFor(() => expect(calls(mock, '/trace')).toHaveLength(1));
    await fireEvent.click(screen.getByRole('button', { name: /показать трассу/i }));
    await fireEvent.click(screen.getByRole('button', { name: /показать ещё/i }));
    await waitFor(() => expect(calls(mock, '/trace')).toHaveLength(2));
    expect(String(calls(mock, '/trace')[1][0])).toContain('cursor=p1');
    expect(screen.getByText('deep_step')).toBeTruthy();

    const scheduled = timeout.mock.calls.filter((call) => call[1] === 30_000);
    (scheduled[scheduled.length - 1][0] as () => void)();
    await waitFor(() => expect(snapshotCalls(mock, 'a-1')).toHaveLength(2));

    // The user's deeper pages survive: the poll refreshes the snapshot only.
    expect(calls(mock, '/trace')).toHaveLength(2);
    expect(screen.getByText('first_step')).toBeTruthy();
    expect(screen.getByText('deep_step')).toBeTruthy();
  });

  it('keeps a page the user loaded when a first-page refresh was already in flight', async () => {
    const timeout = vi.spyOn(globalThis, 'setTimeout');
    let releaseAppend: (value: Response) => void = () => {};
    let releaseRefresh: (value: Response) => void = () => {};
    const appendPending = new Promise<Response>((resolve) => { releaseAppend = resolve; });
    const refreshPending = new Promise<Response>((resolve) => { releaseRefresh = resolve; });
    let firstPageCalls = 0;
    const mock = stubFetch((url) => {
      if (url.includes('/api/seo/analyses/a-1/trace')) {
        if (url.includes('cursor=p1')) return appendPending;
        firstPageCalls += 1;
        return firstPageCalls === 1
          ? jsonResponse({ items: [traceStep(1, 'first_step')], next_cursor: 'p1' })
          : refreshPending;
      }
      if (url.includes('/api/seo/analyses/a-1')) return jsonResponse(snapshot({ status: 'running' }));
      if (url.includes('/api/seo/chats/')) {
        return jsonResponse(chatPage({
          chat: chat({ id: 'c1', running: true }), messages: [runMessage('a-1')]
        }));
      }
      return jsonResponse({ detail: 'Нет маршрута' }, 404);
    });
    render(Page, { props: { data: pageData({ chats: [chat({ id: 'c1', running: true })] }) } });

    await screen.findByText('Прогон SEO-анализа');
    await waitFor(() => expect(calls(mock, '/trace')).toHaveLength(1));
    await fireEvent.click(screen.getByRole('button', { name: /показать трассу/i }));
    await fireEvent.click(screen.getByRole('button', { name: /показать ещё/i }));
    await waitFor(() => expect(calls(mock, '/trace')).toHaveLength(2));

    // A poll starts its first-page refresh while the user's next page is on the wire.
    const scheduled = timeout.mock.calls.filter((call) => call[1] === 30_000);
    (scheduled[scheduled.length - 1][0] as () => void)();
    await waitFor(() => expect(calls(mock, '/trace')).toHaveLength(3));

    // The user's page lands first, then the older refresh: it must not undo it.
    releaseAppend(jsonResponse({ items: [traceStep(2, 'deep_step')], next_cursor: null }));
    await screen.findByText('deep_step');
    releaseRefresh(jsonResponse({ items: [traceStep(1, 'first_step')], next_cursor: 'p1' }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.getByText('deep_step')).toBeTruthy();
    expect(screen.getByText('first_step')).toBeTruthy();
  });

  it('cancels the run through the existing endpoint', async () => {
    const mock = stubFetch((url) => {
      if (url.endsWith('/cancel')) return jsonResponse(snapshot({ status: 'cancelled' }));
      if (url.includes('/api/seo/analyses/a-1/trace')) return jsonResponse({ items: [], next_cursor: null });
      if (url.includes('/api/seo/analyses/a-1')) return jsonResponse(snapshot({ status: 'running' }));
      if (url.includes('/api/seo/chats/')) {
        return jsonResponse(chatPage({
          chat: chat({ id: 'c1', running: true }), messages: [runMessage('a-1')]
        }));
      }
      return jsonResponse({ detail: 'Нет маршрута' }, 404);
    });
    render(Page, { props: { data: pageData({ chats: [chat({ id: 'c1', running: true })] }) } });

    await fireEvent.click(await screen.findByRole('button', { name: 'Отменить анализ' }));
    await waitFor(() => expect(calls(mock, '/cancel')).toHaveLength(1));
    const cancel = calls(mock, '/cancel')[0];
    expect(String(cancel[0])).toContain('/api/seo/analyses/a-1/cancel');
    expect(cancel[1]?.method).toBe('POST');
  });

  it('loads earlier messages with the cursor the server returned', async () => {
    const mock = stubFetch((url) => {
      if (url.includes('before=5')) {
        return jsonResponse(chatPage({ messages: [textMessage('первое', 'm1')], next_cursor: null }));
      }
      if (url.includes('/api/seo/chats/')) {
        return jsonResponse(chatPage({
          chat: chat({ id: 'c1' }), messages: [textMessage('второе', 'm2')], next_cursor: 5
        }));
      }
      return jsonResponse({ detail: 'Нет маршрута' }, 404);
    });
    render(Page, { props: { data: pageData({ chats: [chat({ id: 'c1' })] }) } });

    await screen.findByText('второе');
    await fireEvent.click(screen.getByRole('button', { name: /показать более ранние/i }));
    await waitFor(() => expect(calls(mock, '?before=5')).toHaveLength(1));
    expect(screen.getByText('первое')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /показать более ранние/i })).toBeNull();
  });

  it('replaces the proposal card after a connection is toggled', async () => {
    const mock = stubFetch((url, init) => {
      if (init.method === 'PUT') {
        return jsonResponse({
          chat: chat(), message: proposalMessage(['a'])
        });
      }
      if (url.includes('/api/seo/chats/')) {
        return jsonResponse(chatPage({ messages: [proposalMessage([])] }));
      }
      return jsonResponse({ detail: 'Нет маршрута' }, 404);
    });
    render(Page, { props: { data: pageData({ chats: [chat({ id: 'c1' })] }) } });

    const chip = await screen.findByRole('checkbox', { name: /Провайдер a/ }) as HTMLInputElement;
    expect(chip.checked).toBe(false);
    await fireEvent.click(chip);

    await waitFor(() => expect(calls(mock, '/proposal')).toHaveLength(1));
    const request = calls(mock, '/proposal')[0];
    expect(request[1]?.method).toBe('PUT');
    expect(JSON.parse(String(request[1]?.body))).toEqual({ connection_ids: ['a'] });
    await waitFor(() => expect(chip.checked).toBe(true));
  });

  it('deletes the active chat and resets the screen', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const mock = stubFetch((url, init) => {
      if (init.method === 'DELETE') return new Response(null, { status: 204 });
      if (url.includes('/api/seo/chats/')) {
        return jsonResponse(chatPage({ chat: chat({ id: 'c1' }), messages: [textMessage('привет')] }));
      }
      return jsonResponse({ detail: 'Нет маршрута' }, 404);
    });
    render(Page, { props: { data: pageData({ chats: [chat({ id: 'c1' })] }) } });

    await screen.findByText('привет');
    await fireEvent.click(screen.getByRole('button', { name: 'Удалить чат c1' }));

    await waitFor(() => expect(calls(mock, '/api/seo/chats/c1')).toHaveLength(2));
    const remove = calls(mock, '/api/seo/chats/c1').find((call) => call[1]?.method === 'DELETE');
    expect(remove).toBeTruthy();
    await waitFor(() => expect(screen.queryByText('привет')).toBeNull());
    expect(screen.queryByRole('button', { name: 'Открыть чат Цветы' })).toBeNull();
  });

  it('starts a new empty dialogue from the sidebar without creating a chat', async () => {
    const mock = stubFetch((url) => {
      if (url.includes('/api/seo/chats/')) {
        return jsonResponse(chatPage({ chat: chat({ id: 'c1' }), messages: [textMessage('привет')] }));
      }
      return jsonResponse({ detail: 'Нет маршрута' }, 404);
    });
    render(Page, { props: { data: pageData({ chats: [chat({ id: 'c1' })] }) } });

    await screen.findByText('привет');
    await fireEvent.click(screen.getByRole('button', { name: /новый чат/i }));
    await waitFor(() => expect(screen.queryByText('привет')).toBeNull());
    const creates = mock.mock.calls.filter(
      ([url, init]) => String(url).endsWith('/api/seo/chats') && init?.method === 'POST'
    );
    expect(creates).toHaveLength(0);
    expect(screen.getByText(/чат созда[её]тся при отправке первого сообщения/i)).toBeTruthy();
  });
});
