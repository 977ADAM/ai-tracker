/**
 * Shared vocabulary of the SEO agent runtime: the five agents, their Russian
 * labels, and the rule that distinguishes an agent run from a pre-agent run.
 */
import type { SeoAgent, SeoAgentStatus } from './types';

/** The five agents in their fixed supervisor-to-specialist order. */
export const SEO_AGENT_LABELS: readonly { id: string; label: string }[] = [
  { id: 'supervisor', label: 'Супервизор' },
  { id: 'site', label: 'Агент сайта' },
  { id: 'competitors', label: 'Агент конкурентов' },
  { id: 'queries', label: 'Агент запросов' },
  { id: 'checks', label: 'Агент проверок' }
];

export const SEO_AGENT_STATUS_LABELS: Record<SeoAgentStatus, string> = {
  pending: 'Ожидает',
  running: 'Выполняется',
  waiting: 'Ждёт',
  done: 'Готово',
  error: 'Ошибка',
  skipped: 'Пропущен'
};

/** The Russian label of an agent; an unknown id is shown as the backend sent it. */
export function seoAgentLabel(id: string): string {
  return SEO_AGENT_LABELS.find((entry) => entry.id === id)?.label ?? id;
}

/**
 * Whether the snapshot carries real agent state.
 *
 * Analyses created before the agent runtime have no agents: the backend answers
 * with five `pending` rows whose `updated_at` is null, and the real progress
 * lives in `stages`. Such a snapshot must keep the old stage list.
 */
export function hasAgentState(agents: SeoAgent[] | undefined): boolean {
  if (!agents || agents.length === 0) return false;
  return agents.some((agent) => agent.status !== 'pending' || agent.updated_at !== null);
}
