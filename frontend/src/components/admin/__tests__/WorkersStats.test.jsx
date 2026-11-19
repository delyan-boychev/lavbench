import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, within, act } from '@testing-library/react';
import { renderWithProviders } from '../../../test-utils';
import WorkersStats from '../WorkersStats';
import api from '../../../services/ApiService';

vi.mock('../../../services/ApiService', () => ({
  default: { get: vi.fn() },
}));

const STATUS = {
  status: 'partial_outage',
  components: { api: 'operational', scoring: 'partial_outage' },
  queues: [
    { name: 'evaluation_cpu', consumers: 2, queued: 5 },
    { name: 'evaluation_gpu', consumers: 0, queued: 3 },
  ],
  workers: [
    {
      name: 'celery@cpu-1',
      type: 'cpu',
      queues: ['evaluation_cpu', 'system'],
      online: true,
      last_seen: '2026-11-14T10:00:00Z',
      concurrency: 4,
      cpu_cores: 8,
      ram_gb: 15.6,
      gpu_type: null,
      vram_gb: null,
    },
    {
      name: 'celery@gpu-1',
      type: 'gpu',
      queues: ['evaluation_gpu'],
      online: false,
      last_seen: '2026-11-14T09:57:12Z',
      concurrency: null,
      cpu_cores: null,
      ram_gb: null,
      gpu_type: 'NVIDIA L4',
      vram_gb: 24,
    },
  ],
  submissions: {
    queued: 8,
    running: 2,
    oldest_queued_seconds: 125,
    completed_last_15m: 30,
    failed_last_15m: 4,
  },
  updated_at: '2026-11-14T10:00:12Z',
};

function countFor(label) {
  return screen.getByText(label, { selector: 'dt' }).nextElementSibling;
}

