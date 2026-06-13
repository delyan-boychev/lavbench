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
    render(<LeaderboardTable data={[]} challenge={null} loading={true} />);
    expect(screen.getByText('Loading leaderboard...')).toBeInTheDocument();
  });

  it('renders empty state message when data is empty', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    render(<LeaderboardTable data={[]} challenge={{ scores_finalized: false }} loading={false} />);
    expect(screen.getByText('No scored submissions yet. Be the first!')).toBeInTheDocument();
  });

  it('renders participant alias IDs instead of true identity when scores are not finalized', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    const challenge = { id: 12, title: 'Challenge A', scores_finalized: false, metric_name: 'Accuracy' };
    const data = [
      { id: 101, rank: 1, public_score: 0.9876, user: { id: 2, username: 'user_two', alias_id: 'Alias-002', name: 'John', surname: 'Doe' } },
      { id: 102, rank: 2, public_score: 0.8523, user: { id: 1, username: 'user_one', alias_id: 'Alias-001', name: 'My', surname: 'Name' } },
    ];

    render(<LeaderboardTable data={data} challenge={challenge} loading={false} />);

    // Renders Rank Medals
    expect(screen.getByText('🥇')).toBeInTheDocument();
    expect(screen.getByText('🥈')).toBeInTheDocument();

    // Renders "You" badge for current user, and shows their real name
    expect(screen.getByText('You')).toBeInTheDocument();
    expect(screen.getByText('My Name')).toBeInTheDocument();

    // Blind review is in effect for John Doe, so John Doe should NOT be visible, only their alias
    expect(screen.queryByText('John Doe')).not.toBeInTheDocument();
    expect(screen.getByText('Alias-002')).toBeInTheDocument();
    
    // Scores
    expect(screen.getByText('0.9876')).toBeInTheDocument();
    expect(screen.getByText('0.8523')).toBeInTheDocument();
  });

  it('reveals true identities and private scores when challenge is finalized', () => {
    useAuth.mockReturnValue({ currentUser: { id: 1, role: 'competitor' } });
    const challenge = { id: 12, title: 'Challenge A', scores_finalized: true, metric_name: 'Accuracy' };
    const data = [
      { id: 101, rank: 1, public_score: 0.9876, private_score: 0.9912, user: { id: 2, username: 'user_two', alias_id: 'Alias-002', name: 'John', surname: 'Doe' } },
    ];

    render(<LeaderboardTable data={data} challenge={challenge} loading={false} />);

    // True identity revealed
    expect(screen.getByText('John Doe')).toBeInTheDocument();
    // Private score column shown
    expect(screen.getByText('0.9912')).toBeInTheDocument();
  });

  it('allows admins or jury to finalize challenge scores', async () => {
    useAuth.mockReturnValue({ currentUser: { id: 99, role: 'admin' } });
    const challenge = { id: 12, title: 'Challenge A', scores_finalized: false, metric_name: 'Accuracy' };
    const data = [
      { id: 101, rank: 1, public_score: 0.9876, user: { id: 2, username: 'user_two', alias_id: 'Alias-002' } },
    ];

    // Mock window.confirm
    const confirmSpy = vi.fn().mockReturnValue(true);
    window.confirm = confirmSpy;
    ChallengeService.finalize.mockResolvedValue({ ok: true });

    render(<LeaderboardTable data={data} challenge={challenge} loading={false} />);

    const button = screen.getByText('Finalize & Reveal Identities');
    expect(button).toBeInTheDocument();

    fireEvent.click(button);

    expect(confirmSpy).toHaveBeenCalled();
    expect(ChallengeService.finalize).toHaveBeenCalledWith(12);

    // Give microtask queue time to flush for async call
    await vi.waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith('Scores finalized — identities revealed.');
      expect(mockFetchChallenges).toHaveBeenCalled();
    });
  });
});
