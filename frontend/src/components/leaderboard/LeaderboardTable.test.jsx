import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import ChallengeService from '../../services/ChallengeService';
import LeaderboardTable from './LeaderboardTable';

// Mock AuthContext
vi.mock('../../AuthContext', () => ({
  useAuth: vi.fn(),
}));

// Mock AppContext
vi.mock('../../context/AppContext', () => ({
  useApp: vi.fn(),
}));

// Mock ChallengeService
vi.mock('../../services/ChallengeService', () => ({
  default: {
    finalize: vi.fn(),
    saveManualPoints: vi.fn(),
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
    render(<LeaderboardTable data={[]} tasks={[]} challenge={null} loading={true} />);
    expect(screen.getByText('Loading leaderboard...')).toBeInTheDocument();
  });

  it('renders empty state message when data is empty', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    render(<LeaderboardTable data={[]} tasks={[]} challenge={{ scores_finalized: false }} loading={false} />);
    expect(screen.getByText('No scored submissions yet. Be the first!')).toBeInTheDocument();
  });

  it('renders participant alias IDs instead of true identity when scores are not finalized', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    const challenge = { id: 12, title: 'Challenge A', scores_finalized: false, metric_name: 'Accuracy' };
    const tasks = [{ id: 1, title: 'Task 1' }];
    const data = [
      { 
        rank: 1, 
        public_score: 0.9876, 
        has_submitted: true,
        user: { id: 2, username: 'user_two', alias_id: 'Alias-002', name: 'John', surname: 'Doe' },
        task_scores: { "1": { public_score: 0.9876 } }
      },
      { 
        rank: 2, 
        public_score: 0.8523, 
        has_submitted: true,
        user: { id: 1, username: 'user_one', alias_id: 'Alias-001', name: 'My', surname: 'Name' },
        task_scores: { "1": { public_score: 0.8523 } }
      },
    ];

    render(<LeaderboardTable data={data} tasks={tasks} challenge={challenge} loading={false} />);

    // Renders Rank Medals
    expect(screen.getByTitle('Rank 1')).toBeInTheDocument();
    expect(screen.getByTitle('Rank 2')).toBeInTheDocument();

    // Renders "You" badge for current user, and shows their real name
    expect(screen.getByText('You')).toBeInTheDocument();
    expect(screen.getByText('My Name')).toBeInTheDocument();

    // Blind review is in effect for John Doe, so John Doe should NOT be visible, only their alias
    expect(screen.queryByText('John Doe')).not.toBeInTheDocument();
    expect(screen.getByText('Alias-002')).toBeInTheDocument();
    
    // Scores
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
      reveal_public_scores: true,
      reveal_private_scores: true,
      reveal_points: true 
    };
    const tasks = [{ id: 1, title: 'Task 1' }];
    const data = [
      { 
        rank: 1, 
        public_score: 0.9876, 
        private_score: 0.9912, 
        total_points: 95,
        has_submitted: true,
        user: { id: 2, username: 'user_two', alias_id: 'Alias-002', name: 'John', surname: 'Doe', school: 'Math High School', grade: '10' },
        task_scores: { "1": { public_score: 0.9876, private_score: 0.9912 } }
      },
    ];

    render(<LeaderboardTable data={data} tasks={tasks} challenge={challenge} loading={false} />);

    // Click details to expand the row
    const expandBtn = screen.getByTitle('Toggle details');
    fireEvent.click(expandBtn);

    // True identity revealed (shown in both cell and expanded panel)
    expect(screen.getAllByText('John Doe').length).toBe(2);
    
    // School and Grade headers and values are visible in the expanded panel
    expect(screen.getByText('School:')).toBeInTheDocument();
    expect(screen.getByText('Math High School')).toBeInTheDocument();
    expect(screen.getByText('Grade:')).toBeInTheDocument();
    expect(screen.getByText('10 grade')).toBeInTheDocument();

    // Total points visible
    expect(screen.getByText('95 pts')).toBeInTheDocument();
  });

  it('allows jury to finalize challenge scores', async () => {
    useAuth.mockReturnValue({ currentUser: { id: 99, role: 'jury' } });
    const challenge = { id: 12, title: 'Challenge A', scores_finalized: false, metric_name: 'Accuracy' };
    const data = [
      { rank: 1, public_score: 0.9876, user: { id: 2, username: 'user_two', alias_id: 'Alias-002' }, task_scores: {} },
    ];

    ChallengeService.finalize.mockResolvedValue({ ok: true });

    render(<LeaderboardTable data={data} tasks={[]} challenge={challenge} loading={false} />);

    const button = screen.getByText('Finalize & Reveal Identities');
    expect(button).toBeInTheDocument();

    fireEvent.click(button);

    // Click the submit button inside the modal
    const submitBtn = screen.getByText('Finalize & Reveal');
    expect(submitBtn).toBeInTheDocument();
    fireEvent.click(submitBtn);

    expect(ChallengeService.finalize).toHaveBeenCalledWith(12, {
      reveal_public_scores: true,
      reveal_private_scores: true,
      reveal_points: true
    });

    // Give microtask queue time to flush for async call
    await vi.waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith('Scores finalized — visibility options applied.');
      expect(mockFetchChallenges).toHaveBeenCalled();
    });
  });
});
