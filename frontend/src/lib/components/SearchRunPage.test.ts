// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Page from '../../routes/+page.svelte';
import type { FormConfig, PublicProvider, YandexSearchSettings } from '$lib/types';

const settings: YandexSearchSettings = {
  enabled: true, folder_id: null, has_api_key: false, api_key_source: 'none', folder_id_source: 'none'
};
const form: FormConfig = {
  limits: { max_prompts: 20, max_providers: 5, max_prompt_length: 500, max_brand_length: 200, max_domain_length: 253 },
  new_provider_fields: [], default_provider_ids: [], scope_options: []
};
const provider: PublicProvider = {
  id: 'model-1', name: 'Модель', kind: 'custom', endpoint: null, model: 'test-model',
  configured: true, editable_fields: [], can_reset: false, can_delete: true,
  status_label: '', delete_label: '', delete_prompt: '', delete_success: ''
};
const data = {
  providers: [provider], form, loadError: '', searchRegions: [{ id: 1, name: 'Москва' }],
  searchRegionError: '', searchSettings: settings, searchSettingsError: ''
};

afterEach(() => vi.unstubAllGlobals());

function show() {
  const fetch = vi.fn(async (input: string, init?: RequestInit) => {
    if (input === '/api/runs' && !init) return { ok: true, json: async () => ({ items: [], next_cursor: null }) };
    if (input === '/api/runs' && init?.method === 'POST') return { ok: true, json: async () => ({ id: 'new-run', status: 'done' }) };
    if (input === '/api/runs/new-run') return { ok: true, json: async () => ({
      id: 'new-run', created_at: '2026-09-28T00:00:00Z', finished_at: '2026-09-28T00:00:00Z', status: 'done',
      brand: 'Бренд', domain: '', prompts: ['цветы'], provider_ids: ['model-1'], regions: [],
      models: [], search: [], summary_rows: []
    }) };
    throw new Error(`Unexpected request: ${input}`);
  });
  vi.stubGlobal('fetch', fetch);
  return { ...render(Page, { props: { data } }), fetch };
}

describe('regional run form', () => {
  it('offers Yandex and counts selected requests while enabled', async () => {
    const { fetch } = show();
    await fireEvent.click(screen.getByRole('button', { name: '＋ Добавить регион' }));
    expect(screen.getByRole('option', { name: 'Яндекс' })).toBeTruthy();
    await fireEvent.change(screen.getByRole('combobox', { name: 'Регион 1' }), { target: { value: '1' } });
    await fireEvent.input(screen.getByRole('textbox', { name: /Вопросы клиентов/ }), { target: { value: 'первый\nвторой' } });
    expect(screen.getByText('2 запроса к Яндексу')).toBeTruthy();
    await fireEvent.input(screen.getByRole('textbox', { name: 'Сайт' }), { target: { value: 'example.ru' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Проверить бренд' }));
    await waitFor(() => expect(fetch.mock.calls.some(([path, init]) => path === '/api/runs' && init?.method === 'POST')).toBe(true));
    const post = fetch.mock.calls.find(([path, init]) => path === '/api/runs' && init?.method === 'POST')!;
    expect(JSON.parse(post[1]!.body as string)).toMatchObject({
      provider_ids: [], regions: [1], region_targets: [{ region: 1, engine: 'yandex' }]
    });
  });

  it('removes stale Yandex targets after settings refresh and submits selected models', async () => {
    const { rerender, fetch } = show();
    await fireEvent.click(screen.getByRole('checkbox', { name: /Модель/ }));
    await fireEvent.click(screen.getByRole('button', { name: '＋ Добавить регион' }));
    await fireEvent.change(screen.getByRole('combobox', { name: 'Регион 1' }), { target: { value: '1' } });
    await fireEvent.input(screen.getByRole('textbox', { name: /Вопросы клиентов/ }), { target: { value: 'цветы' } });
    await fireEvent.input(screen.getByRole('textbox', { name: /Название бренда/ }), { target: { value: 'Бренд' } });
    await rerender({ data: { ...data, searchSettings: { ...settings, enabled: false } } });
    expect(screen.queryByRole('option', { name: 'Яндекс' })).toBeNull();
    expect((screen.getByRole('button', { name: '＋ Добавить регион' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByText('1 запрос к Яндексу')).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'Проверить бренд' }));
    await waitFor(() => expect(fetch.mock.calls.some(([path, init]) => path === '/api/runs' && init?.method === 'POST')).toBe(true));
    const post = fetch.mock.calls.find(([path, init]) => path === '/api/runs' && init?.method === 'POST')!;
    expect(JSON.parse(post[1]!.body as string)).toMatchObject({ provider_ids: ['model-1'], regions: [], region_targets: [] });
  });
});
