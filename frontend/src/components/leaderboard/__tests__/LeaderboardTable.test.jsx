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

  it('reveals true identities and points to a competitor once the challenge is finalized', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    const challenge = {
      id: 12,
      title: 'Challenge A',
      scores_finalized: true,
      metric_name: 'Accuracy',
      reveal_results: true,
    };
    const tasks = [{ id: 1, title: 'Task 1' }];
    // The whitelisted user record a competitor receives: no school, grade or city
    const data = [
      {
        rank: 1,
        public_score: 0.9876,
        private_score: 0.9912,
        total_points: 95,
        has_submitted: true,
        user: {
          id: 2,
          alias_id: 'Alias-002',
          name: 'John',
          surname: 'Doe',
          is_anonymous: false,
          manual_points: {},
        },
        task_scores: { 1: { public_score: 0.9876, private_score: 0.9912 } },
      },
    ];

    renderWithProviders(
      <LeaderboardTable data={data} tasks={tasks} challenge={challenge} loading={false} />,
    );

    fireEvent.click(screen.getByTitle('Toggle details'));

    expect(screen.getAllByText('John Doe').length).toBe(2);
    expect(screen.queryByText('School:')).not.toBeInTheDocument();
    expect(screen.queryByText('Grade:')).not.toBeInTheDocument();
    expect(screen.queryByText('City:')).not.toBeInTheDocument();
    expect(screen.getByText('95 pts')).toBeInTheDocument();
  });

  it('shows school, grade and city to staff when the API sends them', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'admin' } });
    const challenge = { id: 12, scores_finalized: false, double_blind: false };
    const data = [
      {
        rank: 1,
        public_score: 0.9,
        has_submitted: true,
        user: {
          id: 2,
          username: 'user_two',
          alias_id: 'Alias-002',
          name: 'John',
          surname: 'Doe',
          school: 'Math High School',
          grade: '10',
          city: 'Sofia',
        },
        task_scores: {},
      },
    ];

    renderWithProviders(
      <LeaderboardTable data={data} tasks={[]} challenge={challenge} loading={false} />,
    );
    fireEvent.click(screen.getByTitle('Toggle details'));

    expect(screen.getByText('Math High School')).toBeInTheDocument();
    expect(screen.getByText('10 grade')).toBeInTheDocument();
    expect(screen.getByText('Sofia')).toBeInTheDocument();
  });

  it('shows the alias when the API sends no name for a listed user', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    const challenge = { id: 12, scores_finalized: false, double_blind: false };
    const data = [
      {
        rank: 1,
        public_score: 0.9,
        has_submitted: true,
        user: { id: 2, alias_id: 'Alias-002', is_anonymous: true, manual_points: {} },
        task_scores: {},
      },
    ];

    renderWithProviders(
      <LeaderboardTable data={data} tasks={[]} challenge={challenge} loading={false} />,
    );

    expect(screen.getByText('Alias-002')).toBeInTheDocument();
  });

  it('renders the Baseline row from its label, without user data or a rank', () => {
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
        rank: null,
        public_score: 0.9999,
        has_submitted: true,
        is_baseline_entry: true,
        label: 'Baseline',
        user: null,
        task_ranks: { 10: null },
        task_rows_before: { 10: 0 },
        task_scores: {
          10: { submission_id: 999, public_score: 0.9999, private_score: null },
        },
      },
    ];

    renderWithProviders(
      <LeaderboardTable data={data} tasks={tasks} challenge={challenge} loading={false} />,
    );

    // Baseline hidden from general tab
    expect(screen.queryByText('Baseline')).not.toBeInTheDocument();

    // A task tab shows it, with no expand button and no rank badge
    fireEvent.click(screen.getByText('Task 1'));
    expect(screen.getByText('Baseline')).toBeInTheDocument();
    expect(screen.queryByTitle('Toggle details')).not.toBeInTheDocument();
    expect(screen.queryByTitle(/^Rank /)).not.toBeInTheDocument();
    expect(screen.getByText('0.9999')).toBeInTheDocument();
  });

  it('shows the ranks the API sends on the general, task and stage tabs', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    const challenge = {
      id: 12,
      scores_finalized: false,
      double_blind: true,
      stages: [{ id: 's1', stage_number: 1, title: 'Round', start_time: '2020-01-01T00:00:00Z' }],
    };
    const tasks = [{ id: 10, title: 'Task 1', stage_id: 's1' }];
    const competitor = (id, alias, rank, taskRank, stageRank, score) => ({
      rank,
      public_score: score,
      has_submitted: score != null,
      user: { id, alias_id: alias, is_anonymous: false, manual_points: {} },
      task_ranks: { 10: taskRank },
      stage_ranks: { s1: stageRank },
      task_scores: { 10: { public_score: score, submission_id: score != null ? id : null } },
    });
    // The baseline outscores both competitors but holds no rank
    const data = [
      {
        rank: null,
        public_score: 0.95,
        has_submitted: true,
        is_baseline_entry: true,
        label: 'Baseline',
        user: null,
        task_ranks: { 10: null },
        stage_ranks: { s1: null },
        task_rows_before: { 10: 0 },
        task_scores: { 10: { public_score: 0.95, submission_id: 900 } },
      },
      competitor(2, 'Alias-2', 1, 1, 1, 0.9),
      competitor(3, 'Alias-3', 2, 2, 2, 0.8),
      competitor(4, 'Alias-4', null, null, null, null),
    ];

    renderWithProviders(
      <LeaderboardTable data={data} tasks={tasks} challenge={challenge} loading={false} />,
    );

    const rankTitles = () => screen.queryAllByTitle(/^Rank /).map((el) => el.getAttribute('title'));
    const rowNames = () =>
      screen
        .getAllByRole('row')
        .slice(1)
        .map((row) => row.querySelectorAll('td')[2].textContent);

    expect(rankTitles()).toEqual(['Rank 1', 'Rank 2']);
    expect(rowNames()).toEqual(['Alias-2', 'Alias-3', 'Alias-4']);

    fireEvent.click(screen.getByText('Task 1'));
    expect(rankTitles()).toEqual(['Rank 1', 'Rank 2']);
    expect(rowNames()).toEqual(['Baseline', 'Alias-2', 'Alias-3', 'Alias-4']);

    fireEvent.click(screen.getByText('Stage 1: Round'));
    expect(rankTitles()).toEqual(['Rank 1', 'Rank 2']);
    expect(rowNames()).toEqual(['Alias-2', 'Alias-3', 'Alias-4']);
  });

  describe('Baseline row on a task tab', () => {
    const challenge = { id: 12, scores_finalized: false, double_blind: true };
    const tasks = [{ id: 10, title: 'Task 1' }];
    const competitor = (id, rank, score) => ({
      rank,
      public_score: score,
      has_submitted: true,
      user: { id, alias_id: `Alias-${id}`, is_anonymous: false, manual_points: {} },
      task_ranks: { 10: rank },
      task_scores: { 10: { public_score: score, submission_id: id } },
    });
    // The baseline's score would put it first; only the API's placement decides
    const baseline = (extra) => ({
      rank: null,
      public_score: 0.95,
      has_submitted: true,
      is_baseline_entry: true,
      label: 'Baseline',
      user: null,
      task_ranks: { 10: null },
      task_scores: { 10: { public_score: 0.95, submission_id: 900 } },
      ...extra,
    });
    const rowNames = () =>
      screen
        .getAllByRole('row')
        .slice(1)
        .map((row) => row.querySelectorAll('td')[2].textContent);

    beforeEach(() => {
      useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    });

    it('is inserted after the number of rows the API places before it', () => {
      const data = [
        competitor(2, 1, 0.9),
        competitor(3, 2, 0.8),
        baseline({ task_rows_before: { 10: 1 } }),
      ];

      renderWithProviders(
        <LeaderboardTable data={data} tasks={tasks} challenge={challenge} loading={false} />,
      );
      fireEvent.click(screen.getByText('Task 1'));

      expect(rowNames()).toEqual(['Alias-2', 'Baseline', 'Alias-3']);
    });

    it('is not shown when the API gives it no place on the tab', () => {
      const data = [competitor(2, 1, 0.9), baseline({ task_rows_before: {} })];

      renderWithProviders(
        <LeaderboardTable data={data} tasks={tasks} challenge={challenge} loading={false} />,
      );
      fireEvent.click(screen.getByText('Task 1'));

      expect(rowNames()).toEqual(['Alias-2']);
      expect(screen.queryByText('Baseline')).not.toBeInTheDocument();
    });

    it('is not shown when the API sends no placement at all', () => {
      const data = [competitor(2, 1, 0.9), baseline({})];

      renderWithProviders(
        <LeaderboardTable data={data} tasks={tasks} challenge={challenge} loading={false} />,
      );
      fireEvent.click(screen.getByText('Task 1'));

      expect(screen.queryByText('Baseline')).not.toBeInTheDocument();
    });
  });

  it('does not renumber ranks the API sends with gaps or ties', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    const challenge = { id: 12, scores_finalized: false, double_blind: true };
    const row = (id, rank, score) => ({
      rank,
      public_score: score,
      has_submitted: true,
      user: { id, alias_id: `Alias-${id}`, is_anonymous: false, manual_points: {} },
      task_scores: {},
    });
    const data = [row(2, 1, 0.9), row(3, 1, 0.9), row(4, 4, 0.5)];

    renderWithProviders(
      <LeaderboardTable data={data} tasks={[]} challenge={challenge} loading={false} />,
    );

    expect(screen.queryAllByTitle(/^Rank /).map((el) => el.getAttribute('title'))).toEqual([
      'Rank 1',
      'Rank 1',
      'Rank 4',
    ]);
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

  it('saves decimal manual points via modal', async () => {
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

    const pointsInput = screen.getByPlaceholderText('Enter points');
    fireEvent.change(pointsInput, { target: { value: '87.5' } });

    fireEvent.click(screen.getByRole('button', { name: /Save/i }));

    await waitFor(() => {
      expect(ChallengeService.saveManualPoints).toHaveBeenCalledWith(12, {
        user_id: 5,
        points: { 10: 87.5 },
        reason: undefined,
      });
    });
    expect(onRefresh).toHaveBeenCalled();
  });

  it('lets an admin edit manual points like the jury', async () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'admin' } });
    ChallengeService.saveManualPoints.mockResolvedValue({ ok: true });
    const challenge = {
      id: 12,
      title: 'Challenge A',
      scores_finalized: false,
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
    fireEvent.change(screen.getByPlaceholderText('Enter points'), { target: { value: '12' } });
    fireEvent.click(screen.getByRole('button', { name: /Save/i }));

    await waitFor(() => {
      expect(ChallengeService.saveManualPoints).toHaveBeenCalledWith(12, {
        user_id: 5,
        points: { 10: 12 },
        reason: undefined,
      });
    });
  });

  it.each([
    ['the real name when identities are shown', false, 'Player One'],
    ['the alias in a double-blind competition', true, 'Alias-005'],
  ])('titles the grading modal with %s, as the row shows it', (_label, doubleBlind, name) => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'jury' } });
    const challenge = { id: 12, scores_finalized: false, double_blind: doubleBlind };
    const tasks = [{ id: 10, title: 'Task 1' }];
    const data = [
      {
        rank: 1,
        public_score: 0.9,
        total_points: 1,
        user: { id: 5, username: 'player1', alias_id: 'Alias-005', name: 'Player', surname: 'One' },
        task_scores: { 10: { public_score: 0.9 } },
      },
    ];

    renderWithProviders(
      <LeaderboardTable data={data} tasks={tasks} challenge={challenge} loading={false} />,
    );

    expect(screen.getByText(name)).toBeInTheDocument();
    fireEvent.click(screen.getByTitle('Toggle details'));
    fireEvent.click(screen.getByRole('button', { name: /0 pts/i }));

    expect(screen.getByText(`Grading Competitor: ${name}`)).toBeInTheDocument();
    expect(screen.queryByText(/\{\{name\}\}/)).not.toBeInTheDocument();
  });

  it('tells the jury that private scores stay hidden until the results are final', () => {
    const challenge = {
      id: 12,
      title: 'Challenge A',
      scores_finalized: false,
      double_blind: false,
    };
    const tasks = [{ id: 10, title: 'Task 1' }];
    const data = [
      {
        rank: 1,
        public_score: 0.9,
        private_score: null,
        total_points: 0,
        user: { id: 5, username: 'player1', name: 'Player', surname: 'One' },
        task_scores: { 10: { public_score: 0.9, private_score: null } },
      },
    ];
    const notice = 'Private scores stay hidden from the jury until the results are finalised.';

    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'jury' } });
    const { unmount } = renderWithProviders(
      <LeaderboardTable data={data} tasks={tasks} challenge={challenge} loading={false} />,
    );
    expect(screen.getByText(notice)).toBeInTheDocument();
    // A task whose scores are not final shows no private column to the jury
    fireEvent.click(screen.getByText('Task 1'));
    expect(screen.queryByText('Private Score')).not.toBeInTheDocument();
    expect(screen.queryByText('NaN')).not.toBeInTheDocument();
    unmount();

    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'admin' } });
    renderWithProviders(
      <LeaderboardTable data={data} tasks={tasks} challenge={challenge} loading={false} />,
    );
    expect(screen.queryByText(notice)).not.toBeInTheDocument();
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

    const pointsInput = screen.getByPlaceholderText('Enter points');
    fireEvent.change(pointsInput, { target: { value: '200' } });

    fireEvent.click(screen.getByRole('button', { name: /Save/i }));

    await waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith(
        'Points must be between 0 and 100, with at most 2 decimal places',
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
