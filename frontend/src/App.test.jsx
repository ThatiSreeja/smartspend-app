import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';

const { post } = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock('axios', () => ({ default: { create: () => ({
  interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  post, get: vi.fn(), put: vi.fn(), delete: vi.fn(),
}) } }));
import App from './App.jsx';

describe('SmartSpend authentication screens', () => {
  beforeEach(() => { localStorage.clear(); post.mockReset(); window.history.pushState({}, '', '/register'); });
  afterEach(cleanup);

  it('registers and stores the returned session', async () => {
    post.mockResolvedValue({ data: { access_token: 'test-token', user: { id: 1, name: 'Alex Example', email: 'alex@example.com', currency: 'INR' } } });
    render(<BrowserRouter><App /></BrowserRouter>);
    fireEvent.change(screen.getByLabelText('Your name'), { target: { value: 'Alex Example' } });
    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'alex@example.com' } });
    fireEvent.change(screen.getByLabelText(/Password/), { target: { value: 'correct horse 71' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }));
    await waitFor(() => expect(localStorage.getItem('smartspend_token')).toBe('test-token'));
    expect(post).toHaveBeenCalledWith('/auth/register', expect.objectContaining({ email: 'alex@example.com' }));
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
});
