// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import SeoReport from './SeoReport.svelte';
import type {
  SeoAnalysisSnapshot,
  SeoCompetitorAggregates,
  SeoMetric,
  SeoModelRow,
  SeoSearchRow,
} from '$lib/types';

/** One share: `share` is a fraction of the denominator, or null when it is empty. */
function metric(denominator: number, successes: number, average: number | null = null): SeoMetric {
  return {
    denominator,
    successes,
    share: denominator > 0 ? Math.round((successes / denominator) * 10_000) / 10_000 : null,
    average_position: average,
  };
}

const empty = metric(0, 0);
const search = {
  overall: metric(4, 2, 3.5),
  branded: metric(1, 1, 2),
  unbranded: metric(3, 1, 5),
};

const competitor: SeoCompetitorAggregates = {
  host: 'flower-shop.example',
  title: 'Цветочный магазин — доставка',
  occurrences: 2,
  average_position: 2.5,
  seed_indexes: [0, 1],
  search: { overall: metric(4, 1, 2), branded: empty, unbranded: metric(3, 1, 2) },
  ai: { 'model-1': { host: metric(4, 1), citation: metric(4, 2) } },
};

/**
 * The citation share and the brand position of the site in `model-1`:
 * half of the answers cite the domain, it stands second among the sources,
 * and the brand opens a third of the answers.
 */
const citation = metric(4, 2, 2);
const brandPosition = {
  first: metric(10, 3),
  early: metric(10, 2),
  late: metric(10, 1),
  absent: metric(10, 4),
  ahead: empty,
};

const modelRow: SeoModelRow = {
  query_index: 0,
  connection_id: 'model-1',
  provider_name: 'Модель',
  status: 'found',
  answer: 'Ромашка рекомендует доставку цветов',
  name_mentioned: true,
  host_mentioned: false,
  error: null,
  query: 'купить цветы',
  category: 'commercial',
  service: 'Доставка цветов',
  answer_mode: 'deepseek_web',
  search_status: 'completed',
  citations: [
    { url: 'https://habr.com/ru/articles/1', title: 'Разбор доставки' },
    { url: 'https://vc.ru/marketing/2', title: null },
  ],
  model: null,
  search_calls: null,
};

const searchRow: SeoSearchRow = {
  query_index: 2,
  query: 'цветы или подарки',
  category: 'comparative',
  service: null,
  status: 'error',
  site_position: null,
  site_url: null,
  error: 'Не удалось получить выдачу Яндекса',
};

function snapshot(overrides: Partial<SeoAnalysisSnapshot> = {}): SeoAnalysisSnapshot {
  return {
    id: 'seo-1',
    status: 'completed',
    created_at: '2026-09-28T00:00:00Z',
    updated_at: '2026-09-28T01:00:00Z',
    finished_at: '2026-09-28T01:00:00Z',
    input: {
      url: 'https://example.ru',
      host: 'example.ru',
      sphere: 'Цветы',
      seeds: ['купить цветы', 'доставка букетов', 'цветы или подарки'],
      services: ['Доставка цветов', 'Букеты'],
      connection_ids: ['model-1'],
    },
    estimate: { search_upper: 23, model_upper: 20, generated_limit: 20, connections: 1 },
    company_name: 'Ромашка',
    services: ['Доставка цветов', 'Букеты'],
    pages: [],
    stages: [],
    agents: [],
    budget: {
      pages: { used: 1, limit: 20 },
      searches: { used: 5, limit: 43 },
      model_answers: { used: 4, limit: 40 },
      tool_calls: { used: 9, limit: 120 },
      handoffs: { used: 5, limit: 15 },
      seed_searches: 3,
      model_rows: 7,
      steps: 12,
      agent_steps: {},
    },
    budget_exhausted: false,
    candidates: [],
    queries: Array.from({ length: 7 }, (_, index) => ({
      index,
      text: `запрос ${index + 1}`,
      category: 'commercial',
      service: null,
      flags: {
        mentions_company_name: false,
        mentions_company_host: false,
        mentions_candidate_host: false,
        branded: false,
      },
    })),
    counters: { queries: 7, search_rows: 4, model_rows: 7, search_errors: 1, model_errors: 0 },
    readiness: {
      report_ready: true,
      summary_ready: true,
      queries_ready: true,
      has_submitted_search_rows: false,
      has_unsubmitted_search_rows: false,
      has_unfinished_model_rows: false,
      search_rows: 4,
      model_rows: 7,
    },
    aggregates: {
      site: {
        search,
        ai: {
          'model-1': {
            name: metric(4, 2),
            host: metric(4, 1),
            combined: metric(4, 3),
            citation,
            position: brandPosition,
            branded: {
              name: metric(1, 1),
              host: metric(1, 0),
              combined: metric(1, 1),
              citation,
              position: null,
            },
            unbranded: {
              name: metric(3, 1),
              host: metric(3, 1),
              combined: metric(3, 2),
              citation,
              position: null,
            },
          },
        },
      },
      competitors: [competitor],
      categories: {
        commercial: { search: metric(2, 2, 2), ai: { 'model-1': metric(2, 2) } },
        informational: { search: metric(1, 0), ai: { 'model-1': metric(1, 0) } },
        comparative: { search: empty, ai: { 'model-1': empty } },
      },
      services: {
        'Доставка цветов': { search: metric(2, 1, 4), ai: { 'model-1': metric(2, 1) } },
        '': { search: metric(2, 1), ai: { 'model-1': metric(2, 1) } },
      },
      sources: [{ domain: 'habr.com', answers: 2, citations: 3 }],
      counts: { queries: 7, search_rows: 4, model_rows: 7, search_errors: 1, model_errors: 0 },
    },
    ...overrides,
  };
}

