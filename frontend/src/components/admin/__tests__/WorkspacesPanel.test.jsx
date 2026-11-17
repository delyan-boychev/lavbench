import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { createTestQueryClient } from '../../../test-utils';
import WorkspacesPanel from '../WorkspacesPanel';
import EnvironmentService from '../../../services/EnvironmentService';
import useSSEInvalidation from '../../../hooks/useSSEInvalidation';
import { EnvironmentLiveProvider } from '../../../context/EnvironmentLiveContext';

vi.mock('../../../services/EnvironmentService', () => ({
  default: {
    list: vi.fn(),
    getCatalog: vi.fn(),
    publish: vi.fn(),
    extend: vi.fn(),
    getWorkspaces: vi.fn(),
    liveUrl: (id) => `/api/challenges/${id}/environment/live`,
  },
}));

vi.mock('../../../hooks/useSSEInvalidation', async (importOriginal) => ({
  ...(await importOriginal()),
  default: vi.fn(() => ({ connected: true, refetchInterval: false })),
}));

const mockShowToast = vi.fn();
const mockConfirm = vi.fn();
vi.mock('../../../context/AppContext', () => ({
  useApp: () => ({ showToast: mockShowToast, confirm: mockConfirm }),
}));
vi.mock('../../../context/NotificationsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useNotifications: () => ({ showToast: mockShowToast, confirm: mockConfirm }),
}));

const CHALLENGE = {
  id: 'c1',
  title: 'Spring Cup',
  timezone: 'Europe/Sofia',
  end_time: '2099-05-02T17:00:00+03:00',
  stages: [
    { id: 's1', title: 'Round 1', end_time: '2099-05-01T17:00:00+03:00' },
    { id: 's2', title: 'Round 2', end_time: '2099-05-02T17:00:00+03:00' },
  ],
};
const STATUS = {
  state: 'ready',
  published: false,
  progress: null,
  since: null,
  alert: false,
  code: null,
  message: null,
  limit: null,
  fetched_at: null,
};
const READY = {
  id: 'e1',
  challenge_id: 'c1',
  stage_id: 's1',
  stage_title: 'Round 1',
  enabled: true,
  auto_publish: false,
  published_at: null,
  compute_kind: 'CPU',
  cpu_cores: 2,
  memory_gib: 8,
  workspace_gib: 10,
  data_gib: 3,
  disk_gib: 13,
  gpu_type: null,
  image_id: 'python-ml',
  image_digest: null,
  archive_until: '2099-05-31T17:03:00+03:00',
  max_attendance: 12,
  starts_at: '2099-05-01T09:00:00+03:00',
  ends_at: '2099-05-01T17:03:00+03:00',
  asset_version: null,
  folders: ['image-classification'],
  status: STATUS,
};
const PUBLISHED = {
  ...READY,
  id: 'e2',
  stage_id: 's2',
  stage_title: 'Round 2',
  published_at: '2099-04-30T10:00:00+03:00',
  status: { ...STATUS, published: true },
};

const ok = (data) => Promise.resolve({ ok: true, status: 200, data });

function renderPanel(environments, props = {}) {
  EnvironmentService.list.mockReturnValue(ok({ environments }));
  const onClose = vi.fn();
  const client = createTestQueryClient();
  render(
    <QueryClientProvider client={client}>
      <EnvironmentLiveProvider>
        <WorkspacesPanel challenge={CHALLENGE} readOnly={false} onClose={onClose} {...props} />
      </EnvironmentLiveProvider>
    </QueryClientProvider>,
  );
  return { onClose };
}

const card = async (title) =>
  (await screen.findByRole('heading', { name: title })).closest('[data-testid="environment-card"]');

