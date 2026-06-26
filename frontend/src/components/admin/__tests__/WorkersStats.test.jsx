import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import WorkersStats from '../WorkersStats';

describe('WorkersStats Component', () => {
  const mockSystemStats = {
    connected_workers_count: 1,
    workers: [
      {
        name: 'celery@gpu-worker-test',
        status: 'online',
        pid: 9999,
        uptime: 3600,
        pool_size: 8,
        total_tasks_processed: 42,
        active_tasks_count: 1,
        reserved_tasks_count: 0,
        active_tasks: [{ id: 'test-task-1', name: 'tasks.evaluate_submission' }],
        reserved_tasks: [],
        registered_tasks: ['tasks.evaluate_submission'],
        rusage: {
          maxrss_mb: 256.5,
          utime_sec: 1.25,
          stime_sec: 0.75,
        },
        broker: {
          transport: 'redis',
          hostname: 'localhost',
          port: 6379,
        },
      },
    ],
    system: {
      cpu_count: 16,
      load_avg: [1.2, 0.95, 0.8],
      memory: {
        total_gb: 32.0,
        used_gb: 16.0,
        free_gb: 16.0,
        percent_used: 50.0,
      },
      disk: {
        total_gb: 500.0,
        used_gb: 250.0,
        free_gb: 250.0,
        percent_used: 50.0,
      },
      os: 'Linux',
      platform_release: '5.15.0',
      python_version: '3.10.5',
    },
  };

  const mockFormatUptime = (sec) => `${sec / 3600}h`;

  it('renders stats correctly when loaded', () => {
    const fetchWorkerStats = vi.fn();

    render(
      <WorkersStats
        workerStats={mockSystemStats}
        workerStatsLoading={false}
        workerStatsError={null}
        fetchWorkerStats={fetchWorkerStats}
        formatUptime={mockFormatUptime}
      />,
    );

    expect(screen.getByText('System Resources & Worker Status')).toBeInTheDocument();
    expect(screen.getByText('Host CPU Utilization')).toBeInTheDocument();
    expect(screen.getByText('16 Cores')).toBeInTheDocument();
    expect(screen.getByText('Host Memory Usage')).toBeInTheDocument();
    expect(screen.getByText('16 GB / 32 GB')).toBeInTheDocument();
    expect(screen.getByText('Host Disk Capacity')).toBeInTheDocument();
    expect(screen.getByText('celery@gpu-worker-test')).toBeInTheDocument();
    expect(screen.getByText('8 processes')).toBeInTheDocument();
  });

  it('shows loading indicator and disables refresh when loading', () => {
    const fetchWorkerStats = vi.fn();

    render(
      <WorkersStats
        workerStats={mockSystemStats}
        workerStatsLoading={true}
        workerStatsError={null}
        fetchWorkerStats={fetchWorkerStats}
        formatUptime={mockFormatUptime}
      />,
    );

    const refreshBtn = screen.getByRole('button', { name: /Refreshing/i });
    expect(refreshBtn).toBeDisabled();
  });

  it('displays error message when error occurs', () => {
    const fetchWorkerStats = vi.fn();

    render(
      <WorkersStats
        workerStats={null}
        workerStatsLoading={false}
        workerStatsError="Network Timeout"
        fetchWorkerStats={fetchWorkerStats}
        formatUptime={mockFormatUptime}
      />,
    );

    expect(screen.getByText(/Network Timeout/i)).toBeInTheDocument();
  });

  it('triggers fetchWorkerStats on refresh button click', () => {
    const fetchWorkerStats = vi.fn();

    render(
      <WorkersStats
        workerStats={mockSystemStats}
        workerStatsLoading={false}
        workerStatsError={null}
        fetchWorkerStats={fetchWorkerStats}
        formatUptime={mockFormatUptime}
      />,
    );

    const refreshBtn = screen.getByRole('button', { name: /Refresh Now/i });
    fireEvent.click(refreshBtn);

    expect(fetchWorkerStats).toHaveBeenCalledTimes(1);
  });
});
