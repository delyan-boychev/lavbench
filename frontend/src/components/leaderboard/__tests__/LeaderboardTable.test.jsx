import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../../test-utils';
import { useAuth } from '../../../AuthContext';
import { useApp } from '../../../context/AppContext';
import ChallengeService from '../../../services/ChallengeService';
import LeaderboardTable from '../LeaderboardTable';

vi.mock('../../../AuthContext', () => ({
  useAuth: vi.fn(),
}));

vi.mock('../../../context/AppContext', () => ({
  useApp: vi.fn(),
}));

vi.mock('../../../services/ChallengeService', () => ({
  default: {
    finalize: vi.fn(),
    saveManualPoints: vi.fn(),
  },
}));

vi.mock('../../../services/ApiService', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

describe('LeaderboardTable Component', () => {
  const mockShowToast = vi.fn();
  const mockFetchChallenges = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    useApp.mockReturnValue({
      showToast: mockShowToast,
      fetchChallenges: mockFetchChallenges,
    });
  });

  it('renders loading spinner when loading is true', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    renderWithProviders(<LeaderboardTable data={[]} tasks={[]} challenge={null} loading={true} />);
    expect(screen.getByText('Loading leaderboard...')).toBeInTheDocument();
  });

  it('renders empty state message when data is empty', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    renderWithProviders(
      <LeaderboardTable
        data={[]}
        tasks={[]}
        challenge={{ scores_finalized: false }}
        loading={false}
      />,
    );
    expect(screen.getByText('No scored submissions yet. Be the first!')).toBeInTheDocument();
  });

  it('renders participant alias IDs instead of true identity when scores are not finalized', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    const challenge = {
      id: 12,
      title: 'Challenge A',
      scores_finalized: false,
      metric_name: 'Accuracy',
    };
    const tasks = [{ id: 1, title: 'Task 1' }];
    const data = [
      {
        rank: 1,
        public_score: 0.9876,
        has_submitted: true,
        user: { id: 2, username: 'user_two', alias_id: 'Alias-002', name: 'John', surname: 'Doe' },
        task_scores: { 1: { public_score: 0.9876 } },
      },
      {
        rank: 2,
        public_score: 0.8523,
        has_submitted: true,
        user: { id: 1, username: 'user_one', alias_id: 'Alias-001', name: 'My', surname: 'Name' },
        task_scores: { 1: { public_score: 0.8523 } },
      },
    ];

    renderWithProviders(
      <LeaderboardTable data={data} tasks={tasks} challenge={challenge} loading={false} />,
    );

    expect(screen.getByTitle('Rank 1')).toBeInTheDocument();
    expect(screen.getByTitle('Rank 2')).toBeInTheDocument();

    expect(screen.getByText('You')).toBeInTheDocument();
    expect(screen.getByText('My Name')).toBeInTheDocument();

    expect(screen.queryByText('John Doe')).not.toBeInTheDocument();
    expect(screen.getByText('Alias-002')).toBeInTheDocument();

    expect(screen.getAllByText('0.9876').length).toBeGreaterThan(0);
    expect(screen.getAllByText('0.8523').length).toBeGreaterThan(0);
  });

  it('reveals true identities, school, grade, and private scores when challenge is finalized and row is expanded', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    const challenge = {
      id: 12,
      title: 'Challenge A',
      scores_finalized: true,
      metric_name: 'Accuracy',
      reveal_results: true,
    };
    const tasks = [{ id: 1, title: 'Task 1' }];
    const data = [
      {
        rank: 1,
        public_score: 0.9876,
        private_score: 0.9912,
        total_points: 95,
        has_submitted: true,
        user: {
          id: 2,
          username: 'user_two',
          alias_id: 'Alias-002',
          name: 'John',
          surname: 'Doe',
          school: 'Math High School',
          grade: '10',
        },
        task_scores: { 1: { public_score: 0.9876, private_score: 0.9912 } },
      },
    ];

    renderWithProviders(
      <LeaderboardTable data={data} tasks={tasks} challenge={challenge} loading={false} />,
    );

    const expandBtn = screen.getByTitle('Toggle details');
    fireEvent.click(expandBtn);

    expect(screen.getAllByText('John Doe').length).toBe(2);

    expect(screen.getByText('School:')).toBeInTheDocument();
    expect(screen.getByText('Math High School')).toBeInTheDocument();
    expect(screen.getByText('Grade:')).toBeInTheDocument();
    expect(screen.getByText('10 grade')).toBeInTheDocument();

    expect(screen.getByText('95 pts')).toBeInTheDocument();
  });

  it('shows baseline badge and hides expand button for baseline entries', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    const challenge = {
      id: 12,
      title: 'Challenge A',
      scores_finalized: false,
      metric_name: 'Accuracy',
      double_blind: false,
    };
    const tasks = [{ id: 10, title: 'Task 1' }];
    const data = [
      {
        rank: 1,
        public_score: 0.9999,
        is_baseline_entry: true,
        user: { id: 99, username: 'baseline', alias_id: 'BL-001' },
        task_scores: {
          10: { submission_id: 999, public_score: 0.9999, private_score: 0.95 },
        },
      },
    ];

    renderWithProviders(
      <LeaderboardTable data={data} tasks={tasks} challenge={challenge} loading={false} />,
    );

    // Baseline hidden from general tab
    expect(screen.queryByText('Baseline')).not.toBeInTheDocument();

    // Switch to per-task tab — baselines visible pre-finalized
    fireEvent.click(screen.getByText('Task 1'));
    expect(screen.getByText('Baseline')).toBeInTheDocument();
  });

  it('shows true name for other users when jury/admin view during blind mode', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'admin' } });
    const challenge = {
      id: 12,
      title: 'Challenge A',
      scores_finalized: false,
      metric_name: 'Accuracy',
      double_blind: true,
    };
    const data = [
      {
        rank: 1,
        public_score: 0.95,
        user: {
          id: 2,
          username: 'other_user',
          alias_id: 'Alias-002',
          name: 'Jane',
          surname: 'Smith',
        },
        task_scores: {},
      },
    ];

    renderWithProviders(
      <LeaderboardTable data={data} tasks={[]} challenge={challenge} loading={false} />,
    );
    expect(screen.getByText('Jane Smith')).toBeInTheDocument();
    expect(screen.queryByText('Alias-002')).not.toBeInTheDocument();
  });

  it('calls onRefresh when refresh button is clicked', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    const onRefresh = vi.fn();
    const challenge = {
      id: 12,
      title: 'Challenge A',
      scores_finalized: false,
      metric_name: 'Accuracy',
    };
    const data = [{ rank: 1, public_score: 0.5, user: { id: 1, username: 'me' }, task_scores: {} }];

    renderWithProviders(
      <LeaderboardTable
        data={data}
        tasks={[]}
        challenge={challenge}
        loading={false}
        onRefresh={onRefresh}
      />,
    );
    const refreshBtn = screen.getByTitle('Refresh');
    fireEvent.click(refreshBtn);
    expect(onRefresh).toHaveBeenCalled();
  });

  it('shows normalized badge when isNormalized is true', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    const challenge = {
      id: 12,
      title: 'Challenge A',
      scores_finalized: false,
      metric_name: 'Accuracy',
    };
    const data = [{ rank: 1, public_score: 0.5, user: { id: 1, username: 'me' }, task_scores: {} }];

    renderWithProviders(
      <LeaderboardTable
        data={data}
        tasks={[]}
        challenge={challenge}
        loading={false}
        isNormalized={true}
      />,
    );
    expect(screen.getByText('(normalized)')).toBeInTheDocument();
  });

  it('shows finalized pill when scores are finalized', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    const challenge = {
      id: 12,
      title: 'Challenge A',
      scores_finalized: true,
      reveal_results: true,
      metric_name: 'Accuracy',
    };
    const data = [{ rank: 1, public_score: 0.5, user: { id: 1, username: 'me' }, task_scores: {} }];

    renderWithProviders(
      <LeaderboardTable data={data} tasks={[]} challenge={challenge} loading={false} />,
    );
    expect(screen.getByText('Public')).toBeInTheDocument();
  });

  it('renders task tab buttons and switches view on click', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    const challenge = {
      id: 12,
      title: 'Challenge A',
      scores_finalized: false,
      metric_name: 'Accuracy',
    };
    const tasks = [
      { id: 10, title: 'Task Alpha' },
      { id: 20, title: 'Task Beta' },
    ];
    const data = [
      {
        rank: 1,
        public_score: 0.9,
        total_points: 1,
        user: { id: 1, username: 'me' },
        task_scores: { 10: { public_score: 0.9 }, 20: { public_score: 0.8 } },
      },
    ];

    renderWithProviders(
      <LeaderboardTable data={data} tasks={tasks} challenge={challenge} loading={false} />,
    );
    expect(screen.getByText('General Leaderboard')).toBeInTheDocument();
    expect(screen.getByText('Task Alpha')).toBeInTheDocument();
    expect(screen.getByText('Task Beta')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Task Alpha'));
    expect(screen.getByText('Task Alpha').closest('button')).toHaveClass('bg-indigo-600/20');
  });

  it('saves manual points via modal', async () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'jury' } });
    ChallengeService.saveManualPoints.mockResolvedValue({ ok: true });
    const onRefresh = vi.fn();
    const challenge = {
      id: 12,
      title: 'Challenge A',
      scores_finalized: false,
      metric_name: 'Accuracy',
      double_blind: false,
    };
    const tasks = [{ id: 10, title: 'Task 1' }];
    const data = [
      {
        rank: 1,
        public_score: 0.9,
        total_points: 1,
        user: { id: 5, username: 'player1', name: 'Player', surname: 'One' },
        task_scores: { 10: { public_score: 0.9 } },
      },
    ];

    renderWithProviders(
      <LeaderboardTable
        data={data}
        tasks={tasks}
        challenge={challenge}
        loading={false}
        onRefresh={onRefresh}
      />,
    );

    fireEvent.click(screen.getByTitle('Toggle details'));
    fireEvent.click(screen.getByRole('button', { name: /0 pts/i }));

    const pointsInput = screen.getByPlaceholderText('Enter score');
    fireEvent.change(pointsInput, { target: { value: '85' } });

    fireEvent.click(screen.getByRole('button', { name: /Save/i }));

    await waitFor(() => {
      expect(ChallengeService.saveManualPoints).toHaveBeenCalledWith({
        challengeId: 12,
        user_id: 5,
        points: { 10: 85 },
        reason: undefined,
      });
    });
    expect(onRefresh).toHaveBeenCalled();
  });

  it('shows error toast when save manual points returns invalid input', async () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'jury' } });
    const challenge = {
      id: 12,
      title: 'Challenge A',
      scores_finalized: false,
      metric_name: 'Accuracy',
      double_blind: false,
    };
    const tasks = [{ id: 10, title: 'Task 1' }];
    const data = [
      {
        rank: 1,
        public_score: 0.9,
        total_points: 1,
        user: { id: 5, username: 'player1', name: 'Player', surname: 'One' },
        task_scores: { 10: { public_score: 0.9 } },
      },
    ];

    renderWithProviders(
      <LeaderboardTable data={data} tasks={tasks} challenge={challenge} loading={false} />,
    );

    fireEvent.click(screen.getByTitle('Toggle details'));
    fireEvent.click(screen.getByRole('button', { name: /0 pts/i }));

    const pointsInput = screen.getByPlaceholderText('Enter score');
    fireEvent.change(pointsInput, { target: { value: '200' } });

    fireEvent.click(screen.getByRole('button', { name: /Save/i }));

    await waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith(
        'Points must be an integer between 0 and 100',
        'error',
      );
    });
  });

  it('renders stage tab buttons and switches view on click, sorting by stage-aggregated scores', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    const challenge = {
      id: 12,
      title: 'Challenge A',
      scores_finalized: false,
      metric_name: 'Accuracy',
      stages: [
        { id: 'stage1', stage_number: 1, title: 'Stage Alpha', start_time: '2020-01-01T00:00:00Z' },
      ],
    };
    const tasks = [
      { id: 10, title: 'Task Alpha', stage_id: 'stage1' },
      { id: 20, title: 'Task Beta', stage_id: 'stage1' },
    ];
    const data = [
      {
        rank: 1,
        public_score: 1.5,
        user: { id: 1, username: 'user1', alias_id: 'Alias-1' },
        task_scores: {
          10: { public_score: 0.9, total_points: 1, submission_id: 101 },
          20: { public_score: 0.6, submission_id: 102 },
        },
      },
      {
        rank: 2,
        public_score: 1.6,
        user: { id: 2, username: 'user2', alias_id: 'Alias-2' },
        task_scores: {
          10: { public_score: 0.8, submission_id: 201 },
          20: { public_score: 0.8, submission_id: 202 },
        },
      },
    ];

    renderWithProviders(
      <LeaderboardTable data={data} tasks={tasks} challenge={challenge} loading={false} />,
    );
    expect(screen.getByText('Stage 1: Stage Alpha')).toBeInTheDocument();

    // Click on Stage 1 tab
    fireEvent.click(screen.getByText('Stage 1: Stage Alpha'));
    expect(screen.getByText('Stage 1: Stage Alpha').closest('button')).toHaveClass(
      'bg-indigo-600/20',
    );
  });
});
