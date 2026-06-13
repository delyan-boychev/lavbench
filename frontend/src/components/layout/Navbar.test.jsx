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
      expect(screen.getByText('Cluster')).toBeInTheDocument();
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
      expect(screen.getByText('Cluster')).toBeInTheDocument();
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

    const statusBtn = screen.getByText('Cluster');
    fireEvent.click(statusBtn);

    expect(screen.getByText('Cluster Info & Active Node Specifications')).toBeInTheDocument();

    await vi.waitFor(() => {
      expect(screen.getByText('celery@cpu-worker')).toBeInTheDocument();
      expect(screen.getByText('4 tasks')).toBeInTheDocument();
      expect(screen.getByText('16 GB')).toBeInTheDocument();
    });

    // Click again to close (toggle)
    fireEvent.click(statusBtn);
    await vi.waitFor(() => {
      expect(screen.queryByText('Cluster Info & Active Node Specifications')).not.toBeInTheDocument();
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

  it('renders and fetches docs based on role permissions', async () => {
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      token: 'valid-token',
      logout: mockLogout,
    });

    global.fetch = vi.fn().mockImplementation((url) => {
      if (url.includes('/api/docs/student')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            title: 'Student Guide',
            content: 'Student Guide Content'
          })
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ status: 'online', clusters: [] })
      });
    });

    render(<Navbar />);

    const docsBtn = screen.getByText('Docs');
    fireEvent.click(docsBtn);

    expect(screen.getByText('Documentation & Guides')).toBeInTheDocument();

    await vi.waitFor(() => {
      expect(screen.getByText('Student Guide Content')).toBeInTheDocument();
    });
  });

  it('renders blockquote alerts correctly and cleans the tag even with leading newlines', async () => {
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      token: 'valid-token',
      logout: mockLogout,
    });

    global.fetch = vi.fn().mockImplementation((url) => {
      if (url.includes('/api/docs/student')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            title: 'Student Guide',
            content: '> [!NOTE]\n> This is a test note.'
          })
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ status: 'online', clusters: [] })
      });
    });

    render(<Navbar />);

    const docsBtn = screen.getByText('Docs');
    fireEvent.click(docsBtn);

    await vi.waitFor(() => {
      expect(screen.queryByText(/\[!NOTE\]/)).toBeNull();
      expect(screen.getByText('Note')).toBeInTheDocument();
      expect(screen.getByText('This is a test note.')).toBeInTheDocument();
    });
  });

  it('renders countdown timer in green when time remaining is > 30 minutes', async () => {
    const mockChallenge = {
      id: 1,
      title: 'Challenge Alpha',
      stages: [
        {
          id: 10,
          title: 'Stage 1',
          stage_number: 1,
          start_time: '2026-06-13T10:00:00Z',
          end_time: '2026-06-13T12:00:00Z',
          is_finalized: false,
        }
      ]
    };
    
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      token: 'valid-token',
      logout: mockLogout,
    });

    useApp.mockReturnValue({
      theme: 'dark',
      toggleTheme: mockToggleTheme,
      showToast: mockShowToast,
      selectedChallenge: mockChallenge,
    });

    const mockSystemTime = new Date('2026-06-13T11:00:00Z').getTime();
    vi.spyOn(Date, 'now').mockReturnValue(mockSystemTime);

    render(<Navbar />);

    const timer = screen.getByTitle('Time remaining in Stage 1');
    expect(timer).toBeInTheDocument();
    expect(timer).toHaveStyle({ color: '#10b981' });
    expect(timer).toHaveTextContent('Stage 1 left: 01:00:00');
    expect(timer).not.toHaveClass('animate-flash-red');
  });

  it('renders countdown timer in yellow when time remaining is <= 30 minutes and > 15 minutes', async () => {
    const mockChallenge = {
      id: 1,
      title: 'Challenge Alpha',
      stages: [
        {
          id: 10,
          title: 'Stage 1',
          stage_number: 1,
          start_time: '2026-06-13T10:00:00Z',
          end_time: '2026-06-13T12:00:00Z',
          is_finalized: false,
        }
      ]
    };
    
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      token: 'valid-token',
      logout: mockLogout,
    });

    useApp.mockReturnValue({
      theme: 'dark',
      toggleTheme: mockToggleTheme,
      showToast: mockShowToast,
      selectedChallenge: mockChallenge,
    });

    const mockSystemTime = new Date('2026-06-13T11:40:00Z').getTime();
    vi.spyOn(Date, 'now').mockReturnValue(mockSystemTime);

    render(<Navbar />);

    const timer = screen.getByTitle('Time remaining in Stage 1');
    expect(timer).toBeInTheDocument();
    expect(timer).toHaveStyle({ color: '#f59e0b' });
    expect(timer).toHaveTextContent('Stage 1 left: 00:20:00');
    expect(timer).not.toHaveClass('animate-flash-red');
  });

  it('renders countdown timer in red when time remaining is <= 15 minutes and > 5 minutes', async () => {
    const mockChallenge = {
      id: 1,
      title: 'Challenge Alpha',
      stages: [
        {
          id: 10,
          title: 'Stage 1',
          stage_number: 1,
          start_time: '2026-06-13T10:00:00Z',
          end_time: '2026-06-13T12:00:00Z',
          is_finalized: false,
        }
      ]
    };
    
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      token: 'valid-token',
      logout: mockLogout,
    });

    useApp.mockReturnValue({
      theme: 'dark',
      toggleTheme: mockToggleTheme,
      showToast: mockShowToast,
      selectedChallenge: mockChallenge,
    });

    const mockSystemTime = new Date('2026-06-13T11:50:00Z').getTime();
    vi.spyOn(Date, 'now').mockReturnValue(mockSystemTime);

    render(<Navbar />);

    const timer = screen.getByTitle('Time remaining in Stage 1');
    expect(timer).toBeInTheDocument();
    expect(timer).toHaveStyle({ color: '#ef4444' });
    expect(timer).toHaveTextContent('Stage 1 left: 00:10:00');
    expect(timer).not.toHaveClass('animate-flash-red');
  });

  it('renders countdown timer in red and flashing when time remaining is <= 5 minutes', async () => {
    const mockChallenge = {
      id: 1,
      title: 'Challenge Alpha',
      stages: [
        {
          id: 10,
          title: 'Stage 1',
          stage_number: 1,
          start_time: '2026-06-13T10:00:00Z',
          end_time: '2026-06-13T12:00:00Z',
          is_finalized: false,
        }
      ]
    };
    
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      token: 'valid-token',
      logout: mockLogout,
    });

    useApp.mockReturnValue({
      theme: 'dark',
      toggleTheme: mockToggleTheme,
      showToast: mockShowToast,
      selectedChallenge: mockChallenge,
    });

    const mockSystemTime = new Date('2026-06-13T11:57:00Z').getTime();
    vi.spyOn(Date, 'now').mockReturnValue(mockSystemTime);

    render(<Navbar />);

    const timer = screen.getByTitle('Time remaining in Stage 1');
    expect(timer).toBeInTheDocument();
    expect(timer).toHaveStyle({ color: '#ef4444' });
    expect(timer).toHaveTextContent('Stage 1 left: 00:03:00');
    expect(timer).toHaveClass('animate-flash-red');
  });
});
