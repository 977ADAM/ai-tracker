// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import ChatComposer from './ChatComposer.svelte';

describe('ChatComposer', () => {
  it('sends on Enter and keeps Shift+Enter for a new line', async () => {
    const onSend = vi.fn();
    render(ChatComposer, { props: { onSend } });
    const box = screen.getByRole('textbox');

    await fireEvent.keyDown(box, { key: 'Enter', shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();

    await fireEvent.input(box, { target: { value: 'проверь\nсайт' } });
    await fireEvent.keyDown(box, { key: 'Enter' });
    expect(onSend).toHaveBeenCalledWith('проверь\nсайт');
  });

  it('sends the typed text once and clears the field', async () => {
    const onSend = vi.fn();
    render(ChatComposer, { props: { onSend } });
    const box = screen.getByRole('textbox') as HTMLTextAreaElement;

    await fireEvent.input(box, { target: { value: '  проверь сайт  ' } });
    await fireEvent.keyDown(box, { key: 'Enter' });
    expect(onSend).toHaveBeenCalledWith('проверь сайт');
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(box.value).toBe('');
  });

  it('sends the same text from the button', async () => {
    const onSend = vi.fn();
    render(ChatComposer, { props: { onSend } });
    await fireEvent.input(screen.getByRole('textbox'), { target: { value: 'привет' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Отправить' }));
    expect(onSend).toHaveBeenCalledWith('привет');
  });

  it('never sends an empty message', async () => {
    const onSend = vi.fn();
    render(ChatComposer, { props: { onSend } });
    await fireEvent.input(screen.getByRole('textbox'), { target: { value: '   ' } });
    await fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect(onSend).not.toHaveBeenCalled();
    expect((screen.getByRole('button', { name: 'Отправить' }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it('disables the composer while an answer is pending', () => {
    render(ChatComposer, { props: { onSend: vi.fn(), busy: true } });
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(true);
    expect(
      (screen.getByRole('button', { name: 'Отправляем…' }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it('disables the composer when the page says so', () => {
    render(ChatComposer, { props: { onSend: vi.fn(), disabled: true } });
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(true);
  });

  it('says what the field is waiting for while the answer is pending', () => {
    const view = render(ChatComposer, { props: { onSend: vi.fn(), busy: true } });
    expect(screen.getByRole('button', { name: 'Отправляем…' })).toBeTruthy();
    view.unmount();

    render(ChatComposer, { props: { onSend: vi.fn() } });
    expect(screen.getByRole('button', { name: 'Отправить' })).toBeTruthy();
  });
});
