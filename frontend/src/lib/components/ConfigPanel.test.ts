// @vitest-environment jsdom
import { render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ConfigPanel from './ConfigPanel.svelte';

const CONFIG = '{\n  "providers": {\n    "groups": []\n  },\n  "search": null,\n  "seo": null\n}';

function stubFetch(value: unknown, ok = true) {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok, json: async () => value })));
}

afterEach(() => vi.unstubAllGlobals());

describe('ConfigPanel', () => {
  it('shows the stored document of every setting with its directory', async () => {
    stubFetch({ directory: '/data', exists: true, content: CONFIG });
    render(ConfigPanel, { props: { open: true, onclose: () => {} } });

    expect(await screen.findByText(/"providers"/)).toBeTruthy();
    expect(screen.getByRole('dialog', { name: 'Конфигурация' })).toBeTruthy();
    expect(screen.getByText('/data')).toBeTruthy();
    // The window explains what the document holds and what it never holds.
    const text = (screen.getByRole('dialog').textContent ?? '').replace(/\s+/g, ' ');
    expect(text).toContain('поисковая система и SEO-анализ');
    expect(text).toContain('Ключи API в файлы не записываются');
  });

  it('requests the configuration document once the window opens', async () => {
    const fetch = vi.fn(async () => ({ ok: true, json: async () => ({ directory: '/data', exists: true, content: CONFIG }) }));
    vi.stubGlobal('fetch', fetch);
    render(ConfigPanel, { props: { open: true, onclose: () => {} } });

    expect(await screen.findByText(/"providers"/)).toBeTruthy();
    expect(fetch).toHaveBeenCalledWith('/api/config');
  });

  it('says so while nothing is stored yet', async () => {
    stubFetch({ directory: '/data', exists: false, content: null });
    render(ConfigPanel, { props: { open: true, onclose: () => {} } });

    expect(await screen.findByText(/Настройки ещё не сохранены/)).toBeTruthy();
  });

  it('reports a safe error instead of an empty document', async () => {
    stubFetch({ detail: 'Не удалось прочитать конфигурацию' }, false);
    render(ConfigPanel, { props: { open: true, onclose: () => {} } });

    expect((await screen.findByRole('alert')).textContent).toContain('Не удалось прочитать конфигурацию');
  });

  it('does not request anything while the window is closed', () => {
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    render(ConfigPanel, { props: { open: false, onclose: () => {} } });

    expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
