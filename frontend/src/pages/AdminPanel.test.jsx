import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { useAuth } from '../AuthContext';
import { useApp } from '../context/AppContext';
import AdminPanel from './AdminPanel';

// Mock AuthContext
vi.mock('../AuthContext', () => ({
  useAuth: vi.fn(),
}));

// Mock AppContext
vi.mock('../context/AppContext', () => ({
  useApp: vi.fn(),
}));

const mockSystemStats = {
  connected_workers_count: 1,
  workers: [
    {
      name: "celery@gpu-worker-test",
      status: "online",
      pid: 9999,
      uptime: 3600,
      pool_size: 8,
      total_tasks_processed: 42,
      active_tasks_count: 1,
      reserved_tasks_count: 0,
      active_tasks: [{ id: "test-task-1", name: "tasks.evaluate_submission" }],
      reserved_tasks: [],
      registered_tasks: ["tasks.evaluate_submission"],
      rusage: {
        maxrss_mb: 256.5,
        utime_sec: 1.25,
        stime_sec: 0.75
      },
      broker: {
        transport: "redis",
        hostname: "localhost",
        port: 6379
      }
    }
  ],
  system: {
    cpu_count: 16,
    load_avg: [1.2, 0.95, 0.8],
    memory: {
      total_gb: 32.0,
      used_gb: 16.0,
      free_gb: 16.0,
      percent_used: 50.0
    },
    disk: {
      total_gb: 500.0,
      used_gb: 250.0,
      free_gb: 250.0,
      percent_used: 50.0
    },
    os: "Linux",
    platform_release: "5.15.0",
    python_version: "3.10.5"
  }
};

describe('AdminPanel Page - Workers & Resources', () => {
  const mockShowToast = vi.fn();
  const mockSetSelectedChallengeById = vi.fn();
  const mockFetchChallenges = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    useApp.mockReturnValue({
      challenges: [],
      selectedChallenge: null,
      setSelectedChallengeById: mockSetSelectedChallengeById,
      fetchChallenges: mockFetchChallenges,
      showToast: mockShowToast,
    });
    
    useAuth.mockReturnValue({
      currentUser: { id: 1, username: 'admin', role: 'admin' },
      token: 'valid-admin-token',
    });

    global.fetch = vi.fn().mockImplementation((url) => {
      if (url === '/api/admin/metrics' || url.includes('metrics')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ metrics: {} }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => mockSystemStats,
      });
    });
  });

  it('renders sidebar options including Workers & Resources for admin', () => {
    render(<AdminPanel />);
    expect(screen.getByText('Jury Control Hub')).toBeInTheDocument();
    expect(screen.getByText('Workers & Resources')).toBeInTheDocument();
  });

  it('switches to Workers & Resources tab and fetches detailed stats', async () => {
    render(<AdminPanel />);
    
    const workersTabBtn = screen.getByText('Workers & Resources');
    
    await act(async () => {
      fireEvent.click(workersTabBtn);
    });

    // Check it calls fetch with correct URL and headers
    expect(global.fetch).toHaveBeenCalledWith('/api/admin/workers/stats', expect.objectContaining({
      headers: expect.objectContaining({ 'Authorization': 'Bearer valid-admin-token' })
    }));

    // Verify system stats section renders
    await vi.waitFor(() => {
      expect(screen.getByText('System Resources & Worker Status')).toBeInTheDocument();
      expect(screen.getByText('Host CPU Utilization')).toBeInTheDocument();
      expect(screen.getByText('Host Memory Usage')).toBeInTheDocument();
      expect(screen.getByText('Host Disk Capacity')).toBeInTheDocument();
    });

    // Verify system data values are shown
    expect(screen.getByText('16 Cores')).toBeInTheDocument();
    expect(screen.getAllByText('50%')).toHaveLength(2); // memory & disk percent
    expect(screen.getByText('16 GB / 32 GB')).toBeInTheDocument();
    expect(screen.getByText('250 GB / 500 GB')).toBeInTheDocument();

    // Verify worker details are displayed
    expect(screen.getByText('celery@gpu-worker-test')).toBeInTheDocument();
    expect(screen.getByText('8 processes')).toBeInTheDocument();
    expect(screen.getByText('256.5 MB')).toBeInTheDocument();
    expect(screen.getByText('1h 0s')).toBeInTheDocument(); // uptime (3600 seconds = 1 hour)
    expect(screen.getByText('test-task-1')).toBeInTheDocument();
  });

  it('handles API fetch errors gracefully', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ error: 'Database connection failed' }),
    });

    render(<AdminPanel />);
    const workersTabBtn = screen.getByText('Workers & Resources');

    await act(async () => {
      fireEvent.click(workersTabBtn);
    });

    await vi.waitFor(() => {
      expect(screen.getByText('Error retrieving system statistics: Database connection failed')).toBeInTheDocument();
    });
  });

});
