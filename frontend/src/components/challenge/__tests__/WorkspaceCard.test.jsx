import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { createTestQueryClient } from '../../../test-utils';
import WorkspaceCard from '../WorkspaceCard';
import EnvironmentService from '../../../services/EnvironmentService';
import { openWorkspaceWindow, postLaunchForm } from '../../../utils/workspaceLaunch';
import { environmentKeys } from '../../../hooks/useEnvironmentQuery';
import useSSEInvalidation from '../../../hooks/useSSEInvalidation';
import { EnvironmentLiveProvider } from '../../../context/EnvironmentLiveContext';

vi.mock('../../../services/EnvironmentService', () => ({
  default: {
    getForTask: vi.fn(),
    launch: vi.fn(),
    liveUrl: (id) => `/api/challenges/${id}/environment/live`,
  },
}));

vi.mock('../../../utils/workspaceLaunch', () => ({
  openWorkspaceWindow: vi.fn(),
  postLaunchForm: vi.fn(),
}));

vi.mock('../../../hooks/useSSEInvalidation', async (importOriginal) => ({
  ...(await importOriginal()),
  default: vi.fn(() => ({ connected: true, refetchInterval: false })),
}));

const mockShowToast = vi.fn();
vi.mock('../../../context/NotificationsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useNotifications: () => ({ showToast: mockShowToast, confirm: vi.fn() }),
}));

const TASK = { id: 't1', challenge_id: 'c1' };
const LAUNCH = {
  launch_url: 'https://hub.example/hub/launch',
  launch_token: 'token-1',
  expires_at: '2027-05-01T10:01:00Z',
  open_path: 'image-classification/solution.ipynb',
};

const environment = (status, overrides = {}) => ({
  status,
  folder_name: 'image-classification',
  open_path: 'image-classification/solution.ipynb',
  starts_at: '2027-05-01T09:00:00+03:00',
  ends_at: '2099-05-01T17:03:00+03:00',
  ...overrides,
});

function renderCard() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <WorkspaceCard task={TASK} />
    </QueryClientProvider>,
  );
}

const failure = (status, code, retryAfter) =>
  Promise.resolve({
    ok: false,
    status,
    data: { code, error: code },
    res: { headers: new Headers(retryAfter ? { 'Retry-After': String(retryAfter) } : {}) },
  });

