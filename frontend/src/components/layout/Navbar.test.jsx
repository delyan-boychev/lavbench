import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import Navbar from './Navbar';

// Mock AuthContext
vi.mock('../../AuthContext', () => ({
  useAuth: vi.fn(),
}));

// Mock AppContext
vi.mock('../../context/AppContext', () => ({
  useApp: vi.fn(),
}));

// Mock Logo
vi.mock('../ui/Logo', () => ({
  default: () => <div data-testid="logo" />,
}));

// Mock Badge
vi.mock('../ui/Badge', () => ({
  default: ({ status }) => <span data-testid="badge">{status}</span>,
}));

describe('Navbar Component', () => {
  const mockLogout = vi.fn();
  const mockToggleTheme = vi.fn();
  const mockShowToast = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    useApp.mockReturnValue({
      theme: 'dark',
      toggleTheme: mockToggleTheme,
      showToast: mockShowToast,
    });
    // Mock successful fetch for status check
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'online' }),
    });
  });

  it('renders logo and user info when logged in', async () => {
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123', name: 'John', surname: 'Doe' },
      token: 'valid-token',
      logout: mockLogout,
    });

    render(<Navbar />);

    expect(screen.getByTestId('logo')).toBeInTheDocument();
    expect(screen.getByText('John Doe')).toBeInTheDocument();
    expect(screen.getByText('Alias-123')).toBeInTheDocument();
    expect(screen.getByTestId('badge')).toHaveTextContent('competitor');
  });

  it('polls worker status endpoint and displays online badge', async () => {
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      token: 'valid-token',
      logout: mockLogout,
    });

    render(<Navbar />);

    expect(global.fetch).toHaveBeenCalledWith('/api/worker-status', {
      headers: { 'Authorization': 'Bearer valid-token' }
    });

    await vi.waitFor(() => {
      expect(screen.getByText('Cluster Online')).toBeInTheDocument();
    });
  });

  it('handles offline worker status gracefully', async () => {
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      token: 'valid-token',
      logout: mockLogout,
    });

    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
    });

    render(<Navbar />);

    await vi.waitFor(() => {
      expect(screen.getByText('Cluster Offline')).toBeInTheDocument();
    });
  });

  it('opens clusters modal on status button click', async () => {
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      token: 'valid-token',
      logout: mockLogout,
    });

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        status: 'online',
        clusters: [
          { name: 'celery@cpu-worker', type: 'CPU', concurrency: 4, gpu_type: 'N/A', ram_gb: 16, vram_gb: 'N/A' }
        ]
      }),
    });

    render(<Navbar />);

    const statusBtn = screen.getByText('Cluster Online');
    fireEvent.click(statusBtn);

    expect(screen.getByText('Active Cluster Node Specifications')).toBeInTheDocument();

    await vi.waitFor(() => {
      expect(screen.getByText('celery@cpu-worker')).toBeInTheDocument();
      expect(screen.getByText('4 tasks')).toBeInTheDocument();
      expect(screen.getByText('16 GB')).toBeInTheDocument();
    });
  });

  it('triggers theme toggle on clicking the theme button', () => {
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      token: 'valid-token',
      logout: mockLogout,
    });

    render(<Navbar />);

    const themeBtn = screen.getByTitle('Switch to light mode');
    fireEvent.click(themeBtn);

    expect(mockToggleTheme).toHaveBeenCalledTimes(1);
  });

  it('calls logout and shows success toast when clicking Sign out', () => {
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      token: 'valid-token',
      logout: mockLogout,
    });

    render(<Navbar />);

    const signoutBtn = screen.getByText('Sign out');
    fireEvent.click(signoutBtn);

    expect(mockLogout).toHaveBeenCalledTimes(1);
    expect(mockShowToast).toHaveBeenCalledWith('Signed out successfully.');
  });
});
