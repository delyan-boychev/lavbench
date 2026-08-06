import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { useAuth } from '../../../AuthContext';
import ProtectedLayout from '../ProtectedLayout';

// Mock routing components
vi.mock('react-router-dom', () => ({
  Outlet: () => <div data-testid="router-outlet" />,
  Navigate: ({ to, replace }) => (
    <div data-testid="router-navigate" data-to={to} data-replace={replace ? 'true' : 'false'} />
  ),
  useLocation: () => ({ pathname: '/mock-path' }),
}));

// Mock AuthContext hook
vi.mock('../../../AuthContext', () => ({
  useAuth: vi.fn(),
}));

// Mock sub-layouts to avoid secondary context dependencies
vi.mock('../Navbar', () => ({
  default: () => <div data-testid="navbar" />,
}));
vi.mock('../CompetitionBar', () => ({
  default: () => <div data-testid="competition-bar" />,
}));

describe('ProtectedLayout Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders loading indicator when authLoading is true', () => {
    useAuth.mockReturnValue({
      currentUser: null,
      authLoading: true,
    });

    render(<ProtectedLayout />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(screen.queryByTestId('navbar')).not.toBeInTheDocument();
  });

  it('redirects to login page if no auth token is present', () => {
    useAuth.mockReturnValue({
      currentUser: null,
      authLoading: false,
    });

    render(<ProtectedLayout />);
    const navigateEl = screen.getByTestId('router-navigate');
    expect(navigateEl).toBeInTheDocument();
    expect(navigateEl).toHaveAttribute('data-to', '/login');
    expect(navigateEl).toHaveAttribute('data-replace', 'true');
    expect(screen.queryByTestId('navbar')).not.toBeInTheDocument();
  });

  it('shows a retryable state for a transient auth check failure', () => {
    const fetchUser = vi.fn();
    useAuth.mockReturnValue({
      currentUser: { id: 1, username: 'test', role: 'admin' },
      authLoading: false,
      authCheckError: true,
      fetchUser,
    });

    render(<ProtectedLayout />);

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Authentication is temporarily unavailable. Please try again.',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(fetchUser).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('router-navigate')).not.toBeInTheDocument();
  });

  it('renders navbar, competition bar, and outlet content when logged in', () => {
    useAuth.mockReturnValue({
      currentUser: { id: 1, username: 'test', role: 'admin' },
      authLoading: false,
    });

    render(<ProtectedLayout />);

    expect(screen.getByTestId('navbar')).toBeInTheDocument();
    expect(screen.getByTestId('competition-bar')).toBeInTheDocument();
    expect(screen.getByTestId('router-outlet')).toBeInTheDocument();
    expect(screen.getByText(/LavBench/)).toBeInTheDocument();
  });
});
