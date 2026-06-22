import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { AuthProvider, useAuth } from '../AuthContext';

function TestConsumer() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(auth.authLoading)}</span>
      <span data-testid="has-user">{String(!!auth.currentUser)}</span>
      <button data-testid="login-btn" onClick={() => auth.login('testuser', 'password123')}>
        Login
      </button>
      <button data-testid="logout-btn" onClick={() => auth.logout()}>
        Logout
      </button>
      <span data-testid="error">{String(auth.authError || '')}</span>
    </div>
  );
}

const mockGet = vi.fn();
const mockPost = vi.fn();

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
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );
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
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );
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
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId('has-user').textContent).toBe('true');
    });
    act(() => {
      screen.getByTestId('logout-btn').click();
    });
    await waitFor(() => {
      expect(screen.getByTestId('has-user').textContent).toBe('false');
    });
  });

  it('logs in successfully with valid credentials', async () => {
    mockPost.mockResolvedValue({
      ok: true,
      data: { user: { id: 1, username: 'testuser', role: 'competitor' } },
    });
    mockGet.mockResolvedValue({ ok: false });
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );
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

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await act(async () => {
      screen.getByTestId('login-btn').click();
    });

    waitFor(() => {
      expect(screen.getByTestId('error').textContent).toBeTruthy();
    });
  });
});
