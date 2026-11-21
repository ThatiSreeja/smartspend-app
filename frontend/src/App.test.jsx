import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';

const { post, get, interceptors } = vi.hoisted(() => ({
  post: vi.fn(), get: vi.fn(), interceptors: {},
}));
vi.mock('axios', () => ({ default: { create: () => ({
  interceptors: { request: { use: vi.fn() }, response: { use: (_, rejected) => { interceptors.rejected = rejected; } } },
  post, get, put: vi.fn(), delete: vi.fn(),
}) } }));
vi.mock('recharts', async (importOriginal) => ({
  ...await importOriginal(),
  ResponsiveContainer: ({ children }) => children,
  BarChart: ({ data }) => <output aria-label="Chart data">{JSON.stringify(data)}</output>,
}));
import App from './App.jsx';

describe('SmartSpend authentication screens', () => {
  beforeEach(() => { localStorage.clear(); sessionStorage.clear(); post.mockReset(); get.mockReset(); window.history.pushState({}, '', '/register'); });
  afterEach(cleanup);

  it('registers and stores the returned session', async () => {
    post.mockResolvedValue({ data: { access_token: 'test-token', user: { id: 1, name: 'Alex Example', email: 'alex@example.com', currency: 'INR' } } });
    get.mockResolvedValue({ data: {} });
    render(<BrowserRouter><App /></BrowserRouter>);
    fireEvent.change(screen.getByLabelText('Your name'), { target: { value: 'Alex Example' } });
    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'alex@example.com' } });
    fireEvent.change(screen.getByLabelText(/Password/), { target: { value: 'correct horse 71' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }));
    await waitFor(() => expect(sessionStorage.getItem('smartspend_token')).toBe('test-token'));
    expect(localStorage.getItem('smartspend_token')).toBeNull();
    expect(post).toHaveBeenCalledWith('/auth/register', expect.objectContaining({ email: 'alex@example.com' }),
      expect.objectContaining({ skipSessionAuth: true }));
  });

  it('passes the selected month to the API and renders the returned chart and category data', async () => {
    sessionStorage.setItem('smartspend_token', 'test-token');
    sessionStorage.setItem('smartspend_user', JSON.stringify({ id: 1, name: 'Alex Example', currency: 'INR' }));
    sessionStorage.setItem('smartspend_chat:1', '[]');
    window.history.pushState({}, '', '/');
    const months = Array.from({ length: 12 }, (_, index) => ({
      month: new Date(2000, index, 1).toLocaleString('en', { month: 'long' }),
      income: index === 4 ? 100 : 0, expenses: index === 4 ? 42.25 : 0,
    }));
    get.mockImplementation((path, config) => Promise.resolve({
      data: path === '/auth/me' ? { user: { id: 1, name: 'Alex Example', currency: 'INR' } } :
        { income: 100, expenses: 42.25, balance: 57.75,
          months: config.params.year === 2025 ? months.map(row => ({ ...row, income: 0, expenses: 0 })) : months,
          categories: [{ name: 'Food', amount: 42.25 }] },
    }));
    post.mockResolvedValue({});
    render(<BrowserRouter><App /></BrowserRouter>);
    expect(await screen.findByText('Food')).toBeTruthy();
    expect(screen.getByLabelText('Chart data').textContent).toBe(JSON.stringify(months));
    fireEvent.change(screen.getByLabelText('Month'), { target: { value: '5' } });
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/dashboard', expect.objectContaining({ params: { month: 5, year: expect.any(Number) } })));
    fireEvent.change(screen.getByLabelText('Year'), { target: { value: '2025' } });
    const updatedChart = await screen.findByLabelText('Chart data');
    expect(JSON.parse(updatedChart.textContent)).toEqual(months.map(row => ({ ...row, income: 0, expenses: 0 })));
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(sessionStorage.getItem('smartspend_token')).toBeNull();
    expect(sessionStorage.getItem('smartspend_chat:1')).toBeNull();
  });

  it('clears the old dashboard immediately and ignores out-of-order period responses', async () => {
    sessionStorage.setItem('smartspend_token', 'saved-token');
    const pending = [];
    get.mockImplementation((path, config) => path === '/auth/me' ?
      Promise.resolve({ data: { user: { id: 1, name: 'Alex Example' } } }) :
      new Promise(resolve => pending.push({ ...config, resolve })));
    window.history.pushState({}, '', '/');
    render(<BrowserRouter><App /></BrowserRouter>);
    const picker = await screen.findByLabelText('Month');
    fireEvent.change(screen.getByLabelText('Year'), { target: { value: '2026' } });
    fireEvent.change(picker, { target: { value: '9' } });
    const september = { income: 45000, expenses: 24500, balance: 20500, savings_rate: 45.6,
      categories: [{ name: 'September category', amount: 24500 }], transaction_count: 3 };
    await act(async () => pending.at(-1).resolve({ data: september }));
    expect(screen.getByText('September category')).toBeTruthy();
    fireEvent.change(picker, { target: { value: '10' } });
    const october = pending.at(-1);
    fireEvent.change(picker, { target: { value: '11' } });
    expect(screen.queryByText('September category')).toBeNull();
    expect(screen.getByRole('status').textContent).toContain('November 2026');
    await act(async () => pending.at(-1).resolve({ data: {
      income: 0, expenses: 0, balance: 0, savings_rate: 0, categories: [], recent: [], transaction_count: 0,
    } }));
    expect(screen.getByText('No transactions found for November 2026.')).toBeTruthy();
    await act(async () => october.resolve({ data: september }));
    expect(screen.getByText('No transactions found for November 2026.')).toBeTruthy();
    expect(screen.queryByText('September category')).toBeNull();
  });

  it('reports failed sign-in without exposing details from a server', async () => {
    post.mockRejectedValue({ response: { data: { error: 'Email or password is incorrect.' } } });
    window.history.pushState({}, '', '/login');
    render(<BrowserRouter><App /></BrowserRouter>);
    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'alex@example.com' } });
    fireEvent.change(screen.getByLabelText(/Password/), { target: { value: 'badpassword' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText('Email or password is incorrect.')).toBeTruthy();
  });

  it('keeps a new session when an older request returns an authentication error', async () => {
    const account = { id: 1, name: 'Alex Example', email: 'alex@example.com', currency: 'INR' };
    get.mockResolvedValue({ data: { user: account } });
    post.mockImplementation(path => Promise.resolve({
      data: path === '/auth/login' ? { access_token: 'new-token', user: account } : {},
    }));
    window.history.pushState({}, '', '/login');
    render(<BrowserRouter><App /></BrowserRouter>);
    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: account.email } });
    fireEvent.change(screen.getByLabelText(/Password/), { target: { value: 'correct horse 71' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await screen.findByRole('button', { name: 'Sign out' });
    await act(async () => {
      for (const [token, code] of [['old-token', 'invalid_session'], ['new-token', undefined]]) {
        await expect(interceptors.rejected({
          config: { headers: { Authorization: `Bearer ${token}` } },
          response: { status: 401, data: { code } },
        })).rejects.toBeTruthy();
      }
    });
    await waitFor(() => expect(sessionStorage.getItem('smartspend_token')).toBe('new-token'));
  });

  it('waits for session restoration before loading protected data', async () => {
    sessionStorage.setItem('smartspend_token', 'saved-token');
    let restore;
    get.mockImplementationOnce(() => new Promise(resolve => { restore = resolve; }));
    get.mockImplementation(path => Promise.resolve({
      data: path === '/categories' ? [] : { items: [], page: 1, total: 0 },
    }));
    window.history.pushState({}, '', '/transactions');
    render(<BrowserRouter><App /></BrowserRouter>);
    expect(screen.getByRole('status').textContent).toContain('Checking your session');
    expect(get.mock.calls.map(([path]) => path)).toEqual(['/auth/me']);
    await act(async () => restore({ data: { user: { id: 1, name: 'Alex Example' } } }));
    await screen.findByRole('heading', { name: 'Transactions' });
    expect(get.mock.calls.some(([path]) => path === '/transactions')).toBe(true);
  });

  it('submits only one login while a request is pending', async () => {
    let complete;
    post.mockImplementation(() => new Promise(resolve => { complete = resolve; }));
    get.mockResolvedValue({ data: {} });
    window.history.pushState({}, '', '/login');
    render(<BrowserRouter><App /></BrowserRouter>);
    const field = screen.getByLabelText('Email address');
    fireEvent.change(field, { target: { value: 'alex@example.com' } });
    fireEvent.change(screen.getByLabelText(/Password/), { target: { value: 'correct horse 71' } });
    fireEvent.submit(field.form);
    fireEvent.submit(field.form);
    expect(post).toHaveBeenCalledTimes(1);
    await act(async () => complete({ data: { access_token: 'new-token', user: { id: 1, name: 'Alex Example' } } }));
    expect(await screen.findByRole('button', { name: 'Sign out' })).toBeTruthy();
  });
});
