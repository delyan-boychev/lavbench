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
  image_name: 'Python ML (CPU)',
  phase: 'unpublished',
  auto_publish_at: null,
};
const PUBLISHED = {
  ...READY,
  id: 'e2',
  stage_id: 's2',
  stage_title: 'Round 2',
  published_at: '2099-04-30T10:00:00+03:00',
  status: { ...STATUS, published: true },
  phase: 'published',
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

  it('shows each stage as a chip, one phase line and the key facts', async () => {
    const { onClose } = renderPanel([READY, PUBLISHED]);
    const first = await card('Round 1');
    expect(within(first).getByText('Ready')).toBeInTheDocument();
    expect(within(first).getByTestId('environment-phase')).toHaveTextContent(
      /^Not published - opens May 1, 2099, 09:00/,
    );
    expect(within(first).getByText('2 vCPU, 8 GiB memory, 13 GiB disk')).toBeInTheDocument();
    expect(within(first).getByText('Python ML (CPU)')).toBeInTheDocument();
    expect(within(first).getByText('12')).toBeInTheDocument();
    expect(within(first).getAllByRole('term')).toHaveLength(5);
    expect(within(first).queryByText('Keep archives until')).not.toBeInTheDocument();
    fireEvent.click(within(first).getByRole('button', { name: 'More options' }));
    expect(within(first).getByText('Keep archives until')).toBeInTheDocument();
    const second = await card('Round 2');
    expect(within(second).getByTestId('environment-phase')).toHaveTextContent(/^Published - opens/);
    expect(useSSEInvalidation).toHaveBeenCalledWith('/api/challenges/c1/environment/live', [
      'environment',
      'c1',
    ]);
    expect(screen.queryByText(/Edit competition/)).not.toBeInTheDocument();
    expect(EnvironmentService.getCatalog).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('offers Edit settings to the admin only', async () => {
    const onEditSettings = vi.fn();
    renderPanel([READY], { onEditSettings });
    await card('Round 1');
    fireEvent.click(screen.getByRole('button', { name: 'Edit settings' }));
    expect(onEditSettings).toHaveBeenCalled();
  });

  it('publishes a ready stage after a specific confirmation and extends a published one', async () => {
    mockConfirm.mockResolvedValue(true);
    EnvironmentService.publish.mockReturnValue(ok({ ...READY, published_at: 'now' }));
    EnvironmentService.extend.mockReturnValue(ok(PUBLISHED));
    renderPanel([READY, { ...PUBLISHED, phase: 'open' }]);
    const first = await card('Round 1');
    expect(within(first).queryByRole('button', { name: 'Extend' })).not.toBeInTheDocument();
    fireEvent.click(within(first).getByRole('button', { name: 'Publish' }));
    await waitFor(() => expect(EnvironmentService.publish).toHaveBeenCalledWith('c1', 'e1'));
    const request = mockConfirm.mock.calls[0][0];
    expect(request.title).toBe('Publish Round 1?');
    expect(request.focusCancel).toBe(true);
    render(request.message);
    expect(screen.getByText(/Settings and task files then lock/)).toBeInTheDocument();
    expect(mockShowToast).toHaveBeenCalledWith('Workspaces published.');

    const second = await card('Round 2');
    expect(within(second).getByTestId('environment-phase')).toHaveTextContent(/^Open - closes/);
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

  it('shows a refused extension reason under its field', async () => {
    EnvironmentService.extend.mockReturnValue(
      Promise.resolve({
        ok: false,
        status: 422,
        data: { code: 'ERR_REASON_REQUIRED', error: 'Give a reason.', field: 'reason' },
      }),
    );
    renderPanel([{ ...PUBLISHED, phase: 'open' }]);
    const second = await card('Round 2');
    fireEvent.click(within(second).getByRole('button', { name: 'Extend' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/Reason/), { target: { value: 'too short' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Extend' }));
    await waitFor(() =>
      expect(within(dialog).getByLabelText(/Reason/)).toHaveAttribute('aria-invalid', 'true'),
    );
  });

  it.each([
    [{ enabled: false, phase: 'off', status: { ...STATUS, state: 'off' } }, 'Workspaces are off'],
    [
      { auto_publish: true, auto_publish_at: '2099-04-30T09:00:00+03:00' },
      /^Publishes automatically on Apr 30, 2099, 09:00/,
    ],
    [{ phase: 'ended' }, /^Ended May 1, 2099, 17:03/],
  ])('says the phase in one line (%#)', async (changes, line) => {
    renderPanel([{ ...READY, ...changes }]);
    const first = await card('Round 1');
    expect(within(first).getByTestId('environment-phase')).toHaveTextContent(line);
  });

  it('shows the jury the status and image name without actions', async () => {
    renderPanel([READY, PUBLISHED], { readOnly: true, onEditSettings: vi.fn() });
    const first = await card('Round 1');
    expect(within(first).getByText('Ready')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Publish/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Extend' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit settings' })).not.toBeInTheDocument();
    expect(within(first).getByText('Python ML (CPU)')).toBeInTheDocument();
  });

  it('falls back to the image id without a name', async () => {
    renderPanel([{ ...READY, image_name: null }], { readOnly: true });
    const first = await card('Round 1');
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
