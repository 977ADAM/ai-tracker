// @vitest-environment jsdom
import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import Layout from '../../routes/+layout.svelte';

vi.mock('$app/navigation', () => ({ invalidateAll: vi.fn().mockResolvedValue(undefined) }));

const data = {
  providers: [],
  settingsProviders: [],
  form: null,
  searchRegions: [],
  searchRegionError: '',
  searchSettings: {
    enabled: true,
    folder_id: null,
    has_api_key: false,
    api_key_source: 'none' as const,
    folder_id_source: 'none' as const,
  },
  searchSettingsError: '',
  seoSettings: {
    endpoint: null,
    model: null,
    has_api_key: false,
    endpoint_source: 'none' as const,
    model_source: 'none' as const,
    api_key_source: 'none' as const,
  },
  seoSettingsError: '',
  loadError: '',
};

function openSettings() {
  render(Layout, {
    props: { data, children: createRawSnippet(() => ({ render: () => '<main>Page</main>' })) },
  });
  return fireEvent.click(screen.getByRole('button', { name: 'Настройки API' }));
}

describe('settings dialog navigation', () => {
  it('opens on Models and switches to the Yandex settings panel by mouse or keyboard', async () => {
    await openSettings();
    const tabs = screen.getByRole('tablist', { name: 'Разделы настроек' });
    const models = within(tabs).getByRole('tab', { name: 'Модели' });
    const search = within(tabs).getByRole('tab', { name: 'Поисковые системы' });
    expect(models.getAttribute('aria-selected')).toBe('true');
    expect(search.getAttribute('aria-selected')).toBe('false');
    expect(screen.getByRole('tabpanel', { name: 'Модели' })).toBeTruthy();
    expect(document.getElementById(models.getAttribute('aria-controls')!)).toBeTruthy();
    expect(document.getElementById(search.getAttribute('aria-controls')!)).toBeTruthy();
    expect(document.getElementById(search.getAttribute('aria-controls')!)?.hidden).toBe(true);

    await fireEvent.click(search);
    expect(search.getAttribute('aria-selected')).toBe('true');
    expect(screen.getByRole('tabpanel', { name: 'Поисковые системы' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Яндекс' })).toBeTruthy();
    expect(document.getElementById(models.getAttribute('aria-controls')!)?.hidden).toBe(true);
    expect(document.getElementById(search.getAttribute('aria-controls')!)?.hidden).toBe(false);

    search.focus();
    await fireEvent.keyDown(search, { key: 'ArrowLeft' });
    expect(models.getAttribute('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(models);
    expect(document.getElementById(models.getAttribute('aria-controls')!)?.hidden).toBe(false);
  });

  it('keeps Models as the default tab while making all three tabs reachable', async () => {
    await openSettings();
    const tabs = screen.getByRole('tablist', { name: 'Разделы настроек' });
    const models = within(tabs).getByRole('tab', { name: 'Модели' });
    const search = within(tabs).getByRole('tab', { name: 'Поисковые системы' });
    const seo = within(tabs).getByRole('tab', { name: 'SEO-анализ' });
    expect([models, search, seo].map((tab) => tab.getAttribute('aria-selected'))).toEqual([
      'true',
      'false',
      'false',
    ]);
    expect(models.getAttribute('tabindex')).toBe('0');
    for (const tab of [search, seo]) {
      expect(tab.getAttribute('tabindex')).toBe('-1');
      expect(document.getElementById(tab.getAttribute('aria-controls')!)).toBeTruthy();
      expect(document.getElementById(tab.getAttribute('aria-controls')!)?.hidden).toBe(true);
    }

    // ArrowRight walks forward through every tab and wraps back to the first.
    models.focus();
    await fireEvent.keyDown(models, { key: 'ArrowRight' });
    expect(search.getAttribute('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(search);
    await fireEvent.keyDown(search, { key: 'ArrowRight' });
    expect(seo.getAttribute('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(seo);
    await fireEvent.keyDown(seo, { key: 'ArrowRight' });
    expect(models.getAttribute('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(models);

    // End jumps to the last tab and Home comes back to Models.
    await fireEvent.keyDown(models, { key: 'End' });
    expect(seo.getAttribute('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(seo);
    await fireEvent.keyDown(seo, { key: 'Home' });
    expect(models.getAttribute('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(models);
  });

  it('renders the service-LLM settings panel on the SEO tab without exposing a key field value', async () => {
    await openSettings();
    const seo = within(screen.getByRole('tablist', { name: 'Разделы настроек' })).getByRole('tab', {
      name: 'SEO-анализ',
    });
    expect(screen.queryByRole('heading', { name: 'Служебная LLM' })).toBeNull();
    await fireEvent.click(seo);
    const panel = screen.getByRole('tabpanel', { name: 'SEO-анализ' });
    expect(panel).toBeTruthy();
    expect(document.getElementById(seo.getAttribute('aria-controls')!)?.hidden).toBe(false);
    expect(screen.getByRole('heading', { name: 'Служебная LLM' })).toBeTruthy();
    expect((within(panel).getByLabelText('Новый API-ключ') as HTMLInputElement).value).toBe('');
    expect(within(panel).getByRole('button', { name: 'Проверить подключение' })).toBeTruthy();
    expect(within(panel).getByRole('button', { name: 'Сбросить учётные данные' })).toBeTruthy();
  });
});
