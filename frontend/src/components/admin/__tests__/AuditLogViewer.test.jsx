import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../../test-utils';
import AuditLogViewer from '../AuditLogViewer';
import api from '../../../services/ApiService';

vi.mock('../../../services/ApiService', () => ({
  default: {
    get: vi.fn(),
  },
}));

const mockSetSelectedChallengeById = vi.fn();
vi.mock('../../../context/AppContext', () => ({
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

    renderWithProviders(<AuditLogViewer />);

    await waitFor(() => {
      expect(screen.getByText('Audit Logs')).toBeInTheDocument();
      expect(screen.getByText(/total administrative actions logged/)).toHaveTextContent(
        '1 total administrative actions logged',
      );
      expect(screen.getByText(/admin-user/)).toBeInTheDocument();
      expect(screen.getAllByText('Create').length).toBeGreaterThanOrEqual(1);
    });
  });

  it('shows the student as the actor of a workspace launch', async () => {
    api.get.mockResolvedValue({
      ok: true,
      data: {
        logs: [
          {
            id: 'log-2',
            timestamp: '2026-06-24T19:05:00Z',
            admin_username: null,
            admin_id: null,
            action_type: 'launch',
            target_type: 'environment',
            target_id: 'env-1',
            target_user_id: 'u-7',
            target_user_username: 'comp_ivo',
            details: { task_id: 't1' },
          },
          {
            id: 'log-3',
            timestamp: '2026-06-24T19:06:00Z',
            admin_username: null,
            admin_id: null,
            action_type: 'sync',
            target_type: 'environment',
            target_id: 'env-1',
            details: { code: null },
          },
          {
            id: 'log-4',
            timestamp: '2026-06-24T19:07:00Z',
            admin_username: 'jury-user',
            admin_id: 'jury-uuid',
            action_type: 'update',
            target_type: 'user',
            target_user_id: 'u-8',
            target_user_username: 'comp_ana',
            details: {},
          },
        ],
        total: 3,
        pages: 1,
        page: 1,
      },
    });

    renderWithProviders(<AuditLogViewer />);

    expect(await screen.findByText('comp_ivo')).toBeInTheDocument();
    expect(screen.queryByText('Student: comp_ivo')).not.toBeInTheDocument();
    expect(screen.getByText('u-7')).toBeInTheDocument();
    expect(screen.getAllByText('System')).toHaveLength(1);
    expect(screen.getByText('Student: comp_ana')).toBeInTheDocument();
  });

  it('shows the old and new manual points with their decimals', async () => {
    api.get.mockResolvedValue({
      ok: true,
      data: {
        logs: [
          {
            id: 'log-5',
            timestamp: '2026-06-24T19:08:00Z',
            admin_username: 'jury-user',
            admin_id: 'jury-uuid',
            action_type: 'update',
            target_type: 'user',
            target_user_id: 'u-8',
            target_user_username: 'comp_ana',
            task_id: 't1',
            task_title: 'Sentiment',
            old_score: 7,
            new_score: 7.25,
            details: null,
          },
          {
            id: 'log-6',
            timestamp: '2026-06-24T19:09:00Z',
            admin_username: 'jury-user',
            admin_id: 'jury-uuid',
            action_type: 'update',
            target_type: 'user',
            target_user_id: 'u-9',
            task_id: 't2',
            old_score: null,
            new_score: 12.5,
            details: null,
          },
        ],
        total: 2,
        pages: 1,
        page: 1,
      },
    });

    renderWithProviders(<AuditLogViewer />);

    expect(await screen.findByText('Points for Sentiment: 7 → 7.25')).toBeInTheDocument();
    expect(screen.getByText('Points for t2: — → 12.5')).toBeInTheDocument();
  });
});
