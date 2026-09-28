// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SearchSettingsPanel from './SearchSettingsPanel.svelte';
import type { YandexSearchSettings } from '$lib/types';

vi.mock('$app/navigation', () => ({ invalidateAll: vi.fn().mockResolvedValue(undefined) }));

const settings: YandexSearchSettings = {
  enabled: true,
  folder_id: 'folder-from-env',
  has_api_key: true,
  api_key_source: 'ui',
  folder_id_source: 'env'
};

function show(overrides: Partial<YandexSearchSettings> = {}, error = '') {
  return render(SearchSettingsPanel, { props: { settings: { ...settings, ...overrides }, loadError: error } });
}

function response(yandex: YandexSearchSettings = settings) {
  return { ok: true, json: async () => ({ yandex }) };
}

afterEach(() => vi.unstubAllGlobals());

describe('SearchSettingsPanel', () => {
  it('shows enabled state, effective folder ID and independent credential sources without displaying a key', () => {
    show();
    expect((screen.getByRole('checkbox', { name: 'Яндекс включён' }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole('textbox', { name: 'ID каталога' }) as HTMLInputElement).value).toBe('folder-from-env');
    expect((screen.getByLabelText('Новый API-ключ') as HTMLInputElement).value).toBe('');
    expect(screen.getByText(/Ключ задан.*интерфейс/)).toBeTruthy();
    expect(screen.getByText(/ID каталога.*окружен/)).toBeTruthy();
    expect(screen.getByText(/Подключение настроено/)).toBeTruthy();
  });

  it('saves enabled alone when credentials are unchanged', async () => {
    const fetch = vi.fn().mockResolvedValue(response({ ...settings, enabled: false }));
    vi.stubGlobal('fetch', fetch);
    show();
    await fireEvent.click(screen.getByRole('checkbox', { name: 'Яндекс включён' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Сохранить настройки' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ enabled: false });
  });

  it('saves changed nonempty credentials and clears the key input', async () => {
    const fetch = vi.fn().mockResolvedValue(response({ ...settings, folder_id: 'new-folder' }));
    vi.stubGlobal('fetch', fetch);
    show();
    await fireEvent.input(screen.getByLabelText('Новый API-ключ'), { target: { value: 'new-secret' } });
    await fireEvent.input(screen.getByRole('textbox', { name: 'ID каталога' }), { target: { value: 'new-folder' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Сохранить настройки' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ enabled: true, api_key: 'new-secret', folder_id: 'new-folder' });
    expect((screen.getByLabelText('Новый API-ключ') as HTMLInputElement).value).toBe('');
  });

  it('preserves a stored key when its input is empty', async () => {
    const fetch = vi.fn().mockResolvedValue(response());
    vi.stubGlobal('fetch', fetch);
    show();
    await fireEvent.click(screen.getByRole('button', { name: 'Сохранить настройки' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ enabled: true });
  });

  it('resets both credential overrides through the dedicated action', async () => {
    const fetch = vi.fn().mockResolvedValue(response({ ...settings, api_key_source: 'env', folder_id_source: 'env' }));
    vi.stubGlobal('fetch', fetch);
    show({ folder_id_source: 'ui' });
    await fireEvent.click(screen.getByRole('button', { name: 'Сбросить учётные данные' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    expect(fetch.mock.calls[0][0]).toBe('/api/search/settings/credentials');
    expect(fetch.mock.calls[0][1]).toEqual({ method: 'DELETE' });
  });

  it('disables mutations on load errors and during a pending save, then reports failures safely', async () => {
    const broken = render(SearchSettingsPanel, { props: { settings: null, loadError: 'Не удалось загрузить настройки' } });
    expect(screen.getByRole('alert').textContent).toContain('Не удалось загрузить настройки');
    expect((screen.getByRole('button', { name: 'Сохранить настройки' }) as HTMLButtonElement).disabled).toBe(true);
    broken.unmount();

    let reject!: (reason?: unknown) => void;
    const fetch = vi.fn().mockImplementation(() => new Promise((_resolve, fail) => { reject = fail; }));
    vi.stubGlobal('fetch', fetch);
    show();
    await fireEvent.input(screen.getByLabelText('Новый API-ключ'), { target: { value: 'retry-secret' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Сохранить настройки' }));
    expect((screen.getByRole('button', { name: 'Сохраняем…' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Сбросить учётные данные' }) as HTMLButtonElement).disabled).toBe(true);
    reject(new Error('secret-key-leak'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Не удалось сохранить настройки'));
    expect(screen.getByRole('alert').textContent).not.toContain('secret-key-leak');
    expect((screen.getByLabelText('Новый API-ключ') as HTMLInputElement).value).toBe('retry-secret');
  });
});
