// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { invalidateAll } from '$app/navigation';
import SeoSettingsPanel from './SeoSettingsPanel.svelte';
import type { SeoSettings } from '$lib/types';

vi.mock('$app/navigation', () => ({ invalidateAll: vi.fn().mockResolvedValue(undefined) }));

const settings: SeoSettings = {
  endpoint: 'https://llm.example.com/v1/chat/completions',
  model: 'seo-model',
  has_api_key: true,
  endpoint_source: 'ui',
  model_source: 'env',
  api_key_source: 'env'
};

function show(overrides: Partial<SeoSettings> = {}, error = '') {
  return render(SeoSettingsPanel, { props: { settings: { ...settings, ...overrides }, loadError: error } });
}

function response(body: unknown = settings) {
  return { ok: true, json: async () => body };
}

afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe('SeoSettingsPanel', () => {
  it('shows the effective endpoint, model and credential sources without ever displaying a key', () => {
    show();
    expect((screen.getByRole('textbox', { name: 'Адрес (OpenAI Chat Completions)' }) as HTMLInputElement).value)
      .toBe('https://llm.example.com/v1/chat/completions');
    expect((screen.getByRole('textbox', { name: 'Модель' }) as HTMLInputElement).value).toBe('seo-model');
    expect((screen.getByLabelText('Новый API-ключ') as HTMLInputElement).value).toBe('');
    expect(screen.getByText(/Ключ задан.*окружен/)).toBeTruthy();
    expect(screen.getByText(/Адрес.*интерфейс/)).toBeTruthy();
    expect(screen.getByText(/Модель.*окружен/)).toBeTruthy();
    expect(screen.getByText('Подключение настроено')).toBeTruthy();
    expect(document.body.textContent).not.toContain('secret');
  });

  it('reports an unconfigured service LLM without inventing values', () => {
    show({ endpoint: null, model: null, has_api_key: false, endpoint_source: 'none', model_source: 'none', api_key_source: 'none' });
    expect((screen.getByRole('textbox', { name: 'Адрес (OpenAI Chat Completions)' }) as HTMLInputElement).value).toBe('');
    expect((screen.getByRole('textbox', { name: 'Модель' }) as HTMLInputElement).value).toBe('');
    expect(screen.getByText('Для работы нужны адрес, модель и API-ключ')).toBeTruthy();
    expect(screen.getByText(/Ключ не задан.*не задан/)).toBeTruthy();
  });

  it('saves changed endpoint, model and a nonempty key, then clears the key input', async () => {
    const fetch = vi.fn().mockResolvedValue(response({ ...settings, model: 'new-model' }));
    vi.stubGlobal('fetch', fetch);
    show();
    await fireEvent.input(screen.getByRole('textbox', { name: 'Адрес (OpenAI Chat Completions)' }), { target: { value: 'https://llm.example.com/v2/chat/completions' } });
    await fireEvent.input(screen.getByRole('textbox', { name: 'Модель' }), { target: { value: 'new-model' } });
    await fireEvent.input(screen.getByLabelText('Новый API-ключ'), { target: { value: 'new-secret' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Сохранить настройки' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    expect(fetch.mock.calls[0][0]).toBe('/api/seo/settings');
    expect(fetch.mock.calls[0][1].method).toBe('PUT');
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      endpoint: 'https://llm.example.com/v2/chat/completions', model: 'new-model', api_key: 'new-secret'
    });
    expect((screen.getByLabelText('Новый API-ключ') as HTMLInputElement).value).toBe('');
    await waitFor(() => expect(invalidateAll).toHaveBeenCalledOnce());
    expect(screen.getByRole('status').textContent).toContain('сохранены');
  });

  it('preserves the stored key when the key field is empty', async () => {
    const fetch = vi.fn().mockResolvedValue(response());
    vi.stubGlobal('fetch', fetch);
    show();
    await fireEvent.click(screen.getByRole('button', { name: 'Сохранить настройки' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      endpoint: 'https://llm.example.com/v1/chat/completions', model: 'seo-model'
    });
  });

  it('probes the connection with a bodyless POST and shows the model and tool support', async () => {
    const fetch = vi.fn().mockResolvedValue(response({ ok: true, model: 'seo-model', tools: true }));
    vi.stubGlobal('fetch', fetch);
    show();
    await fireEvent.click(screen.getByRole('button', { name: 'Проверить подключение' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    expect(fetch.mock.calls[0][0]).toBe('/api/seo/settings/test');
    expect(fetch.mock.calls[0][1]).toEqual({ method: 'POST' });
    const status = await screen.findByRole('status');
    expect(status.textContent).toContain('Подключение работает');
    expect(status.textContent).toContain('seo-model');
    expect(status.textContent).toContain('Инструменты: поддерживаются.');
    expect(status.textContent).not.toContain('не поддерживаются');
  });

  it('states that the model cannot call tools when the probe reports no support', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ ok: true, model: 'seo-model', tools: false })));
    show();
    await fireEvent.click(screen.getByRole('button', { name: 'Проверить подключение' }));
    const status = await screen.findByRole('status');
    expect(status.textContent).toContain('Инструменты: не поддерживаются.');
  });

  it('reports a failed connection probe with the safe upstream message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ ok: false, error: 'Модель недоступна' })));
    show();
    await fireEvent.click(screen.getByRole('button', { name: 'Проверить подключение' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Модель недоступна');
    expect(alert.textContent).toContain('Инструменты: не поддерживаются.');
  });

  it('reports the tool-calling requirement as a safe error without any upstream secret', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      response({ ok: false, error: 'Модель не поддерживает вызов инструментов', api_key: 'secret-value' })
    ));
    show();
    await fireEvent.click(screen.getByRole('button', { name: 'Проверить подключение' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Модель не поддерживает вызов инструментов');
    expect(alert.textContent).not.toContain('secret-value');
  });

  it('resets the stored key through the dedicated action', async () => {
    const fetch = vi.fn().mockResolvedValue(response({ ...settings, has_api_key: false, api_key_source: 'none' }));
    vi.stubGlobal('fetch', fetch);
    show();
    await fireEvent.click(screen.getByRole('button', { name: 'Сбросить учётные данные' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    expect(fetch.mock.calls[0][0]).toBe('/api/seo/settings/credentials');
    expect(fetch.mock.calls[0][1]).toEqual({ method: 'DELETE' });
    expect((screen.getByLabelText('Новый API-ключ') as HTMLInputElement).value).toBe('');
    await waitFor(() => expect(invalidateAll).toHaveBeenCalledOnce());
    expect(screen.getByRole('status').textContent).toContain('Ключ удалён');
  });

  it('disables every mutation on load errors and during a pending save, then fails safely', async () => {
    const broken = render(SeoSettingsPanel, { props: { settings: null, loadError: 'Настройки служебной LLM недоступны' } });
    expect(screen.getByRole('alert').textContent).toContain('Настройки служебной LLM недоступны');
    expect((screen.getByRole('button', { name: 'Сохранить настройки' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Проверить подключение' }) as HTMLButtonElement).disabled).toBe(true);
    broken.unmount();

    let reject!: (reason?: unknown) => void;
    const fetch = vi.fn().mockImplementation(() => new Promise((_resolve, fail) => { reject = fail; }));
    vi.stubGlobal('fetch', fetch);
    show();
    await fireEvent.input(screen.getByLabelText('Новый API-ключ'), { target: { value: 'retry-secret' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Сохранить настройки' }));
    expect((screen.getByRole('button', { name: 'Сохраняем…' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Сбросить учётные данные' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Проверить подключение' }) as HTMLButtonElement).disabled).toBe(true);
    reject(new Error('secret-key-leak'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Не удалось сохранить настройки'));
    expect(screen.getByRole('alert').textContent).not.toContain('secret-key-leak');
    expect((screen.getByLabelText('Новый API-ключ') as HTMLInputElement).value).toBe('retry-secret');
  });
});
