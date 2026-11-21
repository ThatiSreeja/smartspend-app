import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import AssistantChat from './AssistantChat';

const formatError = error => error.message;

function send(text) {
  const input = screen.getByRole('textbox', { name: 'Message' });
  fireEvent.change(input, { target: { value: text } });
  fireEvent.submit(input.closest('form'));
}

describe('Financial assistant chat', () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(cleanup);

  it('sends context, shows a typing indicator and renders structured answers', async () => {
    let finish;
    const sendQuestion = vi.fn()
      .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
      .mockResolvedValueOnce({ answer: 'April transactions', display: {
        type: 'transactions', rows: [{ date: '2025-04-10', name: 'Food', description: 'Groceries', type: 'expense', display: '₹50.00' }],
      } });
    render(<AssistantChat userId={1} sendQuestion={sendQuestion} formatError={formatError} />);
    fireEvent.click(screen.getByRole('button', { name: 'Analyze my May expenses' }));
    expect(screen.getByRole('textbox').value).toBe('Analyze my May expenses');
    send('What were my expenses in May?');
    expect(screen.getByRole('status').textContent).toContain('typing');
    finish({ answer: 'May expenses: ₹100.00' });
    await screen.findByText('May expenses: ₹100.00');
    send('What about April?');
    expect(await screen.findByRole('table')).toBeTruthy();
    expect(within(screen.getByRole('table')).getByText('₹50.00')).toBeTruthy();
    expect(within(screen.getByRole('table')).getByText('Groceries')).toBeTruthy();
    expect(sendQuestion).toHaveBeenLastCalledWith({
      question: 'What about April?', history: ['What were my expenses in May?'],
    }, expect.any(AbortSignal));
    expect(screen.getByRole('log').querySelectorAll('time')).toHaveLength(4);
  });

  it('shows category amounts, transaction counts, and shares in a table', async () => {
    const sendQuestion = vi.fn().mockResolvedValue({ answer: 'Selected category spending', display: {
      type: 'categories',
      rows: [{ name: 'Food', amount: '50.00', display: '₹50.00', count: 2, percentage: '25.00%' }],
      summary: { display: '₹50.00', count: 2, percentage: '25.00%', partial: true },
    } });
    render(<AssistantChat userId={1} sendQuestion={sendQuestion} formatError={formatError} />);
    send('How much did I spend on food?');
    const table = within(await screen.findByRole('table', { name: 'Expenses by category' }));
    expect(table.getByRole('columnheader', { name: 'Share of expenses' })).toBeTruthy();
    expect(table.getByRole('row', { name: 'Food ₹50.00 2 25.00%' })).toBeTruthy();
    expect(table.getByRole('row', { name: 'Selected total ₹50.00 2 25.00%' })).toBeTruthy();
  });

  it('restores only the active account conversation and clears it', async () => {
    const props = { sendQuestion: vi.fn().mockResolvedValue({ answer: 'Your saved answer' }), formatError };
    const first = render(<AssistantChat userId={1} {...props} />);
    send('What were my savings?');
    await screen.findByText('Your saved answer');
    first.unmount();
    const second = render(<AssistantChat userId={2} {...props} />);
    expect(screen.queryByText('Your saved answer')).toBeNull();
    second.unmount();
    render(<AssistantChat userId={1} {...props} />);
    expect(screen.getByText('Your saved answer')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Clear conversation' }));
    expect(screen.queryByText('Your saved answer')).toBeNull();
    expect(JSON.parse(sessionStorage.getItem('smartspend_chat:1'))).toEqual([]);
  });

  it('shows request errors and restores the unsent question for retry', async () => {
    render(<AssistantChat userId={1} sendQuestion={vi.fn().mockRejectedValue(new Error('Records unavailable'))}
      formatError={formatError} />);
    send('What is my income?');
    expect((await screen.findByRole('alert')).textContent).toBe('Records unavailable');
    await waitFor(() => expect(screen.getByRole('textbox').value).toBe('What is my income?'));
  });

  it('keeps Shift+Enter for composing and sends multiline text with Enter', async () => {
    const sendQuestion = vi.fn().mockResolvedValue({ answer: 'Money is a medium of exchange.' });
    render(<AssistantChat userId={1} sendQuestion={sendQuestion} formatError={formatError} />);
    const input = screen.getByRole('textbox', { name: 'Message' });
    fireEvent.change(input, { target: { value: 'What is money?' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(sendQuestion).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: 'What is money?\nGive an example.' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(await screen.findByText('Money is a medium of exchange.')).toBeTruthy();
    expect(sendQuestion).toHaveBeenCalledWith({
      question: 'What is money?\nGive an example.', history: [],
    }, expect.any(AbortSignal));
  });
});
