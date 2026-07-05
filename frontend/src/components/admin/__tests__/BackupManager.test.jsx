import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

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

vi.mock('../../../context/AppContext', () => ({
  useApp: () => ({
    selectedChallenge: { id: 'c1-id', timezone: 'UTC' },
  }),
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

  it('renders database backups title without challengeId', async () => {
    api.get.mockResolvedValue({ ok: true, data: { backups: [] } });
    render(<BackupManager />);
    await act(async () => {});
    expect(screen.getByText('Database Backups & Security')).toBeInTheDocument();
  });

  it('shows force backup button', async () => {
    api.get.mockResolvedValue({ ok: true, data: { backups: [] } });
    render(<BackupManager />);
    await act(async () => {});
    expect(screen.getByText('Force Backup Now')).toBeInTheDocument();
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
    expect(api.post).toHaveBeenCalledWith('/admin/backups/force');
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
    expect(openSpy).toHaveBeenCalledWith(
      '/api/admin/backups/backup.db/download',
      '_blank',
      'noopener,noreferrer',
    );
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
    await act(async () => {});
    await waitFor(() => {
      expect(screen.getByText('✕')).toBeInTheDocument();
    });
    await act(async () => {
      fireEvent.click(screen.getByText('✕'));
    });
    expect(api.delete).toHaveBeenCalledWith('/admin/backups/manual_backup.db');
  });
});
