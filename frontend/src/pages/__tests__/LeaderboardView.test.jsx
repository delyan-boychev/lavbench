import React from 'react';
import { render, screen, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('react-router', () => ({
  useParams: vi.fn(),
}));

vi.mock('../../context/AppContext', () => ({
  useApp: vi.fn(),
}));

vi.mock('../../hooks/useLeaderboardQuery', () => ({
  useLeaderboardQuery: vi.fn(),
}));

vi.mock('../../hooks/useSSEInvalidation', () => ({
  default: vi.fn(),
  LEADERBOARD_REFETCH_SPREAD_MS: 10_000,
}));

vi.mock('../../components/leaderboard/LeaderboardTable', () => ({
  default: (props) => (
    <div data-testid="leaderboard-table">
      <span data-testid="loading">{String(props.loading)}</span>
      <span data-testid="metric-name">{props.metricName}</span>
      <span data-testid="is-normalized">{String(props.isNormalized)}</span>
      <span data-testid="rows-count">{props.data.length}</span>
      <span data-testid="tasks-count">{props.tasks.length}</span>
      <span data-testid="challenge-id">{props.challenge?.id}</span>
    </div>
  ),
}));

vi.mock('../../components/ui/EmptyState', () => ({
  default: ({ message, minHeight }) => (
    <div data-testid="empty-state" style={{ minHeight }}>
      {message}
    </div>
  ),
}));

import { useParams } from 'react-router';
import { useApp } from '../../context/AppContext';
import { useLeaderboardQuery } from '../../hooks/useLeaderboardQuery';
import useSSEInvalidation from '../../hooks/useSSEInvalidation';
import LeaderboardView from '../LeaderboardView';

const mockSetSelectedChallengeById = vi.fn();
const mockRefetch = vi.fn();
const defaultUseApp = {
  selectedChallenge: { id: 42, title: 'Test Challenge' },
  setSelectedChallengeById: mockSetSelectedChallengeById,
};

const mockLeaderboardData = [
  { rank: 1, user: { id: 1, username: 'alice' }, public_score: 0.95 },
  { rank: 2, user: { id: 2, username: 'bob' }, public_score: 0.88 },
];

const mockTasks = [
  { id: 1, title: 'Task 1' },
  { id: 2, title: 'Task 2' },
];

const defaultQueryData = {
  leaderboard: mockLeaderboardData,
  tasks: mockTasks,
  metric_name: 'Accuracy',
  is_normalized: false,
};

describe('LeaderboardView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useParams.mockReturnValue({ challengeId: '42' });
    useApp.mockReturnValue(defaultUseApp);
    useLeaderboardQuery.mockReturnValue({
      data: defaultQueryData,
      isLoading: false,
      refetch: mockRefetch,
    });
    useSSEInvalidation.mockReturnValue({ connected: true, refetchInterval: false });
  });

  it('sets selected challenge by id from params on mount', async () => {
    render(<LeaderboardView />);
    await act(async () => {});
    expect(mockSetSelectedChallengeById).toHaveBeenCalledWith('42');
  });

  it('does not call setSelectedChallengeById when challengeId is absent', async () => {
    useParams.mockReturnValue({});
    render(<LeaderboardView />);
    await act(async () => {});
    expect(mockSetSelectedChallengeById).not.toHaveBeenCalled();
  });

  it('shows EmptyState when no challenge is selected', async () => {
    useApp.mockReturnValue({
      selectedChallenge: null,
      setSelectedChallengeById: mockSetSelectedChallengeById,
    });
    render(<LeaderboardView />);
    await act(async () => {});
    expect(screen.getByTestId('empty-state')).toBeTruthy();
  });

  it('renders LeaderboardTable when a challenge is selected', async () => {
    render(<LeaderboardView />);
    await act(async () => {});
    await waitFor(() => {
      expect(screen.getByTestId('leaderboard-table')).toBeTruthy();
    });
  });

  it('passes leaderboard data to LeaderboardTable', async () => {
    render(<LeaderboardView />);
    await act(async () => {});
    await waitFor(() => {
      expect(screen.getByTestId('rows-count').textContent).toBe('2');
    });
  });

  it('passes tasks to LeaderboardTable', async () => {
    render(<LeaderboardView />);
    await act(async () => {});
    await waitFor(() => {
      expect(screen.getByTestId('tasks-count').textContent).toBe('2');
    });
  });

  it('passes metric name to LeaderboardTable', async () => {
    render(<LeaderboardView />);
    await act(async () => {});
    await waitFor(() => {
      expect(screen.getByTestId('metric-name').textContent).toBe('Accuracy');
    });
  });

  it('passes isNormalized to LeaderboardTable', async () => {
    render(<LeaderboardView />);
    await act(async () => {});
    await waitFor(() => {
      expect(screen.getByTestId('is-normalized').textContent).toBe('false');
    });
  });

  it('passes challenge to LeaderboardTable', async () => {
    render(<LeaderboardView />);
    await act(async () => {});
    await waitFor(() => {
      expect(screen.getByTestId('challenge-id').textContent).toBe('42');
    });
  });

  it('shows loading state before leaderboard resolves', async () => {
    useLeaderboardQuery.mockReturnValue({
      data: undefined,
      isLoading: true,
      refetch: mockRefetch,
    });
    render(<LeaderboardView />);
    expect(screen.getByTestId('loading').textContent).toBe('true');
    await act(async () => {});
  });

  it('clears loading after leaderboard loads', async () => {
    render(<LeaderboardView />);
    await act(async () => {});
    await waitFor(() => {
      expect(screen.getByTestId('loading').textContent).toBe('false');
    });
  });

  it('handles leaderboard API failure gracefully', async () => {
    useLeaderboardQuery.mockReturnValue({
      data: undefined,
      isLoading: false,
      refetch: mockRefetch,
    });
    render(<LeaderboardView />);
    await act(async () => {});
    await waitFor(() => {
      expect(screen.getByTestId('leaderboard-table')).toBeTruthy();
    });
  });

  it('invalidates the challenge leaderboard from its signal-only stream, spread over 10 s', async () => {
    render(<LeaderboardView />);
    await act(async () => {});
    expect(useSSEInvalidation).toHaveBeenLastCalledWith(
      '/api/challenges/42/leaderboard/live',
      ['leaderboard', '42'],
      { spreadMs: 10_000 },
    );
  });

  it('opens no stream without an active challenge', async () => {
    useParams.mockReturnValue({});
    useApp.mockReturnValue({ ...defaultUseApp, selectedChallenge: null });
    render(<LeaderboardView />);
    await act(async () => {});
    expect(useSSEInvalidation).toHaveBeenLastCalledWith('', ['leaderboard', undefined], {
      spreadMs: 10_000,
    });
  });

  it('polls the leaderboard while the stream is down', async () => {
    useSSEInvalidation.mockReturnValue({ connected: false, refetchInterval: 15000 });
    render(<LeaderboardView />);
    await act(async () => {});
    expect(useLeaderboardQuery).toHaveBeenLastCalledWith('42', { refetchInterval: 15000 });
  });

  it('does not poll while the stream is connected', async () => {
    render(<LeaderboardView />);
    await act(async () => {});
    expect(useLeaderboardQuery).toHaveBeenLastCalledWith('42', { refetchInterval: false });
  });
});
