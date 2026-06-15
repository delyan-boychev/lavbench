import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { useAuth } from '../../AuthContext';
import ProtectedLayout from './ProtectedLayout';

// Mock routing components
vi.mock('react-router-dom', () => ({
  Outlet: () => <div data-testid="router-outlet" />,
  Navigate: ({ to, replace }) => (
    <div data-testid="router-navigate" data-to={to} data-replace={replace ? 'true' : 'false'} />
  ),
  useLocation: () => ({ pathname: '/mock-path' }),
}));

// Mock AuthContext hook
vi.mock('../../AuthContext', () => ({
  useAuth: vi.fn(),
}));

// Mock sub-layouts to avoid secondary context dependencies
vi.mock('./Navbar', () => ({
  default: () => <div data-testid="navbar" />,
}));
vi.mock('./CompetitionBar', () => ({
  default: () => <div data-testid="competition-bar" />,
}));

describe('ProtectedLayout Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders loading indicator when authLoading is true', () => {
    useAuth.mockReturnValue({
      token: null,
      authLoading: true,
    });

    render(<ProtectedLayout />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(screen.queryByTestId('navbar')).not.toBeInTheDocument();
  });

  it('redirects to login page if no auth token is present', () => {
    useAuth.mockReturnValue({
      token: null,
      authLoading: false,
    });

    render(<ProtectedLayout />);
    const navigateEl = screen.getByTestId('router-navigate');
    expect(navigateEl).toBeInTheDocument();
    expect(navigateEl).toHaveAttribute('data-to', '/login');
    expect(navigateEl).toHaveAttribute('data-replace', 'true');
    expect(screen.queryByTestId('navbar')).not.toBeInTheDocument();
  });

  it('renders navbar, competition bar, and outlet content when logged in', () => {
    useAuth.mockReturnValue({
      token: 'mock-valid-token-xyz',
      authLoading: false,
    });

    render(<ProtectedLayout />);

    expect(screen.getByTestId('navbar')).toBeInTheDocument();
    expect(screen.getByTestId('competition-bar')).toBeInTheDocument();
    expect(screen.getByTestId('router-outlet')).toBeInTheDocument();
    expect(screen.getByText(/LavBench/)).toBeInTheDocument();
  });
});