describe('WorkspacesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    EnvironmentService.getCatalog.mockReturnValue(
      ok({ images: [{ image_id: 'python-ml', name: 'Python ML (CPU)' }], profiles: [] }),
    );
    EnvironmentService.getWorkspaces.mockReturnValue(ok({ workspaces: [] }));
  });

  it('lists each stage with its status, disk and next-step hint, and opens the live stream', async () => {
    const { onClose } = renderPanel([READY, PUBLISHED]);
    const first = await card('Round 1');
    expect(within(first).getByText('Ready')).toBeInTheDocument();
    expect(
      within(first).getByText(
        'Ready. Publish so students can open their workspaces from the start.',
      ),
    ).toBeInTheDocument();
    expect(
      within(first).getByText('10 GiB work space + 3 GiB task data = 13 GiB'),
    ).toBeInTheDocument();
    expect(await within(first).findByText('Python ML (CPU)')).toBeInTheDocument();
    const second = await card('Round 2');
    expect(within(second).getByText(/^Published\. Students can open/)).toBeInTheDocument();
    expect(within(second).getByText(/Extend moves the end later/)).toBeInTheDocument();
    expect(useSSEInvalidation).toHaveBeenCalledWith('/api/challenges/c1/environment/live', [
      'environment',
      'c1',
    ]);
    expect(screen.getByText(/The settings are in Edit competition/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('publishes a ready stage after confirmation and extends a published one', async () => {
    mockConfirm.mockResolvedValue(true);
    EnvironmentService.publish.mockReturnValue(ok({ ...READY, published_at: 'now' }));
    EnvironmentService.extend.mockReturnValue(ok(PUBLISHED));
    renderPanel([READY, PUBLISHED]);
    const first = await card('Round 1');
    expect(within(first).queryByRole('button', { name: 'Extend' })).not.toBeInTheDocument();
    fireEvent.click(within(first).getByRole('button', { name: 'Publish to nanoColab' }));
    await waitFor(() => expect(EnvironmentService.publish).toHaveBeenCalledWith('c1', 'e1'));
    expect(mockConfirm.mock.calls[0][0].title).toBe('Publish to nanoColab?');
    expect(mockShowToast).toHaveBeenCalledWith('Published to nanoColab.');

    const second = await card('Round 2');
    expect(within(second).queryByRole('button', { name: /Publish/ })).not.toBeInTheDocument();
    fireEvent.click(within(second).getByRole('button', { name: 'Extend' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/Reason/), {
      target: { value: 'power cut in room 2' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Extend' }));
    await waitFor(() =>
      expect(EnvironmentService.extend).toHaveBeenCalledWith('c1', 'e2', {
        end_time: '2099-05-02T17:00',
        reason: 'power cut in room 2',
      }),
    );
  });

  it.each([
    [{ enabled: false, status: { ...STATUS, state: 'off' } }, /^Workspaces are off/],
    [{ status: { ...STATUS, state: 'uploading', progress: 40 } }, /^Uploading the task files/],
    [{ status: { ...STATUS, state: 'preparing' } }, /^nanoColab is checking the task files/],
    [{ auto_publish: true }, /^Ready\. It publishes automatically/],
    [{ status: { ...STATUS, state: 'problem' } }, /^Fix the problem shown above/],
    [{ status: { ...STATUS, state: 'unknown' } }, /^The status is out of date/],
  ])('gives the admin a one-line hint for each state (%#)', async (changes, hint) => {
    renderPanel([{ ...READY, ...changes }]);
    const first = await card('Round 1');
    expect(within(first).getByText(hint)).toBeInTheDocument();
  });

  it('shows the jury the status without actions, hints or the catalog', async () => {
    renderPanel([READY, PUBLISHED], { readOnly: true });
    const first = await card('Round 1');
    expect(within(first).getByText('Ready')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Publish/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Extend' })).not.toBeInTheDocument();
    expect(screen.queryByText(/^Ready\. Publish/)).not.toBeInTheDocument();
    expect(EnvironmentService.getCatalog).not.toHaveBeenCalled();
    expect(within(first).getByText('python-ml')).toBeInTheDocument();
  });

  it('names a competition without stages', async () => {
    renderPanel([{ ...READY, stage_id: null, stage_title: null }]);
    expect(await card('Whole competition')).toBeInTheDocument();
  });

  it('offers a retry when the list cannot be loaded', async () => {
    EnvironmentService.list.mockReturnValue(
      Promise.resolve({ ok: false, status: 500, data: { code: 'ERR_INTERNAL' } }),
    );
    const client = createTestQueryClient();
    render(
      <QueryClientProvider client={client}>
        <WorkspacesPanel challenge={CHALLENGE} readOnly={false} onClose={vi.fn()} />
      </QueryClientProvider>,
    );
    // The one retry for server errors waits a second first
    expect(
      await screen.findByRole('button', { name: /Retry|Try again/i }, { timeout: 4000 }),
    ).toBeInTheDocument();
  });
});
