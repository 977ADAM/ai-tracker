// @vitest-environment jsdom
import { render, screen } from '@testing-library/svelte';
import { expect, it } from 'vitest';
import Page from './+page.svelte';
it('offers project creation without a chat', () => {
  render(Page, { data: { projects: { items: [], cursor: null }, projectsError: '' } });
  expect(screen.getByRole('heading', { name: 'Проекты' })).toBeTruthy();
  expect(screen.getAllByRole('link', { name: /Создать проект/ }).length).toBe(2);
  expect(screen.queryByRole('textbox')).toBeNull();
  expect(
    screen.getByText('Укажите бренд и сайт. Запросы и модели добавьте внутри проекта.'),
  ).toBeTruthy();
});
