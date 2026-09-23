import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import CheckPage from './+page.svelte';
import { load as loadCheckPage } from './+page.server';
import SettingsPage from './settings/+page.svelte';
import type { PublicProvider } from '$lib/types';

const gigachat: PublicProvider = { id: 'gigachat', name: 'GigaChat', kind: 'gigachat', endpoint: null, model: 'GigaChat', configured: true };
const deepseek: PublicProvider = { id: 'deepseek', name: 'DeepSeek', kind: 'openai', endpoint: 'https://api.deepseek.com/chat/completions', model: 'deepseek-flash', configured: true };

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('shows an unconfigured model but does not allow selecting it', () => {
  render(CheckPage, { data: { providers: [{ ...deepseek, configured: false }], loadError: '' } });
  expect((screen.getByRole('checkbox', { name: /DeepSeek/ }) as HTMLInputElement).disabled).toBe(true);
  expect(screen.getByText(/Нужен API-ключ/)).toBeTruthy();
});

it('submits selected IDs and keeps results separate with hostile text escaped', async () => {
  const response = { brand: 'Ромашка', domain: '', checks: [
    { provider_id: 'gigachat', provider_name: 'GigaChat', summary: { successful: 1, failed: 0, mentioned: 1 }, results: [{ prompt: 'Где купить цветы?', answer: 'Ромашка', mentioned: true, error: null }] },
    { provider_id: 'deepseek', provider_name: 'DeepSeek', summary: { successful: 1, failed: 0, mentioned: 1 }, results: [{ prompt: 'Где купить цветы?', answer: '<script>alert(1)</script> Ромашка', mentioned: true, error: null }] }
  ] };
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(response), { headers: { 'content-type': 'application/json' } }));
  const view = render(CheckPage, { data: { providers: [gigachat, deepseek], loadError: '' } });
  await fireEvent.click(screen.getByRole('checkbox', { name: /DeepSeek/ }));
  await fireEvent.input(screen.getByLabelText(/Название бренда/), { target: { value: 'Ромашка' } });
  await fireEvent.input(screen.getByLabelText(/Вопросы клиентов/), { target: { value: 'Где купить цветы?' } });
  await fireEvent.click(screen.getByRole('button', { name: /Проверить бренд/ }));
  await waitFor(() => expect(screen.getByText('<script>alert(1)</script> Ромашка')).toBeTruthy());
  expect(view.container.querySelector('script')).toBeNull();
  expect(screen.getByRole('heading', { name: 'GigaChat' })).toBeTruthy();
  expect(screen.getByRole('heading', { name: 'DeepSeek' })).toBeTruthy();
  expect(view.container.querySelectorAll('.provider-report')).toHaveLength(2);
  const body = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
  expect(body.provider_ids).toEqual(['gigachat', 'deepseek']);
});

it('shows provider errors separately from missed mentions', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ brand: 'Ромашка', domain: '', checks: [
    { provider_id: 'gigachat', provider_name: 'GigaChat', summary: { successful: 0, failed: 1, mentioned: 0 }, results: [{ prompt: 'вопрос', answer: null, mentioned: null, error: 'Сервис недоступен' }] },
    { provider_id: 'deepseek', provider_name: 'DeepSeek', summary: { successful: 1, failed: 0, mentioned: 0 }, results: [{ prompt: 'вопрос', answer: 'Другой ответ', mentioned: false, error: null }] }
  ] }), { headers: { 'content-type': 'application/json' } }));
  render(CheckPage, { data: { providers: [gigachat, deepseek], loadError: '' } });
  await fireEvent.click(screen.getByRole('checkbox', { name: /DeepSeek/ }));
  await fireEvent.input(screen.getByLabelText(/Название бренда/), { target: { value: 'Ромашка' } });
  await fireEvent.input(screen.getByLabelText(/Вопросы клиентов/), { target: { value: 'вопрос' } });
  await fireEvent.click(screen.getByRole('button', { name: /Проверить бренд/ }));
  await waitFor(() => expect(screen.getByText('Сервис недоступен')).toBeTruthy());
  expect(screen.getAllByText('Ошибка')).toHaveLength(1);
  expect(screen.getAllByText('Нет упоминания')).toHaveLength(1);
});

it('rejects more than 20 prompts before calling the BFF', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch');
  render(CheckPage, { data: { providers: [gigachat], loadError: '' } });
  await fireEvent.input(screen.getByLabelText(/Название бренда/), { target: { value: 'Ромашка' } });
  await fireEvent.input(screen.getByLabelText(/Вопросы клиентов/), { target: { value: Array(21).fill('вопрос').join('\n') } });
  await fireEvent.click(screen.getByRole('button', { name: /Проверить бренд/ }));
  expect(screen.getByRole('alert').textContent).toMatch(/20/);
  expect(fetchMock).not.toHaveBeenCalled();
});

it('shows a readable message when the initial provider load fails', async () => {
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('private connection detail'));
  const data = await loadCheckPage();
  expect(data.providers).toEqual([]);
  expect(data.loadError).toMatch(/Python API/);
  render(CheckPage, { data });
  expect(screen.getByRole('alert').textContent).not.toContain('private connection detail');
});

