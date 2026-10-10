// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, expect, it } from 'vitest';
import { tick } from 'svelte';
import { notify, dismissNotification } from '$lib/notifications';
import NotificationToast from './NotificationToast.svelte';
afterEach(() => {
  cleanup();
  dismissNotification();
});
it('announces a successful action and allows dismissing it', async () => {
  render(NotificationToast);
  notify('Замер запущен');
  await tick();
  expect(screen.getByRole('status').textContent).toContain('Замер запущен');
  await fireEvent.click(screen.getByRole('button', { name: 'Закрыть уведомление' }));
  expect(screen.queryByText('Замер запущен')).toBeNull();
});
it('retains feedback when the page content changes', async () => {
  notify('Настройки проекта сохранены');
  render(NotificationToast);
  await tick();
  expect(screen.getByText('Настройки проекта сохранены')).toBeTruthy();
});
