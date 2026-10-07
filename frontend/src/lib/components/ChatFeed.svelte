<script lang="ts">
  import type {
    ChatMessage, PublicProvider, SeoAnalysisSnapshot, SeoModelRow, SeoRowsKind, SeoSearchRow, SeoTraceStep
  } from '$lib/types';
  import ChatRun from './ChatRun.svelte';
  import ChatMessageCard from './ChatMessage.svelte';
  import ChatProposalCard from './ChatProposal.svelte';

  type RowsState = { model: SeoModelRow[]; search: SeoSearchRow[] };
  type CursorsState = { model: string | null; search: string | null };
  type TraceState = { steps: SeoTraceStep[]; cursor: string | null; loading: boolean; error: string };

  const EMPTY_ROWS: RowsState = { model: [], search: [] };
  const EMPTY_CURSORS: CursorsState = { model: null, search: null };
  const EMPTY_TRACE: TraceState = { steps: [], cursor: null, loading: false, error: '' };

  /**
   * The message feed. Every message is routed to the card that owns its kind;
   * an unknown kind renders nothing, so a message written by a newer backend
   * can never break the whole transcript. The per-analysis resources (report
   * rows, trace, cancellation) arrive keyed by analysis id, because one chat
   * can hold several runs.
   */
  let {
    messages,
    providers,
    snapshots,
    traces = {},
    rows = {},
    cursors = {},
    loadingRows = {},
    errors = {},
    cancellingId = null,
    olderCursor = null,
    loadingOlder = false,
    onToggleConnection,
    onCancel,
    onLoadRows = () => {},
    onLoadTrace = () => {},
    onOpenReport = () => {},
    onLoadOlder = () => {}
  }: {
    messages: ChatMessage[];
    providers: PublicProvider[];
    snapshots: Record<string, SeoAnalysisSnapshot>;
    traces?: Record<string, TraceState>;
    rows?: Record<string, RowsState>;
    cursors?: Record<string, CursorsState>;
    loadingRows?: Record<string, SeoRowsKind | null>;
    errors?: Record<string, string>;
    cancellingId?: string | null;
    olderCursor?: number | null;
    loadingOlder?: boolean;
    onToggleConnection: (messageId: string, connectionId: string) => void;
    onCancel: (analysisId: string) => void;
    onLoadRows?: (analysisId: string, kind: SeoRowsKind, cursor: string | null) => void;
    onLoadTrace?: (analysisId: string, cursor: string | null) => void;
    onOpenReport?: (analysisId: string) => void;
    onLoadOlder?: () => void;
  } = $props();

  let feedElement = $state<HTMLElement | null>(null);
  /** The message the feed last scrolled to; prepending older ones must not move it. */
  let newestId: string | null = null;

  const connectionNames = $derived(Object.fromEntries(providers.map((provider) => [provider.id, provider.name])));

  function traceOf(analysisId: string): TraceState {
    return traces[analysisId] ?? EMPTY_TRACE;
  }

  function rowsOf(analysisId: string): RowsState {
    return rows[analysisId] ?? EMPTY_ROWS;
  }

  function cursorsOf(analysisId: string): CursorsState {
    return cursors[analysisId] ?? EMPTY_CURSORS;
  }

  /** The analysis a run card points at; a malformed card renders nothing. */
  function runId(message: ChatMessage): string | null {
    if (message.kind !== 'run' || !message.payload) return null;
    const value = (message.payload as Record<string, unknown>).analysis_id;
    return typeof value === 'string' && value.length > 0 ? value : null;
  }

  // A new message is what the user is waiting for, so the feed follows it; a
  // page of older messages is inserted above the view and must not move it.
  $effect(() => {
    const newest = messages.length > 0 ? messages[messages.length - 1].id : null;
    if (newest === newestId) return;
    newestId = newest;
    if (feedElement) feedElement.scrollTop = feedElement.scrollHeight;
  });
</script>

<div
  bind:this={feedElement}
  data-chat-feed
  role="log"
  aria-label="Лента сообщений"
  class="flex max-h-[60vh] min-h-64 flex-col gap-4 overflow-y-auto rounded-3xl border border-line bg-canvas/30 px-4 py-5 sm:px-5"
>
  {#if olderCursor !== null}
    <div class="flex justify-center">
      <button
        type="button"
        onclick={onLoadOlder}
        disabled={loadingOlder}
        class="inline-flex min-h-11 items-center rounded-xl border border-line bg-white px-5 py-2.5 text-sm font-semibold text-ink hover:border-accent disabled:opacity-50"
      >
        {loadingOlder ? 'Загружаем…' : 'Показать более ранние'}
      </button>
    </div>
  {/if}

  {#if messages.length === 0}
    <p class="px-1 py-8 text-center text-sm text-muted">Сообщений пока нет. Напишите первое сообщение о сайте.</p>
  {:else}
    {#each messages as message (message.id)}
      {@const analysisId = message.kind === 'run' ? runId(message) : null}
      {#if message.kind === 'text'}
        <ChatMessageCard {message} />
      {:else if message.kind === 'proposal'}
        <ChatProposalCard
          {message}
          {providers}
          onToggle={(connectionId) => onToggleConnection(message.id, connectionId)}
        />
      {:else if analysisId}
        <ChatRun
          snapshot={snapshots[analysisId] ?? null}
          {analysisId}
          cancelling={cancellingId === analysisId}
          rows={rowsOf(analysisId)}
          cursors={cursorsOf(analysisId)}
          loadingRows={loadingRows[analysisId] ?? null}
          traces={traceOf(analysisId)}
          {connectionNames}
          error={errors[analysisId] ?? ''}
          onCancel={() => onCancel(analysisId)}
          onMoreRows={(kind) => onLoadRows(analysisId, kind, cursorsOf(analysisId)[kind])}
          onMoreTrace={() => onLoadTrace(analysisId, traceOf(analysisId).cursor)}
          onOpenReport={() => onOpenReport(analysisId)}
        />
      {/if}
    {/each}
  {/if}
</div>
