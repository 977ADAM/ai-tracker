import { writable } from 'svelte/store';
export const notification = writable<{ id: number; text: string } | null>(null);
let sequence = 0;
export function notify(text: string) {
  if (typeof window !== 'undefined') notification.set({ id: ++sequence, text });
}
export function dismissNotification() {
  notification.set(null);
}
