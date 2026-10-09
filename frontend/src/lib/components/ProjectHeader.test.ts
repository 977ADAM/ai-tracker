// @vitest-environment jsdom
import { render, screen, fireEvent } from '@testing-library/svelte';
import { expect, it } from 'vitest';
import ProjectHeader from './ProjectHeader.svelte';
it('renders breadcrumbs and switches the report view', async () => {
  render(ProjectHeader, {
    project: { id: 'p1', name: 'Додопицца — проект', brand: 'Додопицца' },
    ready: true,
    onStart: () => {},
    onDelete: () => {},
    onRename: async () => {},
  });
  expect(screen.getByRole('navigation', { name: 'Хлебные крошки' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Все упоминания' }).getAttribute('aria-pressed')).toBe(
    'true',
  );
  await fireEvent.click(screen.getByRole('button', { name: 'Источники упоминаний' }));
  expect(
    screen.getByRole('button', { name: 'Источники упоминаний' }).getAttribute('aria-pressed'),
  ).toBe('true');
  expect(screen.getByRole('button', { name: 'Обновить' })).toBeTruthy();
});
