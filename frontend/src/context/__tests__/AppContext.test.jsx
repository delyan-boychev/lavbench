import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { AppProvider, useApp } from '../AppContext';

const mockGet = vi.fn();

vi.mock('../../services/ApiService', () => ({
  default: {
    get: (...args) => mockGet(...args),
  },
}));

vi.mock('../../AuthContext', () => ({
  useAuth: () => ({ currentUser: { id: 1, username: 'testuser' } }),
}));

const mockChallenges = [
  {
    id: 1,
    name: 'Challenge 1',
    tasks: [
      { id: 10, title: 'Task 1' },
      { id: 11, title: 'Task 2' },
    ],
  },
  { id: 2, name: 'Challenge 2', tasks: [{ id: 20, title: 'Task 3' }] },
];

const emptyChallenges = [];

function TestConsumer() {
  const app = useApp();
  return (
    <div>
      <span data-testid="challenges-count">{app.challenges.length}</span>
      <span data-testid="selected-challenge">{app.selectedChallenge?.name || 'none'}</span>
      <span data-testid="selected-task">{app.selectedTask?.title || 'none'}</span>
      <span data-testid="theme">{app.theme}</span>
      <span data-testid="toast-show">{String(app.toast.show)}</span>
      <span data-testid="toast-message">{app.toast.message}</span>
      <span data-testid="toast-type">{app.toast.type}</span>
      <button data-testid="fetch-btn" onClick={app.fetchChallenges}>
        Fetch
      </button>
      <button data-testid="select-challenge" onClick={() => app.setSelectedChallengeById(2)}>
        Select Challenge 2
      </button>
      <button
        data-testid="select-task"
        onClick={() => app.setSelectedTask({ id: 20, title: 'Task 3' })}
      >
        Select Task
      </button>
      <button data-testid="toggle-theme-btn" onClick={app.toggleTheme}>
        Toggle Theme
      </button>
      <button data-testid="toast-btn" onClick={() => app.showToast('Test message', 'error')}>
        Show Toast
      </button>
      <button
        data-testid="confirm-btn"
        onClick={async () => {
          await app.confirm({ title: 'Confirm?', message: 'Are you sure?' });
        }}
      >
        Confirm
      </button>
    </div>
  );
}

function renderWithProvider() {
  return render(
    <AppProvider>
      <TestConsumer />
    </AppProvider>,
  );
}

describe('AppContext', () => {
  beforeEach(() => {
    mockGet.mockReset();
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
      length: 0,
      key: vi.fn(),
    });
    document.documentElement.setAttribute('data-theme', '');
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('initial state has empty challenges and defaults', async () => {
    mockGet.mockResolvedValue({ ok: true, data: emptyChallenges });
    renderWithProvider();
    await waitFor(() => {
      expect(screen.getByTestId('challenges-count').textContent).toBe('0');
    });
    expect(screen.getByTestId('selected-challenge').textContent).toBe('none');
    expect(screen.getByTestId('selected-task').textContent).toBe('none');
    expect(screen.getByTestId('theme').textContent).toBe('dark');
  });

  it('fetchChallenges populates challenges array', async () => {
    mockGet.mockResolvedValue({ ok: true, data: mockChallenges });
    renderWithProvider();
    await waitFor(() => {
      expect(screen.getByTestId('challenges-count').textContent).toBe('2');
    });
    expect(screen.getByTestId('selected-challenge').textContent).toBe('Challenge 1');
  });

  it('setSelectedChallengeById selects correct challenge', async () => {
    mockGet.mockResolvedValue({ ok: true, data: mockChallenges });
    renderWithProvider();
    await waitFor(() => {
      expect(screen.getByTestId('selected-challenge').textContent).toBe('Challenge 1');
    });
    act(() => {
      screen.getByTestId('select-challenge').click();
    });
    await waitFor(() => {
      expect(screen.getByTestId('selected-challenge').textContent).toBe('Challenge 2');
    });
    await waitFor(() => {
      expect(screen.getByTestId('selected-task').textContent).toBe('Task 3');
    });
  });

  it('setSelectedTask selects task', async () => {
    mockGet.mockResolvedValue({ ok: true, data: mockChallenges });
    renderWithProvider();
    await waitFor(() => {
      expect(screen.getByTestId('challenges-count').textContent).toBe('2');
    });
    act(() => {
      screen.getByTestId('select-task').click();
    });
    await waitFor(() => {
      expect(screen.getByTestId('selected-task').textContent).toBe('Task 3');
    });
  });

  it('toggleTheme switches theme', async () => {
    mockGet.mockResolvedValue({ ok: true, data: emptyChallenges });
    renderWithProvider();
    await waitFor(() => {
      expect(screen.getByTestId('theme').textContent).toBe('dark');
    });
    act(() => {
      screen.getByTestId('toggle-theme-btn').click();
    });
    expect(screen.getByTestId('theme').textContent).toBe('light');
    act(() => {
      screen.getByTestId('toggle-theme-btn').click();
    });
    expect(screen.getByTestId('theme').textContent).toBe('dark');
  });

  it('showToast creates toast that auto-dismisses after 4s', async () => {
    vi.useFakeTimers();
    mockGet.mockResolvedValue({ ok: true, data: emptyChallenges });
    renderWithProvider();

    await act(() => Promise.resolve());

    expect(screen.getByTestId('toast-show').textContent).toBe('false');

    act(() => {
      screen.getByTestId('toast-btn').click();
    });
    expect(screen.getByTestId('toast-show').textContent).toBe('true');
    expect(screen.getByTestId('toast-message').textContent).toBe('Test message');
    expect(screen.getByTestId('toast-type').textContent).toBe('error');

    act(() => {
      vi.advanceTimersByTime(4000);
    });
    expect(screen.getByTestId('toast-show').textContent).toBe('false');
    vi.useRealTimers();
  });

  it('confirm returns a promise', async () => {
    let capturedConfirm;
    function Capture() {
      // eslint-disable-next-line react-hooks/globals
      capturedConfirm = useApp().confirm;
      return null;
    }
    mockGet.mockResolvedValue({ ok: true, data: emptyChallenges });
    render(
      <AppProvider>
        <Capture />
      </AppProvider>,
    );

    await waitFor(() => {
      expect(capturedConfirm).toBeDefined();
    });

    const promise = capturedConfirm({ title: 'Test', message: 'Test' });
    expect(promise).toBeInstanceOf(Promise);
  });
});
