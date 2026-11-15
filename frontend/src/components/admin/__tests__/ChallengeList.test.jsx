import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import { renderWithProviders } from '../../../test-utils';
import { useAuth } from '../../../AuthContext';
import { useApp } from '../../../context/AppContext';
import { useAdminChallengesQuery } from '../../../hooks/useAdminChallengesQuery';
import ChallengeList from '../ChallengeList';

vi.mock('../../../AuthContext', () => ({
  useAuth: vi.fn(),
}));

vi.mock('../../../context/AppContext', () => ({
  useApp: vi.fn(),
}));

vi.mock('../../../hooks/useAdminChallengesQuery', () => ({
  useAdminChallengesQuery: vi.fn(),
}));

vi.mock('../../../hooks/useChallengeMutations', () => {
  const mutation = () => ({ mutateAsync: vi.fn(), isPending: false });
  return {
    useUpdateChallenge: mutation,
    useDeleteChallenge: mutation,
    useFinalizeChallenge: mutation,
    useToggleRevealChallenge: mutation,
    useArchiveToggle: mutation,
    useExportChallenge: mutation,
    useImportChallenge: mutation,
  };
});

vi.mock('../../../hooks/useStageMutations', () => {
  const mutation = () => ({ mutateAsync: vi.fn(), isPending: false });
  return {
    useCreateStage: mutation,
    useUpdateStage: mutation,
    useDeleteStage: mutation,
    useFinalizeStage: mutation,
    useToggleRevealStage: mutation,
  };
});

vi.mock('../../../hooks/useTaskMutations', () => ({
  useDeleteTask: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('../../../services/ApiService', () => ({
  default: { fetch: vi.fn(), get: vi.fn() },
}));

vi.mock('../../../services/ChallengeService', () => ({
  default: { downloadAuditLogs: vi.fn() },
}));

// A finalised, ended challenge with one task and one finalised stage shows every action
const challenge = {
  id: 'c1',
  title: 'Challenge A',
  description: 'Desc',
  start_time: '2026-01-01T00:00:00Z',
  end_time: '2026-02-01T00:00:00Z',
  timezone: 'UTC',
  scores_finalized: true,
  reveal_results: false,
  is_archived: false,
  tasks: [{ id: 't1', title: 'Task 1', public_eval_percentage: 30 }],
  stages: [
    {
      id: 's1',
      title: 'Stage 1',
      stage_number: 1,
      start_time: '2026-01-01T00:00:00Z',
      end_time: '2026-01-15T00:00:00Z',
      is_finalized: true,
      reveal_results: false,
    },
  ],
};

function renderAs(role) {
  useAuth.mockReturnValue({ currentUser: { id: 1, role } });
  renderWithProviders(<ChallengeList onAddTask={vi.fn()} onEditTask={vi.fn()} />);
  // The competition header holds the title and the challenge-level actions
  const header = screen.getByRole('heading', { name: /Challenge A/ }).parentElement.parentElement;
  const taskRow = screen.getByText('Task 1').closest('.rounded-xl');
  const stageRow = screen.getByText(/Stage 1/).closest('.rounded-xl');
  return { header, taskRow, stageRow };
}

describe('ChallengeList role-based actions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useApp.mockReturnValue({
      showToast: vi.fn(),
      confirm: vi.fn(),
      selectedChallenge: challenge,
    });
    useAdminChallengesQuery.mockReturnValue({
      data: { items: [challenge], total: 1, pages: 1 },
    });
  });

  it('hides import, edit, delete and the audit download from the jury', () => {
    const { header, taskRow, stageRow } = renderAs('jury');

    // Admin-only routes: POST /challenges/import, PUT and DELETE /challenges/<id>,
    // GET /challenges/<id>/audit-logs/download
    expect(screen.queryByRole('button', { name: 'Import Challenge' })).not.toBeInTheDocument();
    expect(within(header).queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    expect(within(header).queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
    expect(within(header).queryByRole('button', { name: 'Audits (JSON)' })).not.toBeInTheDocument();

    // Routes the jury may call stay visible
    for (const name of ['Archive', 'Scores (CSV)', 'Submissions (ZIP)', 'Reveal', 'Export']) {
      expect(within(header).getByRole('button', { name })).toBeInTheDocument();
    }
    expect(screen.getAllByRole('button', { name: 'Add Task' })).toHaveLength(2);
    expect(within(taskRow).getByRole('button', { name: 'Edit Config' })).toBeInTheDocument();
    expect(within(taskRow).getByRole('button', { name: 'Delete' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add Stage' })).toBeInTheDocument();
    for (const name of ['Edit', 'Reveal', 'Download', 'Delete']) {
      expect(within(stageRow).getByRole('button', { name })).toBeInTheDocument();
    }
  });

  it('shows the admin every challenge action', () => {
    const { header, taskRow, stageRow } = renderAs('admin');

    expect(screen.getByRole('button', { name: 'Import Challenge' })).toBeInTheDocument();
    for (const name of [
      'Edit',
      'Archive',
      'Scores (CSV)',
      'Submissions (ZIP)',
      'Audits (JSON)',
      'Reveal',
      'Export',
      'Delete',
    ]) {
      expect(within(header).getByRole('button', { name })).toBeInTheDocument();
    }
    expect(within(taskRow).getByRole('button', { name: 'Edit Config' })).toBeInTheDocument();
    expect(within(taskRow).getByRole('button', { name: 'Delete' })).toBeInTheDocument();
    expect(within(stageRow).getByRole('button', { name: 'Edit' })).toBeInTheDocument();
    expect(within(stageRow).getByRole('button', { name: 'Delete' })).toBeInTheDocument();
  });

  describe('finalize buttons (jury-only routes)', () => {
    // Ended, with an ended stage, nothing finalised yet: Finalize is due for both
    const pending = {
      ...challenge,
      scores_finalized: false,
      stages: [{ ...challenge.stages[0], is_finalized: false }],
    };

    beforeEach(() => {
      useAdminChallengesQuery.mockReturnValue({
        data: { items: [pending], total: 1, pages: 1 },
      });
    });

    it('shows the jury the stage and challenge Finalize buttons', () => {
      const { header, stageRow } = renderAs('jury');
      expect(within(header).getByRole('button', { name: 'Finalize' })).toBeInTheDocument();
      expect(within(stageRow).getByRole('button', { name: 'Finalize' })).toBeInTheDocument();
    });

    it('hides both Finalize buttons from the admin', () => {
      renderAs('admin');
      expect(screen.queryByRole('button', { name: 'Finalize' })).not.toBeInTheDocument();
    });
  });
});
