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

const { mockUpdateChallenge } = vi.hoisted(() => ({ mockUpdateChallenge: vi.fn() }));

vi.mock('../../../hooks/useChallengeMutations', () => {
  const mutation = () => ({ mutateAsync: vi.fn(), isPending: false });
  return {
    useUpdateChallenge: () => ({ mutateAsync: mockUpdateChallenge, isPending: false }),
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

const catalogState = vi.hoisted(() => ({ isError: false, error: null, data: {} }));
vi.mock('../../../hooks/useEnvironmentQuery', async (importOriginal) => ({
  ...(await importOriginal()),
  useWorkspaceCatalogQuery: () => catalogState,
  useEnvironmentsQuery: () => ({ data: [] }),
}));

vi.mock('../WorkspaceSettingsSection', () => ({
  default: ({ draft, onChange, errors }) => (
    <div
      data-testid="workspace-settings"
      data-draft={JSON.stringify(draft)}
      data-errors={JSON.stringify(errors)}
    >
      <button type="button" onClick={() => onChange({ ...draft, workspace_gib: 30 })}>
        resize work space
      </button>
    </div>
  ),
}));

vi.mock('../WorkspacesPanel', () => ({
  default: ({ challenge, readOnly, onClose }) => (
    <div
      data-testid="workspaces-panel"
      data-challenge={challenge.id}
      data-readonly={String(readOnly)}
    >
      <button type="button" onClick={onClose}>
        close workspaces
      </button>
    </div>
  ),
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

  describe('student workspaces', () => {
    const setting = {
      enabled: true,
      auto_publish: false,
      image_id: 'python-ml',
      profile_id: 'cpu-compact',
      cpu_cores: 2,
      memory_gib: 8,
      workspace_gib: 10,
      archive_until: null,
    };
    const withWorkspaces = { ...challenge, workspace: setting };

    // The jsdom time zone list may lack UTC, so submit past the browser's required check
    const saveCompetition = () =>
      fireEvent.submit(screen.getByRole('button', { name: 'Save Changes' }).closest('form'));

    function renderWith(role, item = withWorkspaces) {
      useApp.mockReturnValue({ showToast: vi.fn(), confirm: vi.fn(), selectedChallenge: item });
      useAdminChallengesQuery.mockReturnValue({ data: { items: [item], total: 1, pages: 1 } });
      return renderAs(role);
    }

    it.each([
      ['admin', 'false'],
      ['jury', 'true'],
    ])('opens the Workspaces view from the card for the %s', (role, readOnly) => {
      const { header } = renderWith(role);
      fireEvent.click(within(header).getByRole('button', { name: 'Workspaces' }));
      const panel = screen.getByTestId('workspaces-panel');
      expect(panel).toHaveAttribute('data-challenge', 'c1');
      expect(panel).toHaveAttribute('data-readonly', readOnly);
      fireEvent.click(screen.getByRole('button', { name: 'close workspaces' }));
      expect(screen.queryByTestId('workspaces-panel')).not.toBeInTheDocument();
    });

    it('offers no Workspaces view before a setting exists', () => {
      const { header } = renderWith('admin', challenge);
      expect(within(header).queryByRole('button', { name: 'Workspaces' })).not.toBeInTheDocument();
    });

    it('edits the setting in the competition form and saves it with the form', async () => {
      mockUpdateChallenge.mockResolvedValue({ ok: true });
      const { header } = renderWith('admin');
      fireEvent.click(within(header).getByRole('button', { name: 'Edit' }));
      const section = screen.getByTestId('workspace-settings');
      expect(JSON.parse(section.getAttribute('data-draft'))).toMatchObject({
        enabled: true,
        image_id: 'python-ml',
        profile_id: 'cpu-compact',
        workspace_gib: 10,
      });
      fireEvent.click(screen.getByRole('button', { name: 'resize work space' }));
      saveCompetition();
      await waitFor(() => expect(mockUpdateChallenge).toHaveBeenCalledTimes(1));
      expect(mockUpdateChallenge.mock.calls[0][0].workspace).toEqual({
        enabled: true,
        image_id: 'python-ml',
        profile_id: 'cpu-compact',
        workspace_gib: 30,
        auto_publish: false,
        archive_until: null,
      });
    });

    it('shows a refused value under its field and keeps the form open', async () => {
      mockUpdateChallenge.mockRejectedValue({
        code: 'ERR_INVALID_WORKSPACE_PROFILE',
        error: 'Profile must be one of: CPU Compact, CPU Standard.',
        field: 'workspace.profile_id',
        allowed: 'CPU Compact, CPU Standard',
      });
      const { header } = renderWith('admin');
      fireEvent.click(within(header).getByRole('button', { name: 'Edit' }));
      saveCompetition();
      await waitFor(() =>
        expect(screen.getByTestId('workspace-settings')).toHaveAttribute(
          'data-errors',
          JSON.stringify({ profile_id: 'Profile must be one of: CPU Compact, CPU Standard.' }),
        ),
      );
    });

    it('sends no workspace section when the platform has no workspaces', async () => {
      catalogState.data = { available: false, images: [], profiles: [] };
      mockUpdateChallenge.mockResolvedValue({ ok: true });
      const { header } = renderWith('admin');
      fireEvent.click(within(header).getByRole('button', { name: 'Edit' }));
      saveCompetition();
      await waitFor(() => expect(mockUpdateChallenge).toHaveBeenCalledTimes(1));
      expect(mockUpdateChallenge.mock.calls[0][0]).not.toHaveProperty('workspace');
    });

    it('keeps the stage form to stage fields and points to the competition setting', async () => {
      const { stageRow } = renderWith('admin');
      fireEvent.click(within(stageRow).getByRole('button', { name: 'Edit' }));
      expect(
        await screen.findByText(/come from the competition's Student workspaces/),
      ).toBeVisible();
      expect(screen.queryByTestId('workspace-settings')).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: "Open the competition's settings" }));
      expect(screen.getByTestId('workspace-settings')).toBeInTheDocument();
      expect(screen.queryByLabelText(/Stage Title/i)).not.toBeInTheDocument();
    });

    it('closes the stage form without asking anything', async () => {
      const confirm = vi.fn();
      useApp.mockReturnValue({ showToast: vi.fn(), confirm, selectedChallenge: withWorkspaces });
      useAdminChallengesQuery.mockReturnValue({
        data: { items: [withWorkspaces], total: 1, pages: 1 },
      });
      const { stageRow } = renderAs('admin');
      fireEvent.click(within(stageRow).getByRole('button', { name: 'Edit' }));
      fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
      expect(screen.queryByText(/come from the competition's/)).not.toBeInTheDocument();
      expect(confirm).not.toHaveBeenCalled();
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
      await screen.findByLabelText(/End Time/i);
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
  });
});
