<script lang="ts">
  import { base } from '$app/paths';
  import { onDestroy, onMount, untrack } from 'svelte';
  import ChatSidebar from '$lib/components/ChatSidebar.svelte';
  import ChatFeed from '$lib/components/ChatFeed.svelte';
  import ChatComposer from '$lib/components/ChatComposer.svelte';
  import type {
    ChatCreated, ChatMessage, ChatMessages, ChatPage, ChatProposal, ChatProposalUpdated, ChatSummary,
    PublicProvider, SeoAnalysisSnapshot, SeoModelRow, SeoRowsKind, SeoRowsPage, SeoSearchRow,
    SeoTracePage, SeoTraceStep
  } from '$lib/types';

  type TraceState = { steps: SeoTraceStep[]; cursor: string | null; loading: boolean; error: string };
  type RowsState = { model: SeoModelRow[]; search: SeoSearchRow[] };
  type CursorsState = { model: string | null; search: string | null };

  type Data = {
    providers: PublicProvider[];
    chats: ChatSummary[];
    chatsError: string;
    loadError: string;
  };
  let { data }: { data: Data } = $props();

  const POLL_INTERVAL_MS = 30_000;
  const EMPTY_ROWS: RowsState = { model: [], search: [] };
  const EMPTY_CURSORS: CursorsState = { model: null, search: null };
  const EMPTY_TRACE: TraceState = { steps: [], cursor: null, loading: false, error: '' };

  /**
   * The chat screen owns one dialogue and the resources its runs use. Report
   * rows, the agent trace and the cancellation flag are keyed by analysis id,
   * because one chat can hold several runs and the feed shows them together.
   */
  let chats = $state<ChatSummary[]>(untrack(() => data.chats));
  let chatsError = $state(untrack(() => data.chatsError));
  let error = $state(untrack(() => data.loadError));
  let runError = $state('');
  let activeId = $state<string | null>(null);
  let messages = $state<ChatMessage[]>([]);
  let snapshots = $state<Record<string, SeoAnalysisSnapshot>>({});
  let traces = $state<Record<string, TraceState>>({});
  let rows = $state<Record<string, RowsState>>({});
  let cursors = $state<Record<string, CursorsState>>({});
  let loadingRows = $state<Record<string, SeoRowsKind | null>>({});
  let rowErrors = $state<Record<string, string>>({});
  let olderCursor = $state<number | null>(null);
  let loadingOlder = $state(false);
  let cancellingId = $state<string | null>(null);
  let sending = $state(false);
  let composerHost = $state<HTMLElement | null>(null);

  let destroyed = false;
  const pollTimers = new Map<string, ReturnType<typeof setTimeout>>();
  /** Which chat started each analysis, so a finished run clears its live flag. */
  const analysisChat = new Map<string, string>();
  /** Analyses whose trace the user paged past the first page: a poll must not collapse it. */
  const tracePaged = new Set<string>();

  function detail(value: unknown, fallback: string): string {
    return value !== null && typeof value === 'object' && 'detail' in value && typeof value.detail === 'string'
      ? value.detail : fallback;
  }
  async function payload(response: Response): Promise<unknown> {
    try { return await response.json(); }
    catch { return null; }
  }

  /** The analysis a run message points at; a malformed card owns no run. */
  function analysisIdOf(message: ChatMessage): string | null {
    if (message.kind !== 'run' || !message.payload) return null;
    const value = (message.payload as Record<string, unknown>).analysis_id;
    return typeof value === 'string' && value.length > 0 ? value : null;
  }

  /** The proposal of a message, or null for a card that carries something else. */
  function proposalOf(message: ChatMessage | undefined): ChatProposal | null {
    if (!message || message.kind !== 'proposal' || !message.payload) return null;
    const value = message.payload as Partial<ChatProposal>;
    return Array.isArray(value.connection_ids) ? (value as ChatProposal) : null;
  }

  function applyChat(chat: ChatSummary): void {
    chats = chats.some((item) => item.id === chat.id)
      ? chats.map((item) => (item.id === chat.id ? chat : item))
      : [chat, ...chats];
  }

  /** A finished run is no longer a reason to keep its chat locked for deletion. */
  function markChatStopped(chatId: string | null): void {
    if (chatId === null) return;
    chats = chats.map((item) => (item.id === chatId ? { ...item, running: false } : item));
  }

  function replaceMessage(message: ChatMessage): void {
    messages = messages.map((item) => (item.id === message.id ? message : item));
  }

  function stopPolling(id?: string): void {
    if (id === undefined) {
      for (const timer of pollTimers.values()) clearTimeout(timer);
      pollTimers.clear();
      return;
    }
    const timer = pollTimers.get(id);
    if (timer !== undefined) { clearTimeout(timer); pollTimers.delete(id); }
  }

  /** The one interval of the screen: the same 30 seconds the old page used. */
  function schedulePoll(id: string): void {
    stopPolling(id);
    pollTimers.set(id, setTimeout(() => { pollTimers.delete(id); void loadSnapshot(id); }, POLL_INTERVAL_MS));
  }

  async function loadSnapshot(id: string): Promise<void> {
    try {
      const response = await fetch(`${base}/api/seo/analyses/${encodeURIComponent(id)}`);
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось загрузить прогон'));
      // The chat may have been left while the request was in flight.
      if (destroyed || analysisChat.get(id) !== activeId) return;
      const current = value as SeoAnalysisSnapshot;
      snapshots = { ...snapshots, [id]: current };
      runError = '';
      // Only a live run is polled; a terminal one stops until the chat is reopened.
      if (current.status === 'running') { void syncTrace(id); schedulePoll(id); }
      else { stopPolling(id); markChatStopped(analysisChat.get(id) ?? null); }
    } catch (cause) {
      if (destroyed || analysisChat.get(id) !== activeId) return;
      runError = cause instanceof Error ? cause.message : 'Не удалось загрузить прогон';
      // A transient failure must not freeze the progress screen.
      schedulePoll(id);
    }
  }

  /**
   * Restore the live state of every run in the feed: an unknown analysis is
   * loaded, a running one keeps polling, a finished one stops at once.
   */
  function trackRuns(list: ChatMessage[], chatId: string): void {
    for (const message of list) {
      const id = analysisIdOf(message);
      if (id === null) continue;
      analysisChat.set(id, chatId);
      const known = snapshots[id];
      if (known === undefined) void loadSnapshot(id);
      else if (known.status === 'running') schedulePoll(id);
      else { stopPolling(id); markChatStopped(chatId); }
    }
  }

  function resetAnalysisState(): void {
    stopPolling();
    snapshots = {};
    traces = {};
    rows = {};
    cursors = {};
    loadingRows = {};
    rowErrors = {};
    cancellingId = null;
    runError = '';
    tracePaged.clear();
  }

  async function loadRows(id: string, kind: SeoRowsKind, cursor: string | null, append: boolean): Promise<void> {
    loadingRows = { ...loadingRows, [id]: kind };
    try {
      const query = cursor === null ? `kind=${kind}` : `kind=${kind}&cursor=${encodeURIComponent(cursor)}`;
      const response = await fetch(`${base}/api/seo/analyses/${encodeURIComponent(id)}/rows?${query}`);
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось загрузить строки отчёта'));
      if (destroyed) return;
      const page = value as SeoRowsPage;
      const current = rows[id] ?? EMPTY_ROWS;
      if (kind === 'model') {
        const items = page.items as SeoModelRow[];
        rows = { ...rows, [id]: { model: append ? [...current.model, ...items] : items, search: current.search } };
      } else {
        const items = page.items as SeoSearchRow[];
        rows = { ...rows, [id]: { model: current.model, search: append ? [...current.search, ...items] : items } };
      }
      cursors = { ...cursors, [id]: { ...(cursors[id] ?? EMPTY_CURSORS), [kind]: page.next_cursor } };
      rowErrors = { ...rowErrors, [id]: '' };
    } catch (cause) {
      if (destroyed) return;
      rowErrors = { ...rowErrors, [id]: cause instanceof Error ? cause.message : 'Не удалось загрузить строки отчёта' };
    } finally {
      if (!destroyed && loadingRows[id] === kind) loadingRows = { ...loadingRows, [id]: null };
    }
  }

  async function loadTrace(id: string, cursor: string | null, append: boolean): Promise<void> {
    // The pages the user loaded are the newer state, so a first-page request
    // for a trace they already deepened paints nothing. It returns before the
    // flag is raised: a stranded `loading` would leave the feed's "load more"
    // control disabled on "Загружаем…" for the rest of the session.
    if (!append && tracePaged.has(id)) return;
    traces = { ...traces, [id]: { ...(traces[id] ?? EMPTY_TRACE), loading: true, error: '' } };
    try {
      const query = cursor === null ? '' : `?cursor=${encodeURIComponent(cursor)}`;
      const response = await fetch(`${base}/api/seo/analyses/${encodeURIComponent(id)}/trace${query}`);
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось загрузить трассу агентов'));
      if (destroyed) return;
      // A first-page refresh that was already in flight must not undo a page
      // the user loaded while it travelled: their state is the newer one. This
      // attempt paints nothing, so release the flag it raised on the way in.
      if (!append && tracePaged.has(id)) {
        const pending = traces[id];
        if (pending !== undefined && pending.loading) {
          traces = { ...traces, [id]: { ...pending, loading: false } };
        }
        return;
      }
      const page = value as SeoTracePage;
      const current = traces[id] ?? EMPTY_TRACE;
      traces = { ...traces, [id]: {
        steps: append ? [...current.steps, ...page.items] : page.items,
        cursor: page.next_cursor, loading: false, error: ''
      } };
      // The user asked for more than the first page; a later poll leaves it be.
      if (append) tracePaged.add(id);
    } catch (cause) {
      if (destroyed) return;
      const current = traces[id] ?? EMPTY_TRACE;
      traces = { ...traces, [id]: {
        ...current, loading: false,
        error: cause instanceof Error ? cause.message : 'Не удалось загрузить трассу агентов'
      } };
    }
  }

  /**
   * The live card shows the stages, the agents and the agent trace, so the
   * first trace page is read whenever a running snapshot arrives: once as the
   * run appears and again on every 30-second poll, which is what makes new
   * steps show up without a reload. A trace the user already paged deeper is
   * left exactly as they loaded it. A trace failure stays best-effort: it only
   * paints the feed's own error and never blocks the progress card.
   */
  async function syncTrace(id: string): Promise<void> {
    if (tracePaged.has(id)) return;
    await loadTrace(id, null, false);
  }

  /**
   * Opening a report reads saved data only, and the trace comes with it: an
   * empty feed shows no "load more", so the first page must be requested here.
   * A trace the user already paged deeper is theirs: asking for its first page
   * would collapse their pages (and would leave the feed loading, see above).
   */
  function openReport(id: string): void {
    const requests = [loadRows(id, 'model', null, false), loadRows(id, 'search', null, false)];
    if (!tracePaged.has(id)) requests.push(loadTrace(id, null, false));
    void Promise.all(requests);
  }

  async function openChat(id: string): Promise<void> {
    error = '';
    resetAnalysisState();
    activeId = id;
    messages = [];
    olderCursor = null;
    loadingOlder = false;
    try {
      const response = await fetch(`${base}/api/seo/chats/${encodeURIComponent(id)}`);
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось открыть чат'));
      if (destroyed || activeId !== id) return;
      const page = value as ChatPage;
      messages = page.messages;
      olderCursor = page.next_cursor;
      applyChat(page.chat);
      trackRuns(page.messages, id);
    } catch (cause) {
      if (destroyed || activeId !== id) return;
      error = cause instanceof Error ? cause.message : 'Не удалось открыть чат';
    }
  }

  /** A new dialogue has no row in the database yet: the first message creates it. */
  function newChat(): void {
    error = '';
    resetAnalysisState();
    activeId = null;
    messages = [];
    olderCursor = null;
    loadingOlder = false;
  }

  async function loadOlder(): Promise<void> {
    const id = activeId;
    if (id === null || olderCursor === null || loadingOlder) return;
    loadingOlder = true;
    error = '';
    try {
      const response = await fetch(`${base}/api/seo/chats/${encodeURIComponent(id)}?before=${olderCursor}`);
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось загрузить более ранние сообщения'));
      if (destroyed || activeId !== id) return;
      const page = value as ChatPage;
      messages = [...page.messages, ...messages];
      olderCursor = page.next_cursor;
      trackRuns(page.messages, id);
    } catch (cause) {
      if (destroyed || activeId !== id) return;
      error = cause instanceof Error ? cause.message : 'Не удалось загрузить более ранние сообщения';
    } finally {
      if (!destroyed) loadingOlder = false;
    }
  }

  async function createChat(): Promise<ChatSummary> {
    const response = await fetch(`${base}/api/seo/chats`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}'
    });
    const value = await payload(response);
    if (!response.ok) throw new Error(detail(value, 'Не удалось создать чат'));
    return (value as ChatCreated).chat;
  }

  /**
   * The composer clears its field as it hands the text over, and its contract
   * has no way to be fed a value back. A failed send must not cost the user the
   * message, so the text goes back into the field it came from.
   */
  function restoreDraft(text: string): void {
    const field = composerHost?.querySelector('textarea');
    if (!field) return;
    field.value = text;
    field.dispatchEvent(new Event('input', { bubbles: true }));
  }

  async function send(text: string): Promise<void> {
    if (sending) return;
    sending = true;
    error = '';
    try {
      let chatId = activeId;
      if (chatId === null) {
        const created = await createChat();
        if (destroyed) return;
        chatId = created.id;
        activeId = chatId;
        applyChat(created);
      }
      const response = await fetch(`${base}/api/seo/chats/${encodeURIComponent(chatId)}/messages`, {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text })
      });
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось отправить сообщение'));
      if (destroyed) return;
      const answer = value as ChatMessages;
      applyChat(answer.chat);
      messages = [...messages, ...answer.messages];
      trackRuns(answer.messages, chatId);
    } catch (cause) {
      if (destroyed) return;
      error = cause instanceof Error ? cause.message : 'Не удалось отправить сообщение';
      restoreDraft(text);
    } finally {
      if (!destroyed) sending = false;
    }
  }

  async function toggleConnection(messageId: string, connectionId: string): Promise<void> {
    const chatId = activeId;
    if (chatId === null) return;
    const current = proposalOf(messages.find((item) => item.id === messageId));
    if (current === null) return;
    const selected = new Set(current.connection_ids);
    if (selected.has(connectionId)) selected.delete(connectionId);
    else selected.add(connectionId);
    error = '';
    try {
      const response = await fetch(`${base}/api/seo/chats/${encodeURIComponent(chatId)}/proposal`, {
        method: 'PUT', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ connection_ids: [...selected] })
      });
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось изменить подключения'));
      if (destroyed || activeId !== chatId) return;
      const updated = value as ChatProposalUpdated;
      replaceMessage(updated.message);
      applyChat(updated.chat);
    } catch (cause) {
      if (destroyed) return;
      error = cause instanceof Error ? cause.message : 'Не удалось изменить подключения';
    }
  }

  async function cancelRun(id: string): Promise<void> {
    if (cancellingId !== null) return;
    cancellingId = id;
    runError = '';
    try {
      const response = await fetch(`${base}/api/seo/analyses/${encodeURIComponent(id)}/cancel`, { method: 'POST' });
      const value = await payload(response);
      if (!response.ok) throw new Error(detail(value, 'Не удалось отменить прогон'));
      if (destroyed) return;
      const current = value as SeoAnalysisSnapshot;
      snapshots = { ...snapshots, [id]: current };
      stopPolling(id);
      markChatStopped(analysisChat.get(id) ?? activeId);
    } catch (cause) {
      if (destroyed) return;
      runError = cause instanceof Error ? cause.message : 'Не удалось отменить прогон';
    } finally {
      if (!destroyed) cancellingId = null;
    }
  }

  async function removeChat(id: string): Promise<void> {
    error = '';
    try {
      const response = await fetch(`${base}/api/seo/chats/${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(detail(await payload(response), 'Не удалось удалить чат'));
      if (destroyed) return;
      chats = chats.filter((item) => item.id !== id);
      if (activeId === id) newChat();
    } catch (cause) {
      if (destroyed) return;
      error = cause instanceof Error ? cause.message : 'Не удалось удалить чат';
    }
  }

  onMount(() => {
    // The list comes newest first, so the first row is the freshest chat.
    const newest = chats[0];
    if (newest) void openChat(newest.id);
  });
  onDestroy(() => { destroyed = true; stopPolling(); });
</script>

<svelte:head><title>ИИ-трекинг · Чат SEO-анализа</title></svelte:head>

<main class="mx-auto w-full max-w-[1920px] px-4 pb-16 sm:px-6 lg:px-8">
    <nav aria-label="Хлебные крошки" class="flex items-center gap-2 py-4 text-xs font-medium text-muted">
        <a href={base || '/'} class="hover:text-accent">Инструменты</a>
        <span aria-hidden="true">/</span>
        <span class="text-ink">SEO-анализ сайта</span>
    </nav>

    {#if data.loadError}
        <p role="alert" class="mt-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {data.loadError}
        </p>
    {/if}

    {#if chatsError}
        <p role="alert" class="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            {chatsError}
        </p>
    {/if}

    <div class="grid gap-6 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)] lg:items-start">
        <ChatSidebar
            {chats}
            {activeId}
            busy={sending}
            onSelect={(id) => void openChat(id)}
            onCreate={newChat}
            onDelete={(id) => void removeChat(id)}
        />

        <section class="min-w-0" aria-labelledby="chat-dialogue-title">
            <h2 id="chat-dialogue-title" class="text-xl font-bold tracking-tight">Диалог</h2>

            {#if error}
                <p role="alert" class="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
                    {error}
                </p>
            {/if}

            {#if runError}
                <p role="alert" class="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
                    {runError}
                </p>
            {/if}

            {#if activeId === null}
                <p class="mt-3 rounded-2xl border border-dashed border-line bg-white px-5 py-4 text-sm leading-6 text-muted" data-chat-empty>
                    Опишите задачу в поле ниже: адрес сайта, сферу бизнеса, ключевые запросы и услуги. Чат создаётся при отправке первого сообщения.
                </p>
            {/if}

            <div class="mt-4">
                <ChatFeed
                    {messages}
                    providers={data.providers}
                    {snapshots}
                    {traces}
                    {rows}
                    {cursors}
                    {loadingRows}
                    errors={rowErrors}
                    {cancellingId}
                    {olderCursor}
                    {loadingOlder}
                    onLoadOlder={() => void loadOlder()}
                    onOpenReport={openReport}
                    onToggleConnection={(messageId, connectionId) => void toggleConnection(messageId, connectionId)}
                    onCancel={(id) => void cancelRun(id)}
                    onLoadRows={(id, kind, cursor) => void loadRows(id, kind, cursor, true)}
                    onLoadTrace={(id, cursor) => void loadTrace(id, cursor, true)}
                />
            </div>

            <div bind:this={composerHost}>
                <ChatComposer disabled={!!data.loadError} busy={sending} onSend={(text) => void send(text)} />
            </div>
        </section>
    </div>
</main>
