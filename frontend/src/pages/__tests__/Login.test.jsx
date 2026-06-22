import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { useAuth } from '../../AuthContext';
// eslint-disable-next-line no-unused-vars
import { useApp } from '../../context/AppContext';
import Login from '../Login';

const mockNavigate = vi.fn();
const mockLogin = vi.fn();

vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}));

vi.mock('../../AuthContext', () => ({
  useAuth: vi.fn(() => ({
    currentUser: null,
    authLoading: false,
    authError: null,
    login: mockLogin,
  })),
}));

vi.mock('../../context/AppContext', () => ({
  useApp: vi.fn(() => ({
    theme: 'dark',
    toggleTheme: vi.fn(),
  })),
}));

describe('Login Page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('redirects to /challenges when already authenticated', () => {
    useAuth.mockReturnValue({
      currentUser: { id: 1, username: 'testuser' },
      authLoading: false,
      authError: null,
      login: mockLogin,
    });

    render(<Login />);

    expect(mockNavigate).toHaveBeenCalledWith('/challenges', { replace: true });
  });

  it('renders login form for unauthenticated user', () => {
    render(<Login />);

    expect(screen.getByText('Sign In')).toBeInTheDocument();
    expect(screen.getByText('Password')).toBeInTheDocument();
    expect(screen.getByText('Username')).toBeInTheDocument();
  });

  it('submits form on button click', async () => {
    mockLogin.mockResolvedValue({ success: true });
    render(<Login />);

    fireEvent.change(screen.getByPlaceholderText('comp_ali_lov_3812, jury, or admin_...'), { target: { value: 'testuser' } });
    fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'password123' } });

    await act(async () => {
      fireEvent.click(screen.getByText('Sign In'));
    });

    expect(mockLogin).toHaveBeenCalledWith('testuser', 'password123');
  });

  it('displays error from authError', () => {
    useAuth.mockReturnValue({
      currentUser: null,
      authLoading: false,
      authError: 'Authentication failed.',
      login: mockLogin,
    });

    render(<Login />);

    expect(screen.getByText('Authentication failed.')).toBeInTheDocument();
  });

  it('shows loading state during authentication', async () => {
    let resolveLogin;
    mockLogin.mockReturnValue(new Promise(resolve => { resolveLogin = resolve; }));

    render(<Login />);

    fireEvent.change(screen.getByPlaceholderText('comp_ali_lov_3812, jury, or admin_...'), { target: { value: 'testuser' } });
    fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'password123' } });

    act(() => {
      fireEvent.click(screen.getByText('Sign In'));
    });

    expect(screen.getByText('Signing In...')).toBeInTheDocument();
    expect(screen.getByText('Signing In...')).toBeDisabled();

    await act(async () => {
      resolveLogin({ success: true });
    });

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/challenges', { replace: true });
    });
  });

  it('renders language switch button', () => {
    render(<Login />);

    expect(screen.getByText('BG')).toBeInTheDocument();
  });
});