function content(selector: string): string {
  return document.querySelector(selector)?.textContent?.trim() ?? '';
}

describe('SeoReport', () => {
  it('renders the site Yandex shares and average positions', () => {
    render(SeoReport, { props: { snapshot: snapshot() } });
    expect(content('[data-metric="site-overall"]')).toBe('50 %');
    expect(content('[data-metric="site-branded"]')).toBe('100 %');
    expect(content('[data-metric="site-unbranded"]')).toBe('33 %');
    const table = screen.getByRole('table', { name: 'Сайт в Яндексе' });
    expect(table.textContent).toContain('2 из 4');
    expect(table.textContent).toContain('3,5');
    // The report is numbers-only and compact: the parameters are one line, and
    // there is no counters block or breakdown table any more.
    expect(content('[data-report-params]')).toContain('example.ru');
    expect(content('[data-report-params]')).toContain('Ромашка');
    expect(document.querySelector('[data-report-counters]')).toBeNull();
  });

  it('renders the name, host and combined AI shares of every connection split by brand', () => {
    render(SeoReport, {
      props: { snapshot: snapshot(), connectionNames: { 'model-1': 'DeepSeek' } },
    });
    const table = screen.getByRole('table', { name: 'Упоминания: DeepSeek' });
    expect(table).toBeTruthy();
    expect(content('[data-metric="ai-model-1-all-name"]')).toBe('50 %');
    expect(content('[data-metric="ai-model-1-all-host"]')).toBe('25 %');
    expect(content('[data-metric="ai-model-1-all-combined"]')).toBe('75 %');
    expect(content('[data-metric="ai-model-1-branded-name"]')).toBe('100 %');
    expect(content('[data-metric="ai-model-1-unbranded-host"]')).toBe('33 %');
  });

  it('shows how often the domain is cited and where it stands among the sources', () => {
    render(SeoReport, { props: { snapshot: snapshot() } });
    expect(content('[data-metric="ai-model-1-all-citation"]')).toBe('50 %');
    expect(content('[data-position="ai-model-1-all-citation"]')).toBe('2');
  });

  it('shows the brand position and skips it when there is no data', () => {
    render(SeoReport, { props: { snapshot: snapshot() } });
    expect(content('[data-brand-position="first"]')).toBe('30 %');
    const empty = document.querySelector('[data-brand-position="ahead"]');
    expect(empty?.textContent).toBe('—');
    expect(screen.getByText(/эвристика по абзацам ответа/i)).toBeTruthy();
  });

  it('lists the top cited domains and the model coverage', () => {
    render(SeoReport, { props: { snapshot: snapshot() } });
    expect(document.querySelector('[data-source-domain]')?.textContent).toBe('habr.com');
    expect(document.querySelector('[data-source-domain]')?.getAttribute('data-source-domain')).toBe(
      'habr.com',
    );
    expect(content('[data-source-answers]')).toBe('2');
    expect(content('[data-source-citations]')).toBe('3');
    expect(screen.getByText(/только у подключений с веб-поиском/i)).toBeTruthy();
    expect(content('[data-model-coverage]')).toBe('7 из 7');
  });

  it('keeps the sources section with its disclaimer when no answer cited a source', () => {
    render(SeoReport, {
      props: {
        snapshot: snapshot({ aggregates: { ...snapshot().aggregates, sources: [] } }),
      },
    });
    expect(document.querySelector('[data-source-row]')).toBeNull();
    expect(screen.queryByRole('table', { name: 'Источники' })).toBeNull();
    expect(screen.getByText(/только у подключений с веб-поиском/i)).toBeTruthy();
    expect(content('[data-sources-empty]')).toBe('—');
  });

  it('shows the candidate citation share next to its host share', () => {
    render(SeoReport, { props: { snapshot: snapshot() } });
    expect(content('[data-metric="candidate-flower-shop.example-citation-model-1"]')).toBe('50 %');
  });

  it('shows the answer mode and the number of sources in the detail row', () => {
    render(SeoReport, { props: { snapshot: snapshot(), rows: { model: [modelRow], search: [] } } });
    expect(content('[data-answer-mode]')).toBe('веб-поиск');
    expect(content('[data-answer-sources-count]')).toBe('2');
  });

  it('renders «—» instead of zero sources for an answer without web search', () => {
    const row: SeoModelRow = { ...modelRow, answer_mode: 'text', citations: [] };
    render(SeoReport, { props: { snapshot: snapshot(), rows: { model: [row], search: [] } } });
    expect(content('[data-answer-mode]')).toBe('текст');
    expect(content('[data-answer-sources-count]')).toBe('—');
  });

  it('lists the answer citation links in the dialog and opens them in a new tab', async () => {
    const row: SeoModelRow = { ...modelRow, answer: 'я'.repeat(400) };
    render(SeoReport, { props: { snapshot: snapshot(), rows: { model: [row], search: [] } } });
    await fireEvent.click(screen.getByRole('button', { name: 'Читать полностью' }));

    const list = document.querySelector('[data-answer-sources-list]');
    const links = list?.querySelectorAll('a') ?? [];
    expect(links).toHaveLength(2);
    expect(links[0]?.getAttribute('href')).toBe('https://habr.com/ru/articles/1');
    expect(links[0]?.getAttribute('target')).toBe('_blank');
    expect(links[0]?.getAttribute('rel')).toBe('noopener noreferrer');
    expect(links[0]?.textContent).toBe('Разбор доставки');
    // A citation without a title falls back to its URL.
    expect(links[1]?.textContent).toBe('https://vc.ru/marketing/2');
  });

  it('renders a citation URL repeated in one answer without crashing the dialog', async () => {
    const duplicate = { url: 'https://habr.com/ru/articles/1', title: 'Разбор доставки' };
    const row: SeoModelRow = {
      ...modelRow,
      answer: 'я'.repeat(400),
      citations: [duplicate, { ...duplicate }],
    };
    render(SeoReport, { props: { snapshot: snapshot(), rows: { model: [row], search: [] } } });

    await fireEvent.click(screen.getByRole('button', { name: 'Читать полностью' }));

    expect(await screen.findByRole('dialog')).toBeTruthy();
    const links = document.querySelector('[data-answer-sources-list]')?.querySelectorAll('a') ?? [];
    expect(links).toHaveLength(2);
    expect(links[0]?.getAttribute('href')).toBe('https://habr.com/ru/articles/1');
    expect(links[1]?.getAttribute('href')).toBe('https://habr.com/ru/articles/1');
  });

  it('shows the detail category as its Russian label', () => {
    render(SeoReport, {
      props: { snapshot: snapshot(), rows: { model: [], search: [searchRow] } },
    });
    const table = screen.getByRole('table', { name: 'Проверки в Яндексе' });
    expect(table.textContent).toContain('Сравнительные');
    expect(table.textContent).not.toContain('comparative');
  });

  it('renders the recurring candidates with evidence, seeds and both metric families', () => {
    render(SeoReport, { props: { snapshot: snapshot() } });
    const card = document.querySelector('[data-candidate="flower-shop.example"]');
    expect(card).toBeTruthy();
    expect(card?.textContent).toContain('Цветочный магазин — доставка');
    expect(card?.textContent).toContain('купить цветы, доставка букетов');
    expect(content('[data-candidate-occurrences]')).toBe('2');
    expect(content('[data-metric="candidate-flower-shop.example-overall"]')).toBe('25 %');
    expect(content('[data-metric="candidate-flower-shop.example-branded"]')).toBe('—');
    expect(content('[data-metric="candidate-flower-shop.example-ai-model-1"]')).toBe('25 %');
  });

  it('renders «—» for empty denominators, never-found positions and a missing company name', () => {
    render(SeoReport, {
      props: {
        snapshot: snapshot({
          company_name: '',
          aggregates: {
            ...snapshot().aggregates,
            site: {
              search: {
                overall: metric(2, 1, null),
                branded: empty,
                unbranded: metric(1, 1, null),
              },
              ai: {
                'model-1': {
                  name: metric(2, 0),
                  host: metric(2, 1),
                  combined: metric(2, 1),
                  citation: null,
                  position: null,
                  branded: {
                    name: empty,
                    host: empty,
                    combined: empty,
                    citation: null,
                    position: null,
                  },
                  unbranded: {
                    name: metric(2, 0),
                    host: metric(2, 1),
                    combined: metric(2, 1),
                    citation: null,
                    position: null,
                  },
                },
              },
            },
          },
        }),
      },
    });
    expect(content('[data-metric="site-overall"]')).toBe('50 %');
    // No found row, so the average position is unknown.
    expect(screen.getByRole('table', { name: 'Сайт в Яндексе' }).textContent).toContain('—');
    // The company name was never extracted: name and combined shares are unavailable.
    expect(content('[data-metric="ai-model-1-all-name"]')).toBe('—');
    expect(content('[data-metric="ai-model-1-all-combined"]')).toBe('—');
    expect(content('[data-metric="ai-model-1-all-host"]')).toBe('50 %');
  });

  it('shows the saved model answers and the Yandex rows as they are', () => {
    render(SeoReport, {
      props: {
        snapshot: snapshot(),
        rows: { model: [modelRow], search: [searchRow] },
      },
    });
    expect(screen.getByRole('table', { name: 'Ответы моделей' }).textContent).toContain(
      'Ромашка рекомендует доставку цветов',
    );
    const searchTable = screen.getByRole('table', { name: 'Проверки в Яндексе' });
    expect(searchTable.textContent).toContain('Не удалось получить выдачу Яндекса');
    expect(searchTable.textContent).toContain('Ошибка');
    // The failed row is not turned into an absent site.
    expect(document.querySelector('[data-search-detail]')?.getAttribute('data-status')).toBe(
      'error',
    );
  });

  it('keeps a long answer out of the table and opens it as Markdown on click', async () => {
    const long =
      'Первая строка ответа.\n\n### Что уточнить\n- **материалы** и сроки\n' +
      'Подробности ремонта. '.repeat(60);
    const row: SeoModelRow = { ...modelRow, answer: long };
    render(SeoReport, { props: { snapshot: snapshot(), rows: { model: [row], search: [] } } });

    const table = screen.getByRole('table', { name: 'Ответы моделей' });
    const preview = document.querySelector('[data-model-answer-preview]') as HTMLElement;
    // The preview is prose: no Markdown markers, no full answer.
    expect(preview.textContent?.length).toBeLessThanOrEqual(161);
    expect(preview.textContent?.endsWith('…')).toBe(true);
    expect(preview.textContent).toContain('материалы и сроки');
    expect(preview.textContent).not.toContain('**');
    expect(preview.textContent).not.toContain('###');
    expect(table.textContent).not.toContain('Подробности ремонта. '.repeat(60));

    await fireEvent.click(screen.getByRole('button', { name: 'Читать полностью' }));
    const dialog = await screen.findByRole('dialog');
    expect(dialog.getAttribute('aria-modal')).toBe('true');

    // The full text is rendered as Markdown, not as raw markers.
    const body = document.querySelector('[data-answer-full]') as HTMLElement;
    expect(body.querySelector('h3')?.textContent).toBe('Что уточнить');
    expect(body.querySelector('strong')?.textContent).toBe('материалы');
    expect(body.querySelector('li')?.textContent).toContain('материалы');
    expect(body.textContent).toContain('Подробности ремонта.');
    expect(body.textContent).not.toContain('###');
    expect(document.querySelector('[data-answer-caption]')?.textContent).toContain('Модель');
    expect(document.querySelector('[data-answer-caption]')?.textContent).toContain('купить цветы');
    // The row still shows the preview, not the whole answer.
    expect(document.querySelector('[data-model-answer-preview]')?.textContent?.endsWith('…')).toBe(
      true,
    );
  });

  it('sanitizes an answer before it is rendered as Markdown', async () => {
    const row: SeoModelRow = {
      ...modelRow,
      answer:
        '**жирный** текст ответа.\n\n<script>alert(1)</script>\n\n' +
        '<img src=x onerror=alert(2)> ' +
        'хвост '.repeat(40),
    };
    render(SeoReport, { props: { snapshot: snapshot(), rows: { model: [row], search: [] } } });

    await fireEvent.click(screen.getByRole('button', { name: 'Читать полностью' }));
    const body = document.querySelector('[data-answer-full]') as HTMLElement;

    expect(body.querySelector('script')).toBeNull();
    expect(body.querySelector('img')?.getAttribute('onerror')).toBeNull();
    expect(body.querySelector('strong')?.textContent).toBe('жирный');
  });

  it('closes the answer dialog on the button, on Escape, and on the backdrop', async () => {
    const row: SeoModelRow = { ...modelRow, answer: 'я'.repeat(400) };
    render(SeoReport, { props: { snapshot: snapshot(), rows: { model: [row], search: [] } } });
    const trigger = screen.getByRole('button', { name: 'Читать полностью' });

    await fireEvent.click(trigger);
    await fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(trigger);

    await fireEvent.click(trigger);
    await fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();

    await fireEvent.click(trigger);
    await fireEvent.click(document.querySelector('[data-answer-backdrop]') as HTMLElement);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('offers no dialog for an answer that already fits its preview', () => {
    render(SeoReport, { props: { snapshot: snapshot(), rows: { model: [modelRow], search: [] } } });

    expect(document.querySelector('[data-model-answer-preview]')?.textContent).toBe(
      modelRow.answer,
    );
    expect(screen.queryByRole('button', { name: 'Читать полностью' })).toBeNull();
  });

  it('paginates the detail rows through the cursor callbacks', async () => {
    const onMore = vi.fn();
    const view = render(SeoReport, {
      props: {
        snapshot: snapshot(),
        rows: { model: [modelRow], search: [searchRow] },
        cursors: { model: 'cursor-1', search: null },
        onMore,
      },
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Показать ещё' }));
    expect(onMore).toHaveBeenCalledWith('model');

    view.unmount();
    const blocked = render(SeoReport, {
      props: {
        snapshot: snapshot(),
        rows: { model: [modelRow], search: [searchRow] },
        cursors: { model: 'cursor-1', search: null },
        loadingRows: 'model',
        onMore,
      },
    });
    const button = screen.getByRole('button', { name: 'Загружаем…' }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    blocked.unmount();

    render(SeoReport, {
      props: {
        snapshot: snapshot(),
        rows: { model: [], search: [] },
        cursors: { model: null, search: null },
        onMore,
      },
    });
    expect(screen.queryByRole('button', { name: 'Показать ещё' })).toBeNull();
    expect(screen.getByText('Сохранённых ответов моделей нет.')).toBeTruthy();
  });

  it('renders a failed analysis report with empty sections instead of crashing', () => {
    render(SeoReport, {
      props: {
        snapshot: snapshot({
          status: 'failed',
          counters: undefined as unknown as SeoAnalysisSnapshot['counters'],
          aggregates: undefined as unknown as SeoAnalysisSnapshot['aggregates'],
        }),
      },
    });
    expect(content('[data-report-status]')).toBe('Ошибка');
    expect(content('[data-metric="site-overall"]')).toBe('—');
    expect(
      screen.getByText('Повторяющихся кандидатов нет: не хватило успешных ключевых выдач.'),
    ).toBeTruthy();
    expect(screen.getByText('Ответы моделей не сохранены.')).toBeTruthy();
  });
});
