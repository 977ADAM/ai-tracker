/**
 * Client-side helpers of the chat screen: the short status of a chat row and
 * the text of a message. Both are pure projections of the server payload — the
 * chat state itself is computed by the backend and never re-derived here.
 */
import type { ChatMessage, ChatSummary } from './types';

/** The label of a chat row in the sidebar. */
export function statusLabel(chat: ChatSummary): string {
  return chat.running ? 'Идёт прогон' : 'Готов';
}

/**
 * The text of a message, or `null` when there is nothing to show: card messages
 * (`proposal`/`run`) carry no text of their own, and whitespace alone is not an
 * answer.
 */
export function messageText(message: ChatMessage): string | null {
  const text = message.text?.trim();
  return text ? text : null;
}
