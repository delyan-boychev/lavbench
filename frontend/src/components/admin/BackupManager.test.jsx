import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import BackupManager from './BackupManager';
import api from '../../services/ApiService';

vi.mock('../../services/ApiService', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ ok: true, data: { backups: [] } }),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('../../context/AppContext', () => ({
  useApp: () => ({
    selectedChallenge: { id: 'c1-id', timezone: 'UTC' },
  }),
}));

describe('BackupManager Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.EventSource = class {
      constructor(url) {
        this.url = url;
        this.close = vi.fn();
      }
    };
  });

  it('renders general backup section', async () => {
    api.get.mockResolvedValue({ ok: true, data: { backups: [] } });
    render(<BackupManager />);

    await waitFor(() => {
      expect(screen.getByText('Force Backup Now')).toBeInTheDocument();
    });
  });
});
