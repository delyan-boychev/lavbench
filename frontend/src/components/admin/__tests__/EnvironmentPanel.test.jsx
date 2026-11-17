import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { createTestQueryClient } from '../../../test-utils';
import EnvironmentPanel from '../EnvironmentPanel';
import EnvironmentService from '../../../services/EnvironmentService';
import { environmentKeys } from '../../../hooks/useEnvironmentQuery';
import useSSEInvalidation from '../../../hooks/useSSEInvalidation';
import { EnvironmentLiveProvider } from '../../../context/EnvironmentLiveContext';

vi.mock('../../../services/EnvironmentService', () => ({
  default: {
    get: vi.fn(),
    save: vi.fn(),
    getImages: vi.fn(),
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
  timezone: 'Europe/Sofia',
  end_time: '2027-05-02T17:00:00+03:00',
};
const STAGE = { id: 's1', end_time: '2027-05-01T17:00:00+03:00' };
const STATUS = {
  state: 'off',
  published: false,
  progress: null,
  since: null,
  alert: false,
  code: null,
  message: null,
  limit: null,
  fetched_at: null,
};
const OFF = {
  id: null,
  challenge_id: 'c1',
  stage_id: 's1',
  enabled: false,
  auto_publish: false,
  published_at: null,
  compute_kind: 'CPU',
  cpu_cores: 2,
  memory_gib: 8,
  disk_gib: 10,
  gpu_type: null,
  image_id: '',
  image_digest: null,
  archive_until: '2027-05-31T17:03:00+03:00',
  max_attendance: 12,
  starts_at: '2027-05-01T09:00:00+03:00',
  ends_at: '2027-05-01T17:03:00+03:00',
  asset_version: null,
  folders: ['image-classification', null],
  status: STATUS,
};
const ENABLED = {
  ...OFF,
  id: 'e1',
  enabled: true,
  image_id: 'python-ml',
  status: { ...STATUS, state: 'preparing' },
};
const READY = { ...ENABLED, status: { ...STATUS, state: 'ready' } };
const PUBLISHED = {
  ...READY,
  published_at: '2027-04-30T10:00:00+03:00',
  status: { ...STATUS, state: 'ready', published: true },
};
const IMAGES = [
  { image_id: 'python-ml', name: 'Python ML (CPU)', packages: [], default: true },
  { image_id: 'python-base', name: 'Python', packages: [], default: false },
];

const ok = (data) => Promise.resolve({ ok: true, status: 200, data });

function renderPanel(environment, props = {}) {
  EnvironmentService.get.mockReturnValue(ok(environment));
  const client = createTestQueryClient();
  const utils = render(
    <QueryClientProvider client={client}>
      <EnvironmentLiveProvider>
        <EnvironmentPanel challenge={CHALLENGE} stage={STAGE} {...props} />
      </EnvironmentLiveProvider>
    </QueryClientProvider>,
  );
  return { ...utils, client };
}

describe('EnvironmentPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    EnvironmentService.getImages.mockReturnValue(ok({ images: IMAGES }));
    EnvironmentService.getWorkspaces.mockReturnValue(ok({ workspaces: [] }));
  });

  it('renders nothing while nanoColab is off', async () => {
    EnvironmentService.get.mockReturnValue(
      Promise.resolve({ ok: false, status: 404, data: { code: 'ERR_NANOCOLAB_DISABLED' } }),
    );
    const client = createTestQueryClient();
    const { container } = render(
      <QueryClientProvider client={client}>
        <EnvironmentPanel challenge={CHALLENGE} stage={STAGE} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(EnvironmentService.get).toHaveBeenCalledWith('c1', 's1'));
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it('enables the environment with its defaults and one Save', async () => {
    renderPanel(OFF);
    const save = await screen.findByRole('button', { name: 'Save environment' });
    expect(save).toBeDisabled();
    expect(screen.getByText('Off')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Give students a workspace'));
    await screen.findAllByText('Python ML (CPU)');
    EnvironmentService.save.mockReturnValue(ok({ ...ENABLED, image_id: 'python-ml' }));
    fireEvent.click(save);

    await waitFor(() =>
      expect(EnvironmentService.save).toHaveBeenCalledWith('c1', 's1', {
        enabled: true,
        auto_publish: false,
        compute_kind: 'CPU',
        cpu_cores: 2,
        memory_gib: 8,
        disk_gib: 10,
        gpu_type: null,
        image_id: 'python-ml',
      }),
    );
    expect(mockShowToast).toHaveBeenCalledWith(
      'Environment saved. The workspaces are being prepared.',
    );
  });

  it('sends the archive date and the GPU type only when the admin sets them', async () => {
    renderPanel(ENABLED);
    const archive = await screen.findByLabelText(/Keep archives until/);
    expect(archive).toHaveValue('2027-05-31T17:03');
    fireEvent.change(archive, { target: { value: '2027-06-15T12:00' } });
    fireEvent.click(screen.getByLabelText('GPU workspaces'));
    fireEvent.change(screen.getByLabelText(/GPU type/), { target: { value: 'nvidia-l4' } });
    EnvironmentService.save.mockReturnValue(ok(ENABLED));
    fireEvent.click(screen.getByRole('button', { name: 'Save environment' }));

    await waitFor(() => expect(EnvironmentService.save).toHaveBeenCalled());
    const body = EnvironmentService.save.mock.calls[0][2];
    expect(body.archive_until).toBe('2027-06-15T12:00');
    expect(body.compute_kind).toBe('GPU');
    expect(body.gpu_type).toBe('nvidia-l4');
  });

  it('keeps unsaved edits when the status refreshes', async () => {
    const { client } = renderPanel(ENABLED);
    const cores = await screen.findByLabelText(/CPU cores/);
    fireEvent.change(cores, { target: { value: '4' } });

    act(() => {
      client.setQueryData(environmentKeys.owner('c1', 's1'), READY);
    });

    expect(await screen.findByText('Ready')).toBeInTheDocument();
    expect(screen.getByLabelText(/CPU cores/)).toHaveValue(4);
    expect(screen.getByText('Save your changes before publishing.')).toBeInTheDocument();
  });

  it('publishes only once ready, after a confirmation', async () => {
    const { client } = renderPanel(ENABLED);
    const publish = await screen.findByRole('button', { name: 'Publish to nanoColab' });
    expect(publish).toBeDisabled();
    expect(screen.getByText('You can publish once the status is Ready.')).toBeInTheDocument();

    act(() => {
      client.setQueryData(environmentKeys.owner('c1', 's1'), READY);
    });
    await waitFor(() => expect(publish).toBeEnabled());

    mockConfirm.mockResolvedValueOnce(false);
    fireEvent.click(publish);
    await waitFor(() => expect(mockConfirm).toHaveBeenCalledTimes(1));
    expect(EnvironmentService.publish).not.toHaveBeenCalled();

    mockConfirm.mockResolvedValueOnce(true);
    EnvironmentService.publish.mockReturnValue(ok(PUBLISHED));
    fireEvent.click(publish);
    await waitFor(() => expect(EnvironmentService.publish).toHaveBeenCalledWith('c1', 'e1'));
    expect(mockConfirm.mock.calls[1][0].title).toBe('Publish to nanoColab?');
    await waitFor(() => expect(mockShowToast).toHaveBeenCalledWith('Published to nanoColab.'));
    expect(screen.queryByRole('button', { name: 'Save environment' })).not.toBeInTheDocument();
  });

  it('shows a translated error with its limit when publishing fails', async () => {
    renderPanel(READY);
    mockConfirm.mockResolvedValueOnce(true);
    EnvironmentService.publish.mockReturnValue(
      Promise.resolve({
        ok: false,
        status: 413,
        data: { code: 'ERR_ENVIRONMENT_PACKAGE_TOO_LARGE', error: 'too large', limit: '2 GiB' },
      }),
    );
    fireEvent.click(await screen.findByRole('button', { name: 'Publish to nanoColab' }));
    await waitFor(() =>
      expect(mockShowToast).toHaveBeenCalledWith(
        'The environment package is too large (limit 2 GiB).',
        'rose',
      ),
    );
  });

  it('locks a published environment and extends it with a reason', async () => {
    const onExtended = vi.fn();
    renderPanel(PUBLISHED, { onExtended });
    expect(await screen.findByText(/A published environment is locked/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Give students a workspace')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save environment' })).not.toBeInTheDocument();
    expect(screen.getByText('2 vCPU, 8 GiB memory, 10 GiB disk')).toBeInTheDocument();
    expect(screen.getByText('image-classification/')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Extend' }));
    const dialog = await screen.findByRole('dialog');
    expect(screen.getByLabelText(/New end/)).toHaveValue('2027-05-01T17:00');
    fireEvent.change(screen.getByLabelText(/New end/), { target: { value: '2027-05-01T18:00' } });
    fireEvent.change(screen.getByLabelText(/Reason/), {
      target: { value: '  Power cut at the venue  ' },
    });
    EnvironmentService.extend.mockReturnValue(ok(PUBLISHED));
    fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() =>
      expect(EnvironmentService.extend).toHaveBeenCalledWith('c1', 'e1', {
        end_time: '2027-05-01T18:00',
        reason: 'Power cut at the venue',
      }),
    );
    await waitFor(() => expect(mockShowToast).toHaveBeenCalledWith('The end was moved.'));
    expect(onExtended).toHaveBeenCalledWith('2027-05-01T18:00');
  });

  it('shows the jury the status and settings without any action', async () => {
    renderPanel(PUBLISHED, { readOnly: true });
    expect(await screen.findByText('Ready')).toBeInTheDocument();
    expect(screen.getByText('python-ml')).toBeInTheDocument();
    for (const name of ['Save environment', 'Publish to nanoColab', 'Extend']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByText(/A published environment is locked/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show student workspaces' })).toBeInTheDocument();
    expect(EnvironmentService.getImages).not.toHaveBeenCalled();
  });

  it('shows the jury nothing when the environment is off', async () => {
    const { container } = renderPanel(OFF, { readOnly: true });
    await waitFor(() => expect(EnvironmentService.get).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it('reports unsaved edits to the view that holds it', async () => {
    const onDirtyChange = vi.fn();
    renderPanel(ENABLED, { onDirtyChange });
    fireEvent.change(await screen.findByLabelText(/CPU cores/), { target: { value: '4' } });
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
    fireEvent.change(screen.getByLabelText(/CPU cores/), { target: { value: '2' } });
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false));
  });

  it('keeps listening while hidden from the jury, so an enabled environment shows up', async () => {
    const { client, container } = renderPanel(OFF, { readOnly: true });
    await waitFor(() =>
      expect(useSSEInvalidation).toHaveBeenCalledWith(
        '/api/challenges/c1/environment/live',
        environmentKeys.challenge('c1'),
      ),
    );
    expect(container).toBeEmptyDOMElement();
    act(() => {
      client.setQueryData(environmentKeys.owner('c1', 's1'), PUBLISHED);
    });
    expect(await screen.findByText('Ready')).toBeInTheDocument();
  });

  it('opens no stream while nanoColab is off', async () => {
    EnvironmentService.get.mockReturnValue(
      Promise.resolve({ ok: false, status: 404, data: { code: 'ERR_NANOCOLAB_DISABLED' } }),
    );
    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <EnvironmentLiveProvider>
          <EnvironmentPanel challenge={CHALLENGE} stage={STAGE} />
        </EnvironmentLiveProvider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(EnvironmentService.get).toHaveBeenCalled());
    await act(async () => {});
    expect(useSSEInvalidation).not.toHaveBeenCalled();
  });
});