describe('WorkersStats', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockResolvedValue({ ok: true, status: 200, data: STATUS });
  });

  it('requests the system status', async () => {
    renderWithProviders(<WorkersStats />);
    await screen.findByText('celery@cpu-1');
    expect(api.get).toHaveBeenCalledWith(
      '/admin/system-status',
      expect.objectContaining({ signal: expect.anything() }),
    );
  });

  it('shows a loading indicator until the first response', async () => {
    api.get.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<WorkersStats />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading...');
  });

  it('shows the overall and per-component status as text badges', async () => {
    renderWithProviders(<WorkersStats />);
    await screen.findByText('celery@cpu-1');
    expect(countFor('Overall')).toHaveTextContent('Partial outage');
    expect(countFor('API')).toHaveTextContent('Operational');
    expect(countFor('Scoring')).toHaveTextContent('Partial outage');
    expect(screen.getByText('Updated 10:00:12 UTC')).toBeInTheDocument();
  });

  it('shows the submission counts and the oldest queued age', async () => {
    renderWithProviders(<WorkersStats />);
    await screen.findByText('celery@cpu-1');
    expect(countFor('Queued')).toHaveTextContent('8');
    expect(countFor('Running')).toHaveTextContent('2');
    expect(countFor('Oldest queued')).toHaveTextContent('2 min');
    expect(countFor('Completed (15 min)')).toHaveTextContent('30');
    expect(countFor('Failed (15 min)')).toHaveTextContent('4');
  });

  it('says when nothing is queued', async () => {
    api.get.mockResolvedValue({
      ok: true,
      status: 200,
      data: { ...STATUS, submissions: { ...STATUS.submissions, oldest_queued_seconds: null } },
    });
    renderWithProviders(<WorkersStats />);
    await screen.findByText('celery@cpu-1');
    expect(countFor('Oldest queued')).toHaveTextContent('None queued');
  });

  it('lists the broker queues in a captioned table', async () => {
    renderWithProviders(<WorkersStats />);
    const table = await screen.findByRole('table', { name: 'Broker queues' });
    const rows = within(table).getAllByRole('row');
    expect(
      within(rows[0])
        .getAllByRole('columnheader')
        .map((h) => h.textContent),
    ).toEqual(['Queue', 'Consumers', 'Queued']);
    expect(
      within(rows[2])
        .getAllByRole('cell')
        .map((c) => c.textContent),
    ).toEqual(['evaluation_gpu', '0', '3']);
  });

  it('lists the workers with status, heartbeat age and resources', async () => {
    renderWithProviders(<WorkersStats />);
    const table = await screen.findByRole('table', { name: 'Workers' });
    const [, cpuRow, gpuRow] = within(table).getAllByRole('row');

    const cpu = within(cpuRow)
      .getAllByRole('cell')
      .map((c) => c.textContent);
    expect(cpu).toEqual([
      'celery@cpu-1',
      'cpu',
      'evaluation_cpu, system',
      'Online',
      '12 seconds ago',
      '4',
      '8',
      '15.6 GB',
      'None',
    ]);

    const gpu = within(gpuRow)
      .getAllByRole('cell')
      .map((c) => c.textContent);
    expect(gpu).toEqual([
      'celery@gpu-1',
      'gpu',
      'evaluation_gpu',
      'Stale',
      '3 minutes ago',
      'N/A',
      'N/A',
      'N/A',
      'NVIDIA L4 (24 GB)',
    ]);

    const lastSeen = within(gpuRow).getByText('3 minutes ago');
    expect(lastSeen.tagName).toBe('TIME');
    expect(lastSeen).toHaveAttribute('dateTime', '2026-11-14T09:57:12Z');
    expect(lastSeen).toHaveAttribute('title', expect.stringContaining('(UTC)'));
  });

  it('shows empty rows when there are no queues or workers', async () => {
    api.get.mockResolvedValue({
      ok: true,
      status: 200,
      data: { ...STATUS, queues: [], workers: [] },
    });
    renderWithProviders(<WorkersStats />);
    expect(await screen.findByText('No queues reported.')).toBeInTheDocument();
    expect(
      screen.getByText(
        'No worker has sent a heartbeat. Submissions wait in the queue until one does.',
      ),
    ).toBeInTheDocument();
  });

  it('shows the translated API error with a retry button', async () => {
    api.get.mockResolvedValue({
      ok: false,
      status: 403,
      data: { code: 'ERR_ACCESS_DENIED', error: 'Access denied' },
    });
    renderWithProviders(<WorkersStats />);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Access denied. You do not have the required permissions.',
    );

    api.get.mockResolvedValue({ ok: true, status: 200, data: STATUS });
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Retry' })));
    expect(await screen.findByText('celery@cpu-1')).toBeInTheDocument();
  });

  it('keeps the last data and flags a failed refresh', async () => {
    renderWithProviders(<WorkersStats />);
    await screen.findByText('celery@cpu-1');

    api.get.mockResolvedValue({ ok: false, status: 503, data: null });
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Refresh Now' })));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not refresh. Showing the status from 10:00:12 UTC.',
    );
    expect(screen.getByText('celery@cpu-1')).toBeInTheDocument();
  });

  it('does not show the removed host resources block', async () => {
    renderWithProviders(<WorkersStats />);
    await screen.findByText('celery@cpu-1');
    expect(screen.queryByText(/Host CPU|Host Memory|Host Disk/)).not.toBeInTheDocument();
  });

  it('flags a worker on other queue priorities as needing an update', async () => {
    const outdated = { ...STATUS.workers[0], name: 'celery@old', priority_steps_match: false };
    api.get.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        ...STATUS,
        workers: [{ ...STATUS.workers[0], priority_steps_match: true }, outdated],
      },
    });
    renderWithProviders(<WorkersStats />);
    const row = (await screen.findByText('celery@old')).closest('tr');
    expect(within(row).getByText('Update needed')).toBeInTheDocument();
    expect(screen.getAllByText('Update needed')).toHaveLength(1);
  });
});
