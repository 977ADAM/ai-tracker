<script lang="ts">
  import type { ChatMessage, ChatPayload, ChatProposal, PublicProvider } from '$lib/types';
  import { MAX_CONNECTIONS } from '$lib/seo-form';

  let {
    message,
    providers,
    busy = false,
    onToggle
  }: {
    message: ChatMessage;
    providers: PublicProvider[];
    busy?: boolean;
    onToggle: (connectionId: string) => void;
  } = $props();

  /** Every key the card reads; a run payload carries `analysis_id` instead. */
  const PROPOSAL_KEYS = [
    'status', 'url', 'sphere', 'seeds', 'services', 'connection_ids',
    'search_upper', 'model_upper', 'generated_limit'
  ] as const;

  /**
   * `payload` is `ChatProposal | ChatRunRef | null`, so the card narrows it by
   * shape instead of casting: a run payload or a malformed card renders nothing.
   */
  function isProposal(payload: ChatPayload | null): payload is ChatProposal {
    return !!payload && PROPOSAL_KEYS.every((key) => key in payload);
  }

  const proposal = $derived.by(() => {
    const payload = message.payload;
    return message.kind === 'proposal' && isProposal(payload) ? payload : null;
  });
  const superseded = $derived(proposal?.status === 'superseded');
  const confirmed = $derived(proposal?.status === 'confirmed');
  // A superseded proposal was replaced and a confirmed one is already spent by
  // the run, so neither may change its connections; `busy` covers the request.
  const blocked = $derived(busy || superseded || confirmed);
  const selected = $derived(new Set(proposal?.connection_ids ?? []));
  // The card is the only place a connection is chosen, so it lists the usable
  // ones only and never more than the run's own limit.
  const chips = $derived(providers.filter((provider) => provider.configured).slice(0, MAX_CONNECTIONS));
  const statusLabel = $derived(superseded ? 'Устарело' : confirmed ? 'Подтверждено' : 'Ожидает подтверждения');
  const statusClass = $derived(
    superseded
      ? 'border-line bg-canvas text-muted'
      : confirmed
        ? 'border-accent/40 bg-accent-soft text-accent-dark'
        : 'border-line bg-canvas/70 text-muted'
  );

  const term = 'text-xs font-semibold text-muted';
  const value = 'mt-1 text-sm leading-6 text-ink';
</script>

{#if proposal}
  <article
    data-chat-proposal
    data-status={proposal.status}
    aria-label="Предложение параметров SEO-анализа"
    class={`rounded-3xl border border-line px-5 py-4 shadow-sm ${superseded ? 'bg-canvas opacity-60' : 'bg-white'}`}
  >
    <header class="flex flex-wrap items-center gap-x-3 gap-y-2">
      <h3 class="text-sm font-bold text-ink">Параметры SEO-анализа</h3>
      <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${statusClass}`}>{statusLabel}</span>
    </header>

    <dl class="mt-4 grid gap-4 sm:grid-cols-2">
      <div class="min-w-0">
        <dt class={term}>Адрес сайта</dt>
        <dd class={`${value} break-words`}>{proposal.url}</dd>
      </div>
      <div class="min-w-0">
        <dt class={term}>Сфера бизнеса</dt>
        <dd class={`${value} break-words`}>{proposal.sphere}</dd>
      </div>
      <div class="min-w-0">
        <dt class={term}>Ключевые запросы</dt>
        <dd>
          <ul class="mt-1 space-y-1 text-sm leading-6 text-ink">
            {#each proposal.seeds as seed}
              <li class="break-words">{seed}</li>
            {/each}
          </ul>
        </dd>
      </div>
      <div class="min-w-0">
        <dt class={term}>Услуги</dt>
        <dd>
          <ul class="mt-1 space-y-1 text-sm leading-6 text-ink">
            {#each proposal.services as service}
              <li class="break-words">{service}</li>
            {/each}
          </ul>
        </dd>
      </div>
    </dl>

    <p class="mt-4 border-t border-line pt-4 text-sm leading-6 text-ink">
      Оценка: не больше {proposal.search_upper} поисковых запросов и {proposal.model_upper} ответов моделей.
    </p>

    <fieldset class="mt-4 border-t border-line pt-4">
      <legend class={term}>Подключения моделей</legend>
      <div class="mt-2 flex flex-wrap gap-2">
        {#each chips as provider (provider.id)}
          <label
            class={`inline-flex items-center gap-2 rounded-full border border-line bg-canvas/50 px-3 py-1.5 text-sm text-ink ${blocked ? 'cursor-not-allowed opacity-60' : 'cursor-pointer hover:border-accent/50'}`}
          >
            <input
              type="checkbox"
              class="size-4 accent-accent"
              checked={selected.has(provider.id)}
              disabled={blocked}
              onchange={() => {
                if (!blocked) onToggle(provider.id);
              }}
            />
            <span class="font-semibold">{provider.name}</span>
          </label>
        {/each}
      </div>
    </fieldset>
  </article>
{/if}
