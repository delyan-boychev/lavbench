import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import BackupManager from './BackupManager';

describe('BackupManager Component', () => {
  it('renders download backup section correctly', () => {
    const handleDownloadBackup = vi.fn();
    render(<BackupManager handleDownloadBackup={handleDownloadBackup} />);

    expect(screen.getByText('Database Backups & Security')).toBeInTheDocument();
    expect(screen.getByText('Download Postgres DB Backup')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Download Backup Dump File/i })).toBeInTheDocument();
  });

  it('triggers handleDownloadBackup on button click', () => {
    const handleDownloadBackup = vi.fn();
    render(<BackupManager handleDownloadBackup={handleDownloadBackup} />);

    const downloadBtn = screen.getByRole('button', { name: /Download Backup Dump File/i });
    fireEvent.click(downloadBtn);

    expect(handleDownloadBackup).toHaveBeenCalledTimes(1);
  });
});
