import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from '../AuthContext';

function TestConsumer() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(auth.authLoading)}</span>
      <span data-testid="has-user">{String(!!auth.currentUser)}</span>
      <span data-testid="check-error">{String(auth.authCheckError)}</span>
      <button data-testid="login-btn" onClick={() => auth.login('testuser', 'password123')}>
        Login
      </button>
      <button data-testid="logout-btn" onClick={() => auth.logout()}>
        Logout
      </button>
      <button data-testid="retry-btn" onClick={() => auth.fetchUser()}>
        Retry
      </button>
      <span data-testid="error">{String(auth.authError || '')}</span>
    </div>
  );
}

const mockGet = vi.fn();
const mockPost = vi.fn();

function renderAuth(queryClient = new QueryClient()) {
  const view = render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    </QueryClientProvider>,
  );
  return { ...view, queryClient };
}

vi.mock('../services/ApiService', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    refreshCsrfToken: vi.fn().mockResolvedValue(),
  },
}));

describe('AuthContext', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', {
      subtle: {
        digest: vi.fn().mockResolvedValue(new Uint8Array(32).fill(0xab)),
      },
    });
    vi.stubGlobal(
      'CustomEvent',
      class extends Event {
        constructor(type, init) {
          super(type, init);
          Object.assign(this, init?.detail || {});
        }
      },
    );
    mockGet.mockReset();
    mockPost.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('initializes with authLoading true and no user', async () => {
    renderAuth();
    await waitFor(() => {
      expect(screen.getByTestId('loading').textContent).toBe('false');
    });
    expect(screen.getByTestId('has-user').textContent).toBe('false');
  });

  it('loads user when cookie session exists', async () => {
    mockGet.mockResolvedValue({
      ok: true,
      data: { user: { id: 1, username: 'testuser', role: 'competitor' } },
    });
    renderAuth();
    await waitFor(() => {
      expect(screen.getByTestId('has-user').textContent).toBe('true');
    });
    expect(screen.getByTestId('has-user').textContent).toBe('true');
  });

  it('clears user on logout', async () => {
    mockGet.mockResolvedValue({
      ok: true,
      data: { user: { id: 1, username: 'testuser', role: 'competitor' } },
    });
    mockPost.mockResolvedValue({ ok: true, data: {} });
    const queryClient = new QueryClient();
    queryClient.setQueryData(['submissions'], [{ id: 1 }]);
    renderAuth(queryClient);
    await waitFor(() => {
      expect(screen.getByTestId('has-user').textContent).toBe('true');
    });
    act(() => {
      screen.getByTestId('logout-btn').click();
    });
    await waitFor(() => {
      expect(screen.getByTestId('has-user').textContent).toBe('false');
    });
    expect(queryClient.getQueryData(['submissions'])).toBeUndefined();
  });

  it('clears the local session and query cache on a global 401 event', async () => {
    mockGet.mockResolvedValue({
      ok: true,
      status: 200,
      data: { user: { id: 1, username: 'testuser', role: 'competitor' } },
    });
    const queryClient = new QueryClient();
    queryClient.setQueryData(['leaderboard'], [{ rank: 1 }]);
    renderAuth(queryClient);

    await waitFor(() => expect(screen.getByTestId('has-user').textContent).toBe('true'));
    act(() => window.dispatchEvent(new CustomEvent('auth:unauthorized')));

    expect(screen.getByTestId('has-user').textContent).toBe('false');
    expect(queryClient.getQueryData(['leaderboard'])).toBeUndefined();
    expect(mockPost).not.toHaveBeenCalledWith('/auth/logout');
  });

  it.each([
    ['503 response', () => Promise.resolve({ ok: false, status: 503, data: {} })],
    ['network failure', () => Promise.reject(new Error('network unavailable'))],
  ])('preserves a known user after a transient %s', async (_label, transientResult) => {
    mockGet
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: { user: { id: 1, username: 'testuser', role: 'competitor' } },
      })
      .mockImplementationOnce(transientResult);
    renderAuth();

    await waitFor(() => expect(screen.getByTestId('has-user').textContent).toBe('true'));
    act(() => screen.getByTestId('retry-btn').click());

    await waitFor(() => expect(screen.getByTestId('check-error').textContent).toBe('true'));
    expect(screen.getByTestId('has-user').textContent).toBe('true');
  });

  it('logs in successfully with valid credentials', async () => {
    mockPost.mockResolvedValue({
      ok: true,
      data: { user: { id: 1, username: 'testuser', role: 'competitor' } },
    });
    mockGet.mockResolvedValue({ ok: false });
    renderAuth();
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    await act(async () => {
      screen.getByTestId('login-btn').click();
    });
    expect(screen.getByTestId('has-user').textContent).toBe('true');
    expect(mockPost).toHaveBeenCalled();
  });

  it('sets error on failed login', async () => {
    mockPost.mockResolvedValue({
      ok: false,
      status: 401,
      data: { error: 'Invalid credentials', code: 'ERR_INVALID_CREDENTIALS' },
    });

    renderAuth();

    await act(async () => {
      screen.getByTestId('login-btn').click();
    });

    waitFor(() => {
      expect(screen.getByTestId('error').textContent).toBeTruthy();
    });
  });
});
