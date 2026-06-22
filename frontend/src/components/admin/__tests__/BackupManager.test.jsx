import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

class MockEventSource {
  constructor(url) {
    this.url = url;
    this.onmessage = null;
    this.onerror = null;
  }
  close() {}
}

vi.stubGlobal('EventSource', MockEventSource);

vi.mock('../../../services/ApiService', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('../../ui/Button', () => ({
  default: ({ children, variant, onClick, disabled, size }) => (
    <button data-variant={variant} data-size={size} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
}));

vi.mock('../../ui/EmptyState', () => ({
  default: ({ message }) => <div data-testid="empty-state">{message}</div>,
}));

import api from '../../../services/ApiService';
import BackupManager from '../BackupManager';

describe('BackupManager', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders loading state initially', () => {
    api.get.mockReturnValue(new Promise(() => {}));
    render(<BackupManager />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('renders empty state when no backups', async () => {
    api.get.mockResolvedValue({ ok: true, data: { backups: [] } });
    render(<BackupManager />);
    await waitFor(() => {
      expect(screen.getByText('No backups found.')).toBeInTheDocument();
    });
  });

  it('renders database backups title without challengeId', () => {
    api.get.mockResolvedValue({ ok: true, data: { backups: [] } });
    render(<BackupManager />);
    expect(screen.getByText('Database Backups & Security')).toBeInTheDocument();
  });

  it('renders competition backups title with challengeId', () => {
    api.get.mockResolvedValue({ ok: true, data: { backups: [] } });
    render(<BackupManager challengeId={42} />);
    expect(screen.getByText('Competition Backups')).toBeInTheDocument();
  });

  it('shows force backup button only without challengeId', () => {
    api.get.mockResolvedValue({ ok: true, data: { backups: [] } });
    render(<BackupManager />);
    expect(screen.getByText('Force Backup Now')).toBeInTheDocument();
  });

  it('hides force backup button with challengeId', () => {
    api.get.mockResolvedValue({ ok: true, data: { backups: [] } });
    render(<BackupManager challengeId={42} />);
    expect(screen.queryByText('Force Backup Now')).not.toBeInTheDocument();
  });

  it('renders backup list items', async () => {
    api.get.mockResolvedValue({
      ok: true,
      data: {
        backups: [
          {
            filename: 'backup_2024_01.db',
            size_mb: 12.5,
            created_at: '2024-01-15T10:00:00Z',
            type: 'manual',
          },
        ],
      },
    });
    render(<BackupManager />);
    await waitFor(() => {
      expect(screen.getByText('backup_2024_01.db')).toBeInTheDocument();
    });
  });

  it('calls handleForce when force button clicked', async () => {
    api.get.mockResolvedValue({ ok: true, data: { backups: [] } });
    api.post.mockResolvedValue({ ok: true, data: {} });
    render(<BackupManager />);
    await waitFor(() => {
      expect(screen.getByText('Force Backup Now')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Force Backup Now'));
    expect(api.post).toHaveBeenCalledWith('/api/admin/backups/force');
  });

  it('calls download when download button clicked', async () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => {});
    api.get.mockResolvedValue({
      ok: true,
      data: {
        backups: [
          { filename: 'backup.db', size_mb: 5, created_at: '2024-01-01T00:00:00Z', type: 'manual' },
        ],
      },
    });
    render(<BackupManager />);
    await waitFor(() => {
      expect(screen.getByText('Download')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Download'));
    expect(openSpy).toHaveBeenCalledWith('/api/admin/backups/backup.db/download', '_blank');
    openSpy.mockRestore();
  });

  it('calls delete when delete button clicked for manual backup', async () => {
    api.get.mockResolvedValue({
      ok: true,
      data: {
        backups: [
          {
            filename: 'manual_backup.db',
            size_mb: 3,
            created_at: '2024-01-01T00:00:00Z',
            type: 'manual',
          },
        ],
      },
    });
    api.delete.mockResolvedValue({ ok: true, data: {} });
    render(<BackupManager />);
    await waitFor(() => {
      expect(screen.getByText('✕')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('✕'));
    expect(api.delete).toHaveBeenCalledWith('/api/admin/backups/manual_backup.db');
  });

  it('shows state label for submission_ended backups', async () => {
    api.get.mockResolvedValue({
      ok: true,
      data: {
        backups: [
          {
            filename: 'submission_ended_backup.db',
            size_mb: 1,
            created_at: '2024-01-01T00:00:00Z',
            type: 'auto',
          },
        ],
      },
    });
    render(<BackupManager />);
    await waitFor(() => {
      expect(screen.getByText('Submission Period Ended')).toBeInTheDocument();
    });
  });

  it('shows state label for grace_ended backups', async () => {
    api.get.mockResolvedValue({
      ok: true,
      data: {
        backups: [
          {
            filename: 'grace_ended_backup.db',
            size_mb: 1,
            created_at: '2024-01-01T00:00:00Z',
            type: 'auto',
          },
        ],
      },
    });
    render(<BackupManager />);
    await waitFor(() => {
      expect(screen.getByText('Grace Period Ended')).toBeInTheDocument();
    });
  });

  it('shows state label for finalized backups', async () => {
    api.get.mockResolvedValue({
      ok: true,
      data: {
        backups: [
          {
            filename: 'finalized_backup.db',
            size_mb: 1,
            created_at: '2024-01-01T00:00:00Z',
            type: 'auto',
          },
        ],
      },
    });
    render(<BackupManager />);
    await waitFor(() => {
      expect(screen.getByText('Scores Finalized')).toBeInTheDocument();
    });
  });
});