describe('WorkspaceCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each([
    [404, 'ERR_NANOCOLAB_DISABLED'],
    [409, 'ERR_ENVIRONMENT_NOT_ENABLED'],
    [403, 'ERR_NOT_AVAILABLE'],
  ])('shows nothing on %s %s', async (status, code) => {
    EnvironmentService.getForTask.mockReturnValue(failure(status, code));
    const { container } = renderCard();
    await waitFor(() => expect(EnvironmentService.getForTask).toHaveBeenCalledWith('t1'));
    expect(container).toBeEmptyDOMElement();
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  it('offers Open workspace and names the folder once ready', async () => {
    EnvironmentService.getForTask.mockResolvedValue({ ok: true, data: environment('ready') });
    renderCard();
    const button = await screen.findByRole('button', { name: 'Open workspace' });
    expect(button).toBeEnabled();
    expect(screen.getByText('Ready')).toBeInTheDocument();
    expect(screen.getByText('image-classification/')).toBeInTheDocument();
    expect(screen.getByText(/JupyterLab opens in a new tab/)).toBeInTheDocument();
  });

  it.each([
    ['not_open', 'Not open yet', 'The workspace is not open yet. This page updates by itself.'],
    ['preparing', 'Preparing', 'Your workspace is being prepared. This page updates by itself.'],
  ])('keeps the button disabled while %s', async (status, badge, hint) => {
    EnvironmentService.getForTask.mockResolvedValue({ ok: true, data: environment(status) });
    renderCard();
    expect(await screen.findByText(badge)).toBeInTheDocument();
    expect(screen.getByText(hint)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open workspace' })).toBeDisabled();
    expect(screen.queryByText('image-classification/')).not.toBeInTheDocument();
  });

  it('still lets the student try when the status is unknown', async () => {
    EnvironmentService.getForTask.mockResolvedValue({ ok: true, data: environment('unknown') });
    renderCard();
    expect(await screen.findByRole('button', { name: 'Open workspace' })).toBeEnabled();
    expect(screen.getByText('Unknown')).toBeInTheDocument();
  });

  it('drops the button once closed', async () => {
    EnvironmentService.getForTask.mockResolvedValue({ ok: true, data: environment('closed') });
    renderCard();
    expect(await screen.findByText('Closed')).toBeInTheDocument();
    expect(screen.getByText('The workspace for this task has closed.')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('opens the tab first, then hands the token to the Hub', async () => {
    const win = { closed: false, close: vi.fn() };
    openWorkspaceWindow.mockReturnValue({ win, fresh: true });
    EnvironmentService.getForTask.mockResolvedValue({ ok: true, data: environment('ready') });
    EnvironmentService.launch.mockResolvedValue({ ok: true, status: 200, data: LAUNCH });
    renderCard();
    fireEvent.click(await screen.findByRole('button', { name: 'Open workspace' }));
    expect(openWorkspaceWindow).toHaveBeenCalledWith('Opening your workspace...');
    await waitFor(() => expect(postLaunchForm).toHaveBeenCalledWith(LAUNCH));
    expect(EnvironmentService.launch).toHaveBeenCalledWith('t1');
    expect(win.close).not.toHaveBeenCalled();
  });

  it('closes its blank tab, explains the error and waits out Retry-After', async () => {
    const win = { closed: false, close: vi.fn() };
    openWorkspaceWindow.mockReturnValue({ win, fresh: true });
    EnvironmentService.getForTask.mockResolvedValue({ ok: true, data: environment('ready') });
    EnvironmentService.launch.mockReturnValue(failure(503, 'ERR_ENVIRONMENT_PREPARING', 20));
    renderCard();
    const button = await screen.findByRole('button', { name: 'Open workspace' });
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    try {
      fireEvent.click(button);
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      await vi.waitFor(() => expect(win.close).toHaveBeenCalled());
      expect(postLaunchForm).not.toHaveBeenCalled();
      expect(mockShowToast).toHaveBeenCalledWith(
        'The workspace is being prepared. Please try again shortly.',
        'rose',
      );
      expect(screen.getByText('Try again in a few seconds.')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Open workspace' })).toBeDisabled();
      await act(async () => {
        vi.advanceTimersByTime(20_000);
      });
      expect(screen.queryByText('Try again in a few seconds.')).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('leaves a reused workspace tab open when the launch fails', async () => {
    const win = { closed: false, close: vi.fn() };
    openWorkspaceWindow.mockReturnValue({ win, fresh: false });
    EnvironmentService.getForTask.mockResolvedValue({ ok: true, data: environment('ready') });
    EnvironmentService.launch.mockReturnValue(failure(409, 'ERR_ENVIRONMENT_FULL'));
    renderCard();
    fireEvent.click(await screen.findByRole('button', { name: 'Open workspace' }));
    await waitFor(() =>
      expect(mockShowToast).toHaveBeenCalledWith(
        'The environment has no free places left.',
        'rose',
      ),
    );
    expect(win.close).not.toHaveBeenCalled();
  });

  it('disappears when a refetch says the environment was turned off', async () => {
    EnvironmentService.getForTask.mockResolvedValueOnce({ ok: true, data: environment('ready') });
    const client = createTestQueryClient();
    render(
      <QueryClientProvider client={client}>
        <WorkspaceCard task={TASK} />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole('button', { name: 'Open workspace' })).toBeInTheDocument();
    EnvironmentService.getForTask.mockReturnValue(failure(409, 'ERR_ENVIRONMENT_NOT_ENABLED'));
    await act(() => client.refetchQueries({ queryKey: environmentKeys.task('c1', 't1') }));
    await waitFor(() => expect(screen.queryByTestId('workspace-card')).not.toBeInTheDocument());
  });

  it('stays on LavBench and asks to allow pop-ups when the tab is blocked', async () => {
    openWorkspaceWindow.mockReturnValue({ win: null, fresh: false });
    EnvironmentService.getForTask.mockResolvedValue({ ok: true, data: environment('ready') });
    renderCard();
    const button = await screen.findByRole('button', { name: 'Open workspace' });
    fireEvent.click(button);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Your browser blocked the new tab. Allow pop-ups for this site, then click Open workspace again.',
    );
    expect(EnvironmentService.launch).not.toHaveBeenCalled();
    expect(postLaunchForm).not.toHaveBeenCalled();
    expect(button).toBeEnabled();

    const win = { closed: false, close: vi.fn() };
    openWorkspaceWindow.mockReturnValue({ win, fresh: true });
    EnvironmentService.launch.mockResolvedValue({ ok: true, status: 200, data: LAUNCH });
    fireEvent.click(button);
    await waitFor(() => expect(postLaunchForm).toHaveBeenCalledWith(LAUNCH));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('keeps re-checking after the end until the server reports closed', async () => {
    vi.useFakeTimers();
    try {
      const past = new Date(Date.now() - 1000).toISOString();
      EnvironmentService.getForTask.mockResolvedValue({
        ok: true,
        data: environment('ready', { ends_at: past }),
      });
      renderCard();
      await vi.advanceTimersByTimeAsync(0);
      expect(EnvironmentService.getForTask).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(1000);
      expect(EnvironmentService.getForTask).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(5000 * 2);
      expect(EnvironmentService.getForTask).toHaveBeenCalledTimes(4);

      EnvironmentService.getForTask.mockResolvedValue({
        ok: true,
        data: environment('closed', { ends_at: past }),
      });
      await vi.advanceTimersByTimeAsync(5000);
      await vi.advanceTimersByTimeAsync(100);
      expect(EnvironmentService.getForTask).toHaveBeenCalledTimes(5);
      expect(screen.getByText('Closed')).toBeInTheDocument();
      await vi.advanceTimersByTimeAsync(60_000);
      expect(EnvironmentService.getForTask).toHaveBeenCalledTimes(5);
    } finally {
      vi.useRealTimers();
    }
  });

  it('stops re-checking after about a minute', async () => {
    vi.useFakeTimers();
    try {
      EnvironmentService.getForTask.mockResolvedValue({
        ok: true,
        data: environment('ready', { ends_at: new Date(Date.now() - 1000).toISOString() }),
      });
      renderCard();
      await vi.advanceTimersByTimeAsync(5 * 60_000);
      expect(EnvironmentService.getForTask).toHaveBeenCalledTimes(1 + 12);
    } finally {
      vi.useRealTimers();
    }
  });

  it.each([
    [409, 'ERR_ENVIRONMENT_NOT_ENABLED', true],
    [404, 'ERR_NANOCOLAB_DISABLED', false],
  ])('listens to the shared stream while hidden by %s: %s', async (status, code, listens) => {
    EnvironmentService.getForTask.mockReturnValue(failure(status, code));
    const { container } = render(
      <QueryClientProvider client={createTestQueryClient()}>
        <EnvironmentLiveProvider>
          <WorkspaceCard task={TASK} />
        </EnvironmentLiveProvider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(EnvironmentService.getForTask).toHaveBeenCalled());
    const listening = () =>
      useSSEInvalidation.mock.calls.some(([url]) => url === '/api/challenges/c1/environment/live');
    await waitFor(() => expect(listening()).toBe(listens));
    expect(container).toBeEmptyDOMElement();
  });
});
