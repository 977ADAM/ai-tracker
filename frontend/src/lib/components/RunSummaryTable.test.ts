// @vitest-environment jsdom
import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import RunSummaryTable from './RunSummaryTable.svelte';
import type { RunSnapshot } from '$lib/types';

const snapshot: RunSnapshot = {
  id: 'run-1', created_at: '2026-09-25T14:00:00Z', finished_at: null, status: 'pending',
  brand: 'Ромашка', domain: 'example.ru', prompts: ['цветы'], provider_ids: ['p'], regions: [1],
  models: [], search: [], summary_rows: [
    { prompt: 'цветы', source: 'Яндекс', language: 'ru', region: 'Москва', ai_answer: '—',
      site_found: 'Нет', position: '—', brand_found: '—', status: 'Готово' },
    { prompt: 'цветы', source: 'Demo', language: '', region: '—', ai_answer: 'Да',
      site_found: '—', position: '—', brand_found: 'Да', status: 'Готово' },
    { prompt: 'второй', source: 'Яндекс', language: 'ru', region: 'Москва', ai_answer: '—',
      site_found: '—', position: '—', brand_found: '—', status: 'Прервано' },
    { prompt: 'третий', source: 'Demo', language: '', region: '—', ai_answer: '—',
      site_found: '—', position: '—', brand_found: '—', status: 'Ошибка' }
  ]
};

describe('RunSummaryTable', () => {
  it('shows mixed result columns and unknown values without claiming checks', () => {
    render(RunSummaryTable, { props: { snapshot } });
    expect(screen.getByText('Сайт найден')).toBeTruthy();
    expect(screen.getByText('Бренд найден')).toBeTruthy();
    const rows = screen.getAllByRole('row').slice(1);
    expect(within(rows[0]).getByText('Нет')).toBeTruthy();
    expect(rows[0].textContent).toContain('—');
    expect(rows[1].textContent).toContain('Да');
    expect(rows[1].textContent).toContain('—');
    expect(rows[2].textContent).toContain('Прервано');
    expect(rows[3].textContent).toContain('Ошибка');
  });

  it('offers export only for a terminal run', () => {
    const view = render(RunSummaryTable, { props: { snapshot } });
    expect(screen.queryByRole('link', { name: 'Экспорт' })).toBeNull();
    view.unmount();
    render(RunSummaryTable, { props: { snapshot: { ...snapshot, status: 'interrupted', finished_at: '2026-09-25T15:00:00Z' } } });
    expect(screen.getByRole('link', { name: 'Экспорт' }).getAttribute('href')).toBe('/api/runs/run-1/export.csv');
  });
});
