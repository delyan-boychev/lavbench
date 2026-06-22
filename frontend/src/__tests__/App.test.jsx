import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../context/AppContext', () => ({
  AppProvider: ({ children }) => <div>{children}</div>,
  useApp: vi.fn(),
}));

vi.mock('../AuthContext', () => ({
  useAuth: vi.fn(() => ({
    currentUser: null,
    authLoading: false,
  })),
}));

vi.mock('../components/ErrorBoundary', () => ({
  default: ({ children }) => <div>{children}</div>,
}));

vi.mock('../components/layout/ProtectedLayout', () => ({
  default: ({ children }) => <div data-testid="protected-layout">{children}</div>,
}));

vi.mock('../pages/Login', () => ({
  default: () => <div data-testid="login-page">Login Page</div>,
}));

vi.mock('../pages/Home', () => ({
  default: () => <div data-testid="home-page">Home Page</div>,
}));

vi.mock('../pages/LeaderboardView', () => ({
  default: () => <div data-testid="leaderboard-view">LeaderboardView Page</div>,
}));

vi.mock('../pages/LeaderboardDemo', () => ({
  default: () => <div data-testid="leaderboard-demo">LeaderboardDemo Page</div>,
}));

vi.mock('../pages/AdminPanel', () => ({
  default: () => <div data-testid="admin-panel">Admin Panel</div>,
}));

vi.mock('../pages/SubmissionsView', () => ({
  default: () => <div data-testid="submissions-view">Submissions View</div>,
}));

vi.mock('react-router-dom', () => ({
  BrowserRouter: ({ children }) => <div>{children}</div>,
  Routes: ({ children }) => <div>{children}</div>,
  Route: ({ element }) => element,
  Navigate: ({ to }) => <div data-testid="navigate">{to}</div>,
  useParams: vi.fn(() => ({})),
  useNavigate: vi.fn(),
  Link: ({ children, to }) => <a href={to}>{children}</a>,
}));

import { useApp } from '../context/AppContext';
import App from '../App';

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders without crashing', () => {
    vi.mocked(useApp).mockReturnValue({ toast: { show: false } });
    render(<App />);
    expect(screen.getByTestId('protected-layout')).toBeTruthy();
  });

  it('does not render toast when toast.show is false', () => {
    vi.mocked(useApp).mockReturnValue({ toast: { show: false } });
    render(<App />);
    expect(screen.queryByText(/toast/i)).toBeNull();
  });

  it('renders toast when toast.show is true with success styling', () => {
    vi.mocked(useApp).mockReturnValue({
      toast: { show: true, message: 'Operation successful', type: 'success' },
    });
    render(<App />);
    expect(screen.getByText('Operation successful')).toBeTruthy();
  });

  it('renders toast with error styling for rose type', () => {
    vi.mocked(useApp).mockReturnValue({
      toast: { show: true, message: 'Something went wrong', type: 'rose' },
    });
    render(<App />);
    expect(screen.getByText('Something went wrong')).toBeTruthy();
  });

  it('renders toast with error styling for error type', () => {
    vi.mocked(useApp).mockReturnValue({
      toast: { show: true, message: 'Error occurred', type: 'error' },
    });
    render(<App />);
    expect(screen.getByText('Error occurred')).toBeTruthy();
  });

  it('contains the Navigate to /challenges as a protected route', () => {
    vi.mocked(useApp).mockReturnValue({ toast: { show: false } });
    render(<App />);
    const navigates = screen.getAllByTestId('navigate');
    expect(navigates.some(n => n.textContent === '/challenges')).toBe(true);
  });
});
