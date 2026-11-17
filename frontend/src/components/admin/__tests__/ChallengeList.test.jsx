import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
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

const { mockUpdateStage } = vi.hoisted(() => ({ mockUpdateStage: vi.fn() }));

vi.mock('../../../hooks/useStageMutations', () => {
  const mutation = () => ({ mutateAsync: vi.fn(), isPending: false });
  return {
    useCreateStage: mutation,
    useUpdateStage: () => ({ mutateAsync: mockUpdateStage, isPending: false }),
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

vi.mock('../EnvironmentPanel', async () => {
  const { useState } = await import('react');
  return {
    default: function MockPanel({ challenge, stage, readOnly, onDirtyChange, onExtended }) {
      const [touched, setTouched] = useState(false);
      return (
        <div
          data-testid="environment-panel"
          data-challenge={challenge.id}
          data-stage={stage?.id || ''}
          data-readonly={String(Boolean(readOnly))}
          data-timezone={challenge.timezone || ''}
          data-touched={String(touched)}
        >
          <button
            type="button"
            onClick={() => {
              setTouched(true);
              onDirtyChange?.(true);
            }}
          >
            {`edit environment ${stage?.id || challenge.id}`}
          </button>
          <button type="button" onClick={() => onExtended?.('2026-01-16T09:30')}>
            {`extend environment ${stage?.id || challenge.id}`}
          </button>
        </div>
      );
    },
  };
});

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

  describe('environment section', () => {
    const noStages = { ...challenge, id: 'c2', title: 'Challenge B', stages: [] };

    it('puts the stage environment into the stage settings, read-only for the jury', async () => {
      const { stageRow } = renderAs('jury');
      expect(screen.queryByTestId('environment-panel')).not.toBeInTheDocument();
      fireEvent.click(within(stageRow).getByRole('button', { name: 'Edit' }));
      const panel = await screen.findByTestId('environment-panel');
      expect(panel).toHaveAttribute('data-stage', 's1');
      expect(panel).toHaveAttribute('data-readonly', 'true');
    });

    it('lets the admin edit the stage environment', async () => {
      const { stageRow } = renderAs('admin');
      fireEvent.click(within(stageRow).getByRole('button', { name: 'Edit' }));
      expect(await screen.findByTestId('environment-panel')).toHaveAttribute(
        'data-readonly',
        'false',
      );
    });

    it('puts a competition environment into the competition settings when it has no stages', () => {
      useAdminChallengesQuery.mockReturnValue({
        data: { items: [noStages], total: 1, pages: 1 },
      });
      useAuth.mockReturnValue({ currentUser: { id: 1, role: 'admin' } });
      renderWithProviders(<ChallengeList onAddTask={vi.fn()} onEditTask={vi.fn()} />);
      expect(screen.queryByTestId('environment-panel')).not.toBeInTheDocument();
      fireEvent.click(screen.getAllByRole('button', { name: 'Edit' })[0]);
      const panel = screen.getByTestId('environment-panel');
      expect(panel).toHaveAttribute('data-challenge', 'c2');
      expect(panel).toHaveAttribute('data-stage', '');
    });

    it('shows the jury a competition environment read-only on the competition card', () => {
      useAdminChallengesQuery.mockReturnValue({
        data: { items: [noStages], total: 1, pages: 1 },
      });
      useAuth.mockReturnValue({ currentUser: { id: 1, role: 'jury' } });
      renderWithProviders(<ChallengeList onAddTask={vi.fn()} onEditTask={vi.fn()} />);
      expect(screen.getByTestId('environment-panel')).toHaveAttribute('data-readonly', 'true');
    });

    it('keeps the competition-level panel off a competition with stages', () => {
      renderAs('jury');
      expect(screen.queryByTestId('environment-panel')).not.toBeInTheDocument();
    });
  });

  describe('unsaved environment changes', () => {
    const noStages = { ...challenge, id: 'c2', title: 'Challenge B', stages: [] };

    async function openStage(confirm) {
      useApp.mockReturnValue({ showToast: vi.fn(), confirm, selectedChallenge: challenge });
      const { stageRow } = renderAs('admin');
      fireEvent.click(within(stageRow).getByRole('button', { name: 'Edit' }));
      await screen.findByTestId('environment-panel');
    }

    it('closes the stage settings without asking when nothing is unsaved', async () => {
      const confirm = vi.fn();
      await openStage(confirm);
      fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
      await waitFor(() =>
        expect(screen.queryByTestId('environment-panel')).not.toBeInTheDocument(),
      );
      expect(confirm).not.toHaveBeenCalled();
    });

    it('asks before Cancel discards them, and stays open when the admin declines', async () => {
      const confirm = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
      await openStage(confirm);
      fireEvent.click(screen.getByRole('button', { name: /^edit environment/ }));

      fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
      await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
      expect(confirm.mock.calls[0][0].title).toBe('Discard unsaved environment changes?');
      expect(screen.getByTestId('environment-panel')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
      await waitFor(() =>
        expect(screen.queryByTestId('environment-panel')).not.toBeInTheDocument(),
      );
    });

    it('saves the stage but keeps the view open when the admin keeps the changes', async () => {
      mockUpdateStage.mockResolvedValue({ ok: true });
      const confirm = vi.fn().mockResolvedValue(false);
      await openStage(confirm);
      fireEvent.click(screen.getByRole('button', { name: /^edit environment/ }));
      fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));
      await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
      expect(mockUpdateStage).toHaveBeenCalled();
      expect(screen.getByTestId('environment-panel')).toBeInTheDocument();
    });

    it('asks before closing the competition settings too', async () => {
      const confirm = vi.fn().mockResolvedValue(false);
      useApp.mockReturnValue({ showToast: vi.fn(), confirm, selectedChallenge: noStages });
      useAdminChallengesQuery.mockReturnValue({
        data: { items: [noStages], total: 1, pages: 1 },
      });
      useAuth.mockReturnValue({ currentUser: { id: 1, role: 'admin' } });
      renderWithProviders(<ChallengeList onAddTask={vi.fn()} onEditTask={vi.fn()} />);
      fireEvent.click(screen.getAllByRole('button', { name: 'Edit' })[0]);
      fireEvent.click(screen.getByRole('button', { name: /^edit environment/ }));
      fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
      await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
      expect(screen.getByTestId('environment-panel')).toBeInTheDocument();
    });
  });

  describe('stage and competition times', () => {
    // Stored times carry seconds that the minute-precision inputs drop
    const withSeconds = {
      ...challenge,
      timezone: 'Europe/Sofia',
      stages: [
        {
          ...challenge.stages[0],
          start_time: '2026-01-01T02:00:15+02:00',
          end_time: '2026-01-15T02:00:45+02:00',
        },
        {
          ...challenge.stages[0],
          id: 's2',
          title: 'Stage 2',
          stage_number: 2,
          start_time: '2026-01-16T02:00:00+02:00',
          end_time: '2026-01-20T02:00:00+02:00',
        },
      ],
    };
    const noStages = { ...challenge, id: 'c2', title: 'Challenge B', stages: [] };

    async function openStage(name = 'Stage 1', confirm = vi.fn().mockResolvedValue(true)) {
      useApp.mockReturnValue({ showToast: vi.fn(), confirm, selectedChallenge: withSeconds });
      useAdminChallengesQuery.mockReturnValue({
        data: { items: [withSeconds, noStages], total: 2, pages: 1 },
      });
      useAuth.mockReturnValue({ currentUser: { id: 1, role: 'admin' } });
      const utils = renderWithProviders(<ChallengeList onAddTask={vi.fn()} onEditTask={vi.fn()} />);
      const row = screen.getByText(new RegExp(name)).closest('.rounded-xl');
      fireEvent.click(within(row).getByRole('button', { name: 'Edit' }));
      await screen.findByTestId('environment-panel');
      return { ...utils, confirm };
    }

    it('saves a stage without its unchanged times, even when they carry seconds', async () => {
      mockUpdateStage.mockResolvedValue({ ok: true });
      await openStage();
      fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));
      await waitFor(() => expect(mockUpdateStage).toHaveBeenCalledTimes(1));
      const body = mockUpdateStage.mock.calls[0][0];
      expect(body).not.toHaveProperty('start_time');
      expect(body).not.toHaveProperty('end_time');
    });

    it('sends a time the admin changed', async () => {
      mockUpdateStage.mockResolvedValue({ ok: true });
      await openStage();
      fireEvent.change(screen.getByLabelText(/End Time/i), {
        target: { value: '2026-01-15T03:00' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));
      await waitFor(() => expect(mockUpdateStage).toHaveBeenCalledTimes(1));
      expect(mockUpdateStage.mock.calls[0][0].end_time).toBe('2026-01-15T03:00');
      expect(mockUpdateStage.mock.calls[0][0]).not.toHaveProperty('start_time');
    });

    it('takes the extended end into the open stage form', async () => {
      mockUpdateStage.mockResolvedValue({ ok: true });
      await openStage();
      fireEvent.click(screen.getByRole('button', { name: 'extend environment s1' }));
      expect(screen.getByLabelText(/End Time/i)).toHaveValue('2026-01-16T09:30');
      fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));
      await waitFor(() => expect(mockUpdateStage).toHaveBeenCalledTimes(1));
      expect(mockUpdateStage.mock.calls[0][0].end_time).toBe('2026-01-16T09:30');
    });

    it('starts a fresh environment section for another stage', async () => {
      const { confirm } = await openStage();
      fireEvent.click(screen.getByRole('button', { name: 'edit environment s1' }));
      expect(screen.getByTestId('environment-panel')).toHaveAttribute('data-touched', 'true');
      const row = screen.getByText(/Stage 2/).closest('.rounded-xl');
      fireEvent.click(within(row).getByRole('button', { name: 'Edit' }));
      await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
      await waitFor(() =>
        expect(screen.getByTestId('environment-panel')).toHaveAttribute('data-stage', 's2'),
      );
      expect(screen.getByTestId('environment-panel')).toHaveAttribute('data-touched', 'false');
    });

    it('keeps the competition time zone when the competition leaves the list page', async () => {
      const { rerender } = await openStage();
      useAdminChallengesQuery.mockReturnValue({
        data: { items: [noStages], total: 2, pages: 1 },
      });
      rerender(<ChallengeList onAddTask={vi.fn()} onEditTask={vi.fn()} />);
      expect(screen.getByTestId('environment-panel')).toHaveAttribute(
        'data-timezone',
        'Europe/Sofia',
      );
    });

    it('asks only for the section whose view is closing', async () => {
      const { confirm } = await openStage('Stage 1', vi.fn().mockResolvedValue(false));
      fireEvent.click(screen.getByRole('button', { name: 'edit environment s1' }));
      fireEvent.click(
        within(screen.getByText('Challenge B').closest('.rounded-2xl')).getByRole('button', {
          name: 'Edit',
        }),
      );
      await screen.findByRole('button', { name: 'edit environment c2' });
      fireEvent.click(screen.getAllByRole('button', { name: 'Cancel' })[0]);
      await waitFor(() =>
        expect(
          screen.queryByRole('button', { name: 'edit environment c2' }),
        ).not.toBeInTheDocument(),
      );
      expect(confirm).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
      await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    });
  });
});
