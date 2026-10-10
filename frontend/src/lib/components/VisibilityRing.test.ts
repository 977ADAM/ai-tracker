// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, expect, it } from 'vitest';
import VisibilityRing from './VisibilityRing.svelte';

afterEach(cleanup);

it('explains all received answers including unknown sentiment and absent brand', async () => {
  render(VisibilityRing, {
    successful: 10,
    visibility: 0.8,
    sentiment: { positive: 2, neutral: 4, negative: 0, unknown: 2 },
    delta: -4,
  });
  const trigger = screen.getByRole('button', { name: /Видимость в ИИ: 80 процентов/ });
  await fireEvent.click(trigger);
  const tooltip = screen.getByRole('tooltip');
  expect(trigger.getAttribute('aria-describedby')).toBe(tooltip.id);
  expect(tooltip.className).not.toContain('hidden');
  expect(screen.getByText('Без упоминания бренда').parentElement?.textContent).toContain('2');
  expect(screen.getByText('Тональность не определена').parentElement?.textContent).toContain('2');
  expect(screen.getByText('Всего получено: 10')).toBeTruthy();
  expect(screen.getByText('-4 п.п.').getAttribute('title')).toContain('к предыдущему замеру');
  await fireEvent.click(trigger);
  expect(tooltip.className).toContain('hidden');
});

it('does not invent a distribution when no answers were received', async () => {
  render(VisibilityRing, {
    successful: 0,
    visibility: null,
    sentiment: { positive: 0, neutral: 0, negative: 0, unknown: 0 },
  });
  await fireEvent.click(screen.getByRole('button'));
  expect(screen.getByText('Успешных ответов пока нет.')).toBeTruthy();
  expect(screen.queryByText('Без упоминания бренда')).toBeNull();
});
