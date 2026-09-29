// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import SeoForm from './SeoForm.svelte';
import type { FormConfig, PublicProvider } from '$lib/types';

const form: FormConfig = {
  limits: { max_prompts: 20, max_providers: 5, max_prompt_length: 500, max_brand_length: 200, max_domain_length: 253 },
  new_provider_fields: [], default_provider_ids: ['model-1'], scope_options: []
};

const ready: PublicProvider = {
  id: 'model-1', name: 'Модель 1', kind: 'custom', endpoint: null, model: 'test-model', configured: true,
  editable_fields: [], can_reset: false, can_delete: true,
  status_label: '', delete_label: '', delete_prompt: '', delete_success: ''
};
const second: PublicProvider = { ...ready, id: 'model-2', name: 'Модель 2', model: 'other-model' };
const unavailable: PublicProvider = { ...ready, id: 'model-3', name: 'Модель 3', configured: false, status_label: 'Нет ключа' };
const providers = [ready, second, unavailable];

async function fill(values: { url?: string; sphere?: string; seeds?: string[]; services?: string } = {}) {
  await fireEvent.input(screen.getByRole('textbox', { name: /Адрес главной страницы/ }), { target: { value: values.url ?? 'https://example.ru' } });
  await fireEvent.input(screen.getByRole('textbox', { name: /Сфера бизнеса/ }), { target: { value: values.sphere ?? 'Цветы' } });
  const seeds = values.seeds ?? ['купить цветы', 'доставка букетов', 'цветочный магазин'];
  await fireEvent.input(screen.getByRole('textbox', { name: /Первый ключевой запрос/ }), { target: { value: seeds[0] } });
  await fireEvent.input(screen.getByRole('textbox', { name: /Второй ключевой запрос/ }), { target: { value: seeds[1] } });
  await fireEvent.input(screen.getByRole('textbox', { name: /Третий ключевой запрос/ }), { target: { value: seeds[2] } });
  await fireEvent.input(screen.getByRole('textbox', { name: /Услуги/ }), { target: { value: values.services ?? 'Доставка цветов\nБукеты' } });
}

describe('SeoForm', () => {
  it('renders the five fields and defaults the connections from the form config', () => {
    render(SeoForm, { props: { providers, form, onSubmit: vi.fn() } });
    expect(screen.getByRole('textbox', { name: /Адрес главной страницы/ })).toBeTruthy();
    expect(screen.getByRole('textbox', { name: /Сфера бизнеса/ })).toBeTruthy();
    expect(screen.getByRole('textbox', { name: /Первый ключевой запрос/ })).toBeTruthy();
    expect(screen.getByRole('textbox', { name: /Второй ключевой запрос/ })).toBeTruthy();
    expect(screen.getByRole('textbox', { name: /Третий ключевой запрос/ })).toBeTruthy();
    expect(screen.getByRole('textbox', { name: /Услуги/ })).toBeTruthy();
    expect((screen.getByRole('checkbox', { name: /Модель 1/ }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole('checkbox', { name: /Модель 2/ }) as HTMLInputElement).checked).toBe(false);
    const off = screen.getByRole('checkbox', { name: /Модель 3/ }) as HTMLInputElement;
    expect(off.disabled).toBe(true);
    expect(off.checked).toBe(false);
  });

  it('shows the upper estimate for the selected connections and the paid-run notices', async () => {
    render(SeoForm, { props: { providers, form, onSubmit: vi.fn() } });
    expect(screen.getByText('43')).toBeTruthy();
    expect(screen.getByText('40')).toBeTruthy();
    await fireEvent.click(screen.getByRole('checkbox', { name: /Модель 2/ }));
    expect(screen.getByText('80')).toBeTruthy();
    expect(screen.getByText(/служебные шаги/i)).toBeTruthy();
    expect(screen.getByText(/платные вызовы/i)).toBeTruthy();
    expect(screen.getByText(/отложенном режиме/i)).toBeTruthy();
  });

  it('validates before submitting and keeps the form usable', async () => {
    const onSubmit = vi.fn();
    render(SeoForm, { props: { providers, form, onSubmit } });
    await fill();
    await fireEvent.input(screen.getByRole('textbox', { name: /Третий ключевой запрос/ }), { target: { value: '' } });
    await fireEvent.click(screen.getByRole('button', { name: /Запустить анализ/ }));
    expect(screen.getByRole('alert').textContent).toMatch(/ровно 3/);
    expect(onSubmit).not.toHaveBeenCalled();

    await fill({ seeds: ['купить цветы', 'купить цветы', 'третий'] });
    await fireEvent.click(screen.getByRole('button', { name: /Запустить анализ/ }));
    expect(screen.getByRole('alert').textContent).toMatch(/не должны повторяться/);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('submits the parsed services and the selected connections', async () => {
    const onSubmit = vi.fn();
    render(SeoForm, { props: { providers, form, onSubmit } });
    await fill();
    await fireEvent.click(screen.getByRole('checkbox', { name: /Модель 2/ }));
    await fireEvent.click(screen.getByRole('button', { name: /Запустить анализ/ }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).toEqual({
      url: 'https://example.ru',
      sphere: 'Цветы',
      seeds: ['купить цветы', 'доставка букетов', 'цветочный магазин'],
      services: ['Доставка цветов', 'Букеты'],
      connectionIds: ['model-1', 'model-2']
    });
  });

  it('blocks the run when no connection is selected', async () => {
    render(SeoForm, { props: { providers, form: { ...form, default_provider_ids: [] }, onSubmit: vi.fn() } });
    await fill();
    await fireEvent.click(screen.getByRole('button', { name: /Запустить анализ/ }));
    expect(screen.getByRole('alert').textContent).toMatch(/от 1 до 5/);
  });

  it('shows the load error and disables the run without configuration', () => {
    render(SeoForm, { props: { providers: [], form: null, disabled: true, error: 'Python API недоступен', onSubmit: vi.fn() } });
    expect(screen.getByRole('alert').textContent).toContain('Python API недоступен');
    expect((screen.getByRole('button', { name: /Запустить анализ/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('reports a rejected request and re-enables the button', async () => {
    const onError = vi.fn();
    const onSubmit = vi.fn(() => Promise.reject(new Error('Сервер отклонил запуск')));
    render(SeoForm, { props: { providers, form, onSubmit, onError } });
    await fill();
    await fireEvent.click(screen.getByRole('button', { name: /Запустить анализ/ }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/Сервер отклонил запуск/));
    expect(onError).toHaveBeenCalledWith('Сервер отклонил запуск');
    expect((screen.getByRole('button', { name: /Запустить анализ/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('falls back to a safe sentence when the rejection carries no message', async () => {
    render(SeoForm, { props: { providers, form, onSubmit: vi.fn(() => Promise.reject(new Error(''))) } });
    await fill();
    await fireEvent.click(screen.getByRole('button', { name: /Запустить анализ/ }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/Не удалось запустить анализ/));
  });
});