it('shows preset and custom connections without rendering keys or hostile HTML', () => {
  const malicious = { ...deepseek, id: 'custom-1', name: '<img onerror=alert(1)>', configured: true };
  const view = render(SettingsPage, { data: { providers: [gigachat, deepseek, malicious], loadError: '' } });
  expect(screen.getByText('<img onerror=alert(1)>')).toBeTruthy();
  expect(view.container.querySelector('img')).toBeNull();
  expect(screen.getAllByText(/Готово к проверке/)).toHaveLength(3);
  expect(view.container.textContent).not.toContain('private-key');
});

it('locks preset metadata and sends only a blank-key-safe update', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(gigachat), { headers: { 'content-type': 'application/json' } }));
  render(SettingsPage, { data: { providers: [gigachat], loadError: '' } });
  await fireEvent.click(screen.getByRole('button', { name: /Настроить GigaChat/ }));
  expect((screen.getByLabelText('Название подключения') as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByLabelText('Адрес API') as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByLabelText('Модель') as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByLabelText('API-ключ') as HTMLInputElement).value).toBe('');
  await fireEvent.click(screen.getByRole('button', { name: 'Сохранить подключение' }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe('/api/providers/gigachat');
  expect(JSON.parse(init?.body as string)).toEqual({ scope: 'GIGACHAT_API_PERS' });
});

it('creates a custom OpenAI-compatible connection and keeps the key input empty afterwards', async () => {
  const custom = { ...deepseek, id: 'custom-1', name: 'Новая модель' };
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify(custom), { headers: { 'content-type': 'application/json' } }))
    .mockResolvedValueOnce(new Response(JSON.stringify([gigachat, custom]), { headers: { 'content-type': 'application/json' } }));
  render(SettingsPage, { data: { providers: [gigachat], loadError: '' } });
  await fireEvent.input(screen.getByLabelText('Название подключения'), { target: { value: 'Новая модель' } });
  await fireEvent.input(screen.getByLabelText('Адрес API'), { target: { value: 'https://api.example.com/chat/completions' } });
  await fireEvent.input(screen.getByLabelText('Модель'), { target: { value: 'model-1' } });
  await fireEvent.input(screen.getByLabelText('API-ключ'), { target: { value: 'private-key' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Сохранить подключение' }));
  await waitFor(() => expect(screen.getByText('Новая модель')).toBeTruthy());
  expect(fetchMock.mock.calls[0][0]).toBe('/api/providers');
  expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({ name: 'Новая модель', kind: 'openai', endpoint: 'https://api.example.com/chat/completions', model: 'model-1', api_key: 'private-key' });
  expect((screen.getByLabelText('API-ключ') as HTMLInputElement).value).toBe('');
  expect(document.body.textContent).not.toContain('private-key');
});

it('deletes a custom connection and resets a preset key', async () => {
  const custom = { ...deepseek, id: 'custom-1', name: 'Сторонняя модель' };
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ deleted: true }), { headers: { 'content-type': 'application/json' } }))
    .mockResolvedValueOnce(new Response(JSON.stringify([gigachat, deepseek]), { headers: { 'content-type': 'application/json' } }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ deleted: true }), { headers: { 'content-type': 'application/json' } }))
    .mockResolvedValueOnce(new Response(JSON.stringify([gigachat, { ...deepseek, configured: false }]), { headers: { 'content-type': 'application/json' } }));
  vi.stubGlobal('confirm', () => true);
  render(SettingsPage, { data: { providers: [gigachat, deepseek, custom], loadError: '' } });
  await fireEvent.click(screen.getByRole('button', { name: /Удалить Сторонняя модель/ }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(fetchMock.mock.calls[0][0]).toBe('/api/providers/custom-1');
  expect(fetchMock.mock.calls[0][1]?.method).toBe('DELETE');
  await fireEvent.click(screen.getByRole('button', { name: /Сбросить ключ DeepSeek/ }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
  expect(fetchMock.mock.calls[2][0]).toBe('/api/providers/deepseek');
  vi.unstubAllGlobals();
});

it('shows a failed save without leaking the entered key', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ detail: 'Адрес API недоступен' }), { status: 400, headers: { 'content-type': 'application/json' } }));
  render(SettingsPage, { data: { providers: [gigachat], loadError: '' } });
  await fireEvent.input(screen.getByLabelText('Название подключения'), { target: { value: 'Тест' } });
  await fireEvent.input(screen.getByLabelText('Адрес API'), { target: { value: 'https://api.example.com/chat/completions' } });
  await fireEvent.input(screen.getByLabelText('Модель'), { target: { value: 'model-1' } });
  await fireEvent.input(screen.getByLabelText('API-ключ'), { target: { value: 'private-key' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Сохранить подключение' }));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/Адрес API недоступен/));
  expect(document.body.textContent).not.toContain('private-key');
});
