import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';
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
    await act(async () => {});
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
    await act(async () => {});
    await waitFor(() => {
      expect(screen.getByTestId('challenges-count').textContent).toBe('2');
    });
    expect(screen.getByTestId('selected-challenge').textContent).toBe('Challenge 1');
  });

  it('setSelectedChallengeById selects correct challenge', async () => {
    mockGet.mockResolvedValue({ ok: true, data: mockChallenges });
    renderWithProvider();
    await act(async () => {});
    await waitFor(() => {
      expect(screen.getByTestId('challenges-count').textContent).toBe('2');
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
    await act(async () => {});
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
    await act(async () => {});
    await waitFor(() => {
      expect(screen.getByTestId('theme').textContent).toBe('dark');
    });
    await act(async () => {
      screen.getByTestId('toggle-theme-btn').click();
    });
    await act(async () => {});
    await waitFor(() => {
      expect(screen.getByTestId('theme').textContent).toBe('light');
    });
    await act(async () => {
      screen.getByTestId('toggle-theme-btn').click();
    });
    await act(async () => {});
    await waitFor(() => {
      expect(screen.getByTestId('theme').textContent).toBe('dark');
    });
  });

  it('showToast creates toast that auto-dismisses after 4s', async () => {
    vi.useFakeTimers();
    mockGet.mockResolvedValue({ ok: true, data: emptyChallenges });
    renderWithProvider();
    await act(async () => {});

    expect(screen.getByTestId('toast-show').textContent).toBe('false');

    await act(async () => {
      screen.getByTestId('toast-btn').click();
    });
    await act(async () => {});
    expect(screen.getByTestId('toast-show').textContent).toBe('true');
    expect(screen.getByTestId('toast-message').textContent).toBe('Test message');
    expect(screen.getByTestId('toast-type').textContent).toBe('error');

    act(() => {
      vi.advanceTimersByTime(4000);
    });
    await act(async () => {});
    expect(screen.getByTestId('toast-show').textContent).toBe('false');
    vi.useRealTimers();
    await act(async () => {});
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
    await act(async () => {});

    await waitFor(() => {
      expect(capturedConfirm).toBeDefined();
    });
    await act(async () => {});

    let promise;
    await act(async () => {
      promise = capturedConfirm({ title: 'Test', message: 'Test' });
    });
    await act(async () => {});
    expect(promise).toBeInstanceOf(Promise);
  });
});

describe('AppContext – additional branches', () => {
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
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('setSelectedChallengeById(null) clears challenge and task', async () => {
    mockGet.mockResolvedValue({ ok: true, data: mockChallenges });

    function NullSelector() {
      const app = useApp();
      return (
        <div>
          <span data-testid="sel">{app.selectedChallenge?.name || 'none'}</span>
          <button data-testid="clear" onClick={() => app.setSelectedChallengeById(null)}>
            Clear
          </button>
        </div>
      );
    }

    render(
      <AppProvider>
        <NullSelector />
      </AppProvider>,
    );
    await act(async () => {});

    await waitFor(() => expect(screen.getByTestId('sel').textContent).toBe('Challenge 1'));

    act(() => screen.getByTestId('clear').click());

    await waitFor(() => expect(screen.getByTestId('sel').textContent).toBe('none'));
  });

  it('confirm with isPrompt=true resolves with the typed value on confirm', async () => {
    let captured;

    function PromptConsumer() {
      const app = useApp();
      return (
        <div>
          <button
            data-testid="open-prompt"
            onClick={() => {
              app
                .confirm({
                  title: 'Enter name',
                  message: 'Name:',
                  isPrompt: true,
                  placeholder: 'your name',
                })
                .then((val) => {
                  captured = val;
                });
            }}
          >
            Prompt
          </button>
        </div>
      );
    }

    mockGet.mockResolvedValue({ ok: true, data: [] });
    render(
      <AppProvider>
        <PromptConsumer />
      </AppProvider>,
    );
    await act(async () => {});

    act(() => screen.getByTestId('open-prompt').click());

    // The modal should now be open – type into the input
    const input = screen.getByPlaceholderText('your name');
    fireEvent.change(input, { target: { value: 'Alice' } });

    // Click the confirm button (first button in the modal footer that isn't Cancel)
    const confirmBtn = screen.getByText('Confirm');
    await act(async () => fireEvent.click(confirmBtn));

    expect(captured).toBe('Alice');
  });

  it('confirm with isPrompt=true resolves with null on cancel', async () => {
    let captured = 'initial';

    function CancelPrompt() {
      const app = useApp();
      return (
        <button
          data-testid="open"
          onClick={() =>
            app
              .confirm({ title: 'T', message: 'M', isPrompt: true, placeholder: 'x' })
              .then((v) => {
                captured = v;
              })
          }
        >
          Go
        </button>
      );
    }

    mockGet.mockResolvedValue({ ok: true, data: [] });
    render(
      <AppProvider>
        <CancelPrompt />
      </AppProvider>,
    );
    await act(async () => {});

    act(() => screen.getByTestId('open').click());

    const cancelBtn = screen.getByText('Cancel');
    await act(async () => fireEvent.click(cancelBtn));

    expect(captured).toBeNull();
  });

  it('confirm without isPrompt resolves false on cancel', async () => {
    let result = 'initial';

    function CancelConfirm() {
      const app = useApp();
      return (
        <button
          data-testid="open"
          onClick={() =>
            app.confirm({ title: 'Delete?', message: 'Sure?' }).then((v) => {
              result = v;
            })
          }
        >
          Go
        </button>
      );
    }

    mockGet.mockResolvedValue({ ok: true, data: [] });
    render(
      <AppProvider>
        <CancelConfirm />
      </AppProvider>,
    );
    await act(async () => {});

    act(() => screen.getByTestId('open').click());
    await act(async () => fireEvent.click(screen.getByText('Cancel')));

    expect(result).toBe(false);
  });

  it('confirm without isPrompt resolves true on confirm', async () => {
    let result = null;

    function ConfirmConfirm() {
      const app = useApp();
      return (
        <button
          data-testid="open"
          onClick={() =>
            app.confirm({ title: 'Delete?', message: 'Sure?' }).then((v) => {
              result = v;
            })
          }
        >
          Go
        </button>
      );
    }

    mockGet.mockResolvedValue({ ok: true, data: [] });
    render(
      <AppProvider>
        <ConfirmConfirm />
      </AppProvider>,
    );
    await act(async () => {});

    act(() => screen.getByTestId('open').click());
    await act(async () => fireEvent.click(screen.getByText('Confirm')));

    expect(result).toBe(true);
  });

  it('fetchChallenges clears state when API returns ok:false', async () => {
    mockGet.mockResolvedValue({ ok: false, data: null });
    renderWithProvider();
    await act(async () => {});
    await waitFor(() => expect(screen.getByTestId('challenges-count').textContent).toBe('0'));
  });

  it('fetchChallenges handles thrown errors without crashing', async () => {
    mockGet.mockRejectedValue(new Error('network error'));
    renderWithProvider();
    await act(async () => {});
    await waitFor(() => expect(screen.getByTestId('challenges-count').textContent).toBe('0'));
  });
});
