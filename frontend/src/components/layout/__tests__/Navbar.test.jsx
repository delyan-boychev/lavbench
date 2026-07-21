import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, act } from '@testing-library/react';
import { renderWithProviders } from '../../../test-utils';
import { useAuth } from '../../../AuthContext';
import { useApp } from '../../../context/AppContext';
import Navbar from '../Navbar';

// Mock AuthContext
vi.mock('../../../AuthContext', () => ({
  useAuth: vi.fn(),
}));

// Mock AppContext
vi.mock('../../../context/AppContext', () => ({
  useApp: vi.fn(),
}));

// Mock react-router-dom for useLocation
vi.mock('react-router-dom', () => ({
  useLocation: () => ({ pathname: '/' }),
}));

// Mock Logo
vi.mock('../../ui/Logo', () => ({
  default: () => <div data-testid="logo" />,
}));

// Mock Badge
vi.mock('../../ui/Badge', () => ({
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
    global.EventSource = class {
      constructor(url) {
        this.url = url;
        this.close = vi.fn();
      }
    };
  });

  it('renders logo and user info when logged in', async () => {
    useAuth.mockReturnValue({
      currentUser: {
        username: 'testuser',
        role: 'competitor',
        alias_id: 'Alias-123',
        name: 'John',
        surname: 'Doe',
      },
      logout: mockLogout,
    });

    renderWithProviders(<Navbar />);

    expect(screen.getByTestId('logo')).toBeInTheDocument();
    expect(screen.getAllByText('John Doe').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Alias-123').length).toBeGreaterThan(0);
    const badges = screen.getAllByTestId('badge');
    expect(badges.some((b) => b.textContent === 'competitor')).toBe(true);
  });

  it('polls worker status endpoint and displays online badge', async () => {
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      logout: mockLogout,
    });

    let eventSourceInstance;
    global.EventSource = class {
      constructor(url) {
        this.url = url;
        this.close = vi.fn();
        eventSourceInstance = this;
      }
    };

    renderWithProviders(<Navbar />);

    expect(eventSourceInstance.url).toBe('/api/worker-status/live');

    // Simulate SSE data arriving
    act(() => {
      eventSourceInstance.onmessage({ data: JSON.stringify({ status: 'online', clusters: [] }) });
    });

    await vi.waitFor(() => {
      expect(screen.getByText('Cluster')).toBeInTheDocument();
    });
  });

  it('handles offline worker status gracefully', async () => {
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      logout: mockLogout,
    });

    global.EventSource = class {
      constructor() {
        this.close = vi.fn();
        this.onmessage = null;
        this.onerror = () => {};
        // Simulate error immediately
        setTimeout(() => {
          if (this.onerror) {
            act(() => {
              this.onerror();
            });
          }
        }, 0);
      }
    };

    renderWithProviders(<Navbar />);

    await vi.waitFor(() => {
      expect(screen.getByText('Cluster')).toBeInTheDocument();
    });
  });

  it('opens clusters modal on status button click', async () => {
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      logout: mockLogout,
    });

    let eventSourceInstance;
    global.EventSource = class {
      constructor(url) {
        this.url = url;
        this.close = vi.fn();
        this.onmessage = vi.fn();
        eventSourceInstance = this;
      }
    };

    renderWithProviders(<Navbar />);

    // Simulate SSE with cluster data
    act(() => {
      eventSourceInstance.onmessage({
        data: JSON.stringify({
          status: 'online',
          clusters: [
            {
              name: 'celery@cpu-worker',
              type: 'CPU',
              concurrency: 4,
              gpu_type: 'N/A',
              ram_gb: 16,
              vram_gb: 'N/A',
            },
          ],
        }),
      });
    });

    const statusBtn = screen.getByText('Cluster');
    await act(async () => {
      fireEvent.click(statusBtn);
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByText('Cluster Info & Active Node Specifications')).toBeInTheDocument();

    await vi.waitFor(() => {
      expect(screen.getByText('celery@cpu-worker')).toBeInTheDocument();
      expect(screen.getByText('4 tasks')).toBeInTheDocument();
      expect(screen.getByText('16 GB')).toBeInTheDocument();
    });

    // Click again to close (toggle)
    await act(async () => {
      fireEvent.click(statusBtn);
      await new Promise((r) => setTimeout(r, 220));
    });
    await vi.waitFor(() => {
      expect(
        screen.queryByText('Cluster Info & Active Node Specifications'),
      ).not.toBeInTheDocument();
    });
  });

  it('triggers theme toggle on clicking the theme button', () => {
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      logout: mockLogout,
    });

    renderWithProviders(<Navbar />);

    const themeBtn = screen.getByTitle('Switch to light mode');
    fireEvent.click(themeBtn);

    expect(mockToggleTheme).toHaveBeenCalledTimes(1);
  });

  it('calls logout and shows success toast when clicking Sign out', () => {
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      logout: mockLogout,
    });

    renderWithProviders(<Navbar />);

    const signoutBtn = screen.getByTitle('Sign out');
    fireEvent.click(signoutBtn);

    expect(mockLogout).toHaveBeenCalledTimes(1);
    expect(mockShowToast).toHaveBeenCalledWith('Signed out successfully.');
  });

  it('renders and fetches docs based on role permissions', async () => {
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      logout: mockLogout,
    });

    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url) => {
        if (url.includes('/api/docs/competitor')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                title: 'Competitor Guide',
                content: 'Competitor Guide Content',
              }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'online', clusters: [] }),
        });
      }),
    );

    renderWithProviders(<Navbar />);

    const docsBtn = screen.getByText('Docs');
    fireEvent.click(docsBtn);

    expect(screen.getByText('Documentation & Guides')).toBeInTheDocument();

    expect(await screen.findByText('Competitor Guide Content')).toBeInTheDocument();
  });

  it('renders blockquote alerts correctly and cleans the tag even with leading newlines', async () => {
    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
      logout: mockLogout,
    });

    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url) => {
        if (url.includes('/api/docs/competitor')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                title: 'Competitor Guide',
                content: '> [!NOTE]\n> This is a test note.',
              }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'online', clusters: [] }),
        });
      }),
    );

    renderWithProviders(<Navbar />);

    const docsBtn = screen.getByText('Docs');
    fireEvent.click(docsBtn);

    expect(await screen.findByText('This is a test note.')).toBeInTheDocument();
    expect(screen.queryByText(/\[!NOTE\]/)).toBeNull();
    expect(screen.getByText('Note')).toBeInTheDocument();
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
        },
      ],
    };

    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
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

    renderWithProviders(<Navbar />);

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
        },
      ],
    };

    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
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

    renderWithProviders(<Navbar />);

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
        },
      ],
    };

    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
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

    renderWithProviders(<Navbar />);

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
        },
      ],
    };

    useAuth.mockReturnValue({
      currentUser: { username: 'testuser', role: 'competitor', alias_id: 'Alias-123' },
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

    renderWithProviders(<Navbar />);

    const timer = screen.getByTitle('Time remaining in Stage 1');
    expect(timer).toBeInTheDocument();
    expect(timer).toHaveStyle({ color: '#ef4444' });
    expect(timer).toHaveTextContent('Stage 1 left: 00:03:00');
    expect(timer).toHaveClass('animate-flash-red');
  });
});
