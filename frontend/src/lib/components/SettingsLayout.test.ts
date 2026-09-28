// @vitest-environment jsdom
import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import Layout from '../../routes/+layout.svelte';

vi.mock('$app/navigation', () => ({ invalidateAll: vi.fn().mockResolvedValue(undefined) }));

const data = {
  providers: [], settingsProviders: [], form: null, searchRegions: [], searchRegionError: '',
  searchSettings: { enabled: true, folder_id: null, has_api_key: false, api_key_source: 'none' as const, folder_id_source: 'none' as const },
  searchSettingsError: '', loadError: ''
};

describe('settings dialog navigation', () => {
  it('opens on Models and switches to the Yandex settings panel by mouse or keyboard', async () => {
    render(Layout, { props: { data, children: createRawSnippet(() => ({ render: () => '<main>Page</main>' })) } });
    await fireEvent.click(screen.getByRole('button', { name: 'Настройки API' }));
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
});
