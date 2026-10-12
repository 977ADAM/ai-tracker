// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, expect, it, vi } from 'vitest';
import PromptSetup from './PromptSetup.svelte';

vi.mock('$app/paths', () => ({ base: '/clustering/tracker' }));
afterEach(cleanup);
it('offers import templates beneath the deployed base path', async () => {
  render(PromptSetup, { queries: [], onGenerate: () => {} });
  await fireEvent.click(screen.getByRole('tab', { name: 'Из списка' }));
  expect(screen.getByRole('link', { name: '▧ xlsx' }).getAttribute('href')).toBe(
    '/clustering/tracker/templates/prompts.xlsx',
  );
});
