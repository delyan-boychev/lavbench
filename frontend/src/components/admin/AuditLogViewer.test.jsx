import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import AuditLogViewer from './AuditLogViewer';
import api from '../../services/ApiService';

vi.mock('../../services/ApiService', () => ({
  default: {
    get: vi.fn(),
  },
}));

const mockSetSelectedChallengeById = vi.fn();
vi.mock('../../context/AppContext', () => ({
  useApp: () => ({
    challenges: [
      { id: 'c1-id', title: 'Challenge One', timezone: 'Europe/Sofia' },
      { id: 'c2-id', title: 'Challenge Two', timezone: 'UTC' },
    ],
    selectedChallenge: { id: 'c1-id', title: 'Challenge One', timezone: 'Europe/Sofia' },
    setSelectedChallengeById: mockSetSelectedChallengeById,
  }),
}));

describe('AuditLogViewer Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders filter controls and fetches audit logs on mount', async () => {
    api.get.mockImplementation((url) => {
      if (url.includes('/admin/audit-logs')) {
        return Promise.resolve({
          ok: true,
          data: {
            logs: [
              {
                id: 'log-1',
                timestamp: '2026-06-24T19:00:00Z',
                admin_username: 'admin-user',
                admin_id: 'admin-uuid',
                action_type: 'create',
                target_type: 'challenge',
                target_id: 'c1-id',
                ip_address: '127.0.0.1',
                details: { title: 'Challenge One' },
              },
            ],
            total: 1,
            pages: 1,
            page: 1,
          },
        });
      }
      return Promise.resolve({ ok: false });
    });

    render(<AuditLogViewer />);

    await waitFor(() => {
      expect(screen.getByText('Audit Logs')).toBeInTheDocument();
      expect(screen.getByText(/total administrative actions logged/)).toHaveTextContent(
        '1 total administrative actions logged',
      );
      expect(screen.getByText(/admin-user/)).toBeInTheDocument();
      expect(screen.getAllByText('Create').length).toBeGreaterThanOrEqual(1);
    });
  });
});
