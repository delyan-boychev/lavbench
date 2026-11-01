import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { createTestQueryClient } from '../../../test-utils';
import StageComputePanel from '../StageComputePanel';
import WorkspaceImagePicker from '../WorkspaceImagePicker';

vi.mock('../../../context/AppContext', () => ({
  useApp: vi.fn(),
}));

vi.mock('../../../services/EnvironmentService', () => ({
  default: {
    getStageCompute: vi.fn(),
    getWorkspaceImages: vi.fn(),
    putStageCompute: vi.fn(),
    syncStageCompute: vi.fn(),
    putTaskWorkspacePaths: vi.fn(),
  },
}));

import { useApp } from '../../../context/AppContext';
import EnvironmentService from '../../../services/EnvironmentService';

const DIGEST = `localhost:5050/nanocolab/workspace-python-ml@sha256:${'a'.repeat(64)}`;
const IMAGES = [
  {
    image_id: 'python-ml',
    name: 'Python ML (CPU)',
    description: 'pandas and scikit-learn',
    digest: DIGEST,
    packages: [
      { name: 'python', version: '3.12.7' },
      { name: 'pandas', version: '2.2.3' },
      { name: 'scikit-learn', version: '1.6.1' },
    ],
    default: true,
  },
  {
    image_id: 'python-base',
    name: 'Python (no ML libraries)',
    description: '',
    digest: `localhost:5050/nanocolab/workspace-python-base@sha256:${'b'.repeat(64)}`,
    packages: [],
    default: false,
  },
];

const COMPUTE = {
  stage_id: 'stage-1',
  enabled: true,
  published: false,
  compute_kind: 'CPU',
  cpu_cores: 1,
  memory_gib: 2,
  disk_gib: 10,
  gpu_type: null,
  image_id: '',
  image_digest: '',
  asset_version: 'lb-0123456789ab-v1',
  package_state: 'READY',
  package_error: null,
  task_folders: { 'task-a': 'task1', 'task-b': 'task2' },
  max_attendance: 5,
  retention_days: 1,
  sync_state: 'PENDING',
  readiness: null,
};

const stage = { id: 'stage-1', title: 'Stage 1' };
let showToast;
let confirm;

function renderWithQuery(ui) {
  return render(<QueryClientProvider client={createTestQueryClient()}>{ui}</QueryClientProvider>);
}

const environment = () => screen.getByRole('combobox', { name: 'Environment' });

async function shown(label) {
  await waitFor(() => expect(environment()).toHaveTextContent(label));
}

function renderPanel(compute = COMPUTE) {
  EnvironmentService.getStageCompute.mockResolvedValue({ ok: true, data: compute });
  return renderWithQuery(<StageComputePanel challengeId="c1" stage={stage} tasks={[]} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  showToast = vi.fn();
  confirm = vi.fn().mockResolvedValue(true);
  useApp.mockReturnValue({ showToast, confirm });
  EnvironmentService.getWorkspaceImages.mockResolvedValue({ ok: true, data: { images: IMAGES } });
  EnvironmentService.putStageCompute.mockResolvedValue({ ok: true, data: COMPUTE });
});

describe('StageComputePanel environment choice', () => {
  it('has no free-text image digest field', async () => {
    renderPanel();
    await shown('Python ML (CPU)');
    expect(screen.queryByPlaceholderText(/sha256/)).toBeNull();
    expect(screen.queryByDisplayValue(/sha256/)).toBeNull();
  });

  it('preselects the default environment and saves its ID', async () => {
    renderPanel();
    await shown('Python ML (CPU)');
    fireEvent.click(screen.getByRole('button', { name: /save compute settings/i }));
    await waitFor(() => expect(EnvironmentService.putStageCompute).toHaveBeenCalled());
    const body = EnvironmentService.putStageCompute.mock.calls[0][2];
    expect(body.image_id).toBe('python-ml');
    expect(body).not.toHaveProperty('image_digest');
  });

  it('saves the environment the organiser picks', async () => {
    renderPanel();
    await shown('Python ML (CPU)');
    fireEvent.click(environment());
    fireEvent.click(await screen.findByRole('option', { name: /Python \(no ML libraries\)/ }));
    fireEvent.click(screen.getByRole('button', { name: /save compute settings/i }));
    await waitFor(() => expect(EnvironmentService.putStageCompute).toHaveBeenCalled());
    expect(EnvironmentService.putStageCompute.mock.calls[0][2].image_id).toBe('python-base');
  });

  it('keeps the stored environment instead of the default', async () => {
    renderPanel({ ...COMPUTE, image_id: 'python-base' });
    await shown('Python (no ML libraries)');
    fireEvent.click(screen.getByRole('button', { name: /save compute settings/i }));
    await waitFor(() => expect(EnvironmentService.putStageCompute).toHaveBeenCalled());
    expect(EnvironmentService.putStageCompute.mock.calls[0][2].image_id).toBe('python-base');
  });

  it('asks for confirmation with a title and message before publishing', async () => {
    renderPanel({ ...COMPUTE, image_id: 'python-ml', published: false });
    await shown('Python ML (CPU)');
    fireEvent.click(screen.getByLabelText(/publish/i));
    fireEvent.click(screen.getByRole('button', { name: /save compute settings/i }));
    await waitFor(() => expect(confirm).toHaveBeenCalled());
    expect(confirm.mock.calls[0][0]).toEqual({
      title: 'Publish compute?',
      message: expect.stringContaining('Publishing locks the profile'),
    });
  });

  it('does not save when publishing is cancelled', async () => {
    confirm.mockResolvedValue(false);
    renderPanel({ ...COMPUTE, image_id: 'python-ml' });
    await shown('Python ML (CPU)');
    fireEvent.click(screen.getByLabelText(/publish/i));
    fireEvent.click(screen.getByRole('button', { name: /save compute settings/i }));
    await waitFor(() => expect(confirm).toHaveBeenCalled());
    expect(EnvironmentService.putStageCompute).not.toHaveBeenCalled();
  });

  it('shows an error when the catalogue cannot be loaded', async () => {
    EnvironmentService.getWorkspaceImages.mockResolvedValue({
      ok: false,
      data: { code: 'ERR_COMPUTE_UNAVAILABLE' },
    });
    renderPanel();
    expect(
      await screen.findByText('Could not load the environment list from nano-colab.'),
    ).toBeInTheDocument();
  });

  it('shows the API error when the chosen environment is refused', async () => {
    EnvironmentService.putStageCompute.mockResolvedValue({
      ok: false,
      data: { code: 'ERR_INVALID_WORKSPACE_IMAGE', error: 'Choose an environment from the list.' },
    });
    renderPanel();
    await shown('Python ML (CPU)');
    fireEvent.click(screen.getByRole('button', { name: /save compute settings/i }));
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith('Choose an environment from the list.', 'rose'),
    );
  });
});

describe('StageComputePanel task files', () => {
  it('has no asset version field and sends none', async () => {
    renderPanel();
    await shown('Python ML (CPU)');
    expect(screen.queryByText(/asset version/i)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /save compute settings/i }));
    await waitFor(() => expect(EnvironmentService.putStageCompute).toHaveBeenCalled());
    expect(EnvironmentService.putStageCompute.mock.calls[0][2]).not.toHaveProperty('asset_version');
  });

  it('shows that task files are ready', async () => {
    renderPanel();
    expect(await screen.findByTestId('package-status')).toHaveTextContent(
      'Task files are ready in the notebooks.',
    );
  });

  it('shows the validator message when packaging failed', async () => {
    renderPanel({
      ...COMPUTE,
      package_state: 'FAILED',
      package_error: 'ZIP contains hidden, reserved or unsafe paths.',
    });
    const status = await screen.findByTestId('package-status');
    expect(status).toHaveTextContent('Task files could not be prepared.');
    expect(status).toHaveTextContent('ZIP contains hidden, reserved or unsafe paths.');
  });

  it('translates error codes for an empty stage', async () => {
    renderPanel({ ...COMPUTE, package_state: 'FAILED', package_error: 'ERR_STAGE_PACKAGE_EMPTY' });
    expect(await screen.findByTestId('package-status')).toHaveTextContent(
      'Add a task with files to this stage before enabling the notebook environment.',
    );
  });

  it('polls until the task files are ready', async () => {
    EnvironmentService.getStageCompute
      .mockResolvedValueOnce({
        ok: true,
        data: { ...COMPUTE, sync_state: 'PACKAGING', package_state: 'VALIDATING' },
      })
      .mockResolvedValue({ ok: true, data: { ...COMPUTE, sync_state: 'SYNCED' } });
    renderWithQuery(<StageComputePanel challengeId="c1" stage={stage} tasks={[]} />);
    expect(await screen.findByTestId('package-status')).toHaveTextContent(
      'Preparing task files for the notebooks…',
    );
    await waitFor(
      () =>
        expect(screen.getByTestId('package-status')).toHaveTextContent(
          'Task files are ready in the notebooks.',
        ),
      { timeout: 5000 },
    );
    expect(EnvironmentService.getStageCompute.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it('shows each task folder and uses it in the path hints', async () => {
    EnvironmentService.getStageCompute.mockResolvedValue({ ok: true, data: COMPUTE });
    const tasks = [
      { id: 'task-a', title: 'Regression', stage_id: 'stage-1' },
      { id: 'task-b', title: 'Classification', stage_id: 'stage-1' },
    ];
    renderWithQuery(<StageComputePanel challengeId="c1" stage={stage} tasks={tasks} />);
    expect(await screen.findByText('task2/')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('task2/submission.csv')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('task1/solution.ipynb')).toBeInTheDocument();
  });
});

describe('WorkspaceImagePicker', () => {
  it('lists installed libraries with versions in the info tooltip', () => {
    renderWithQuery(
      <WorkspaceImagePicker
        images={IMAGES}
        loadFailed={false}
        value="python-ml"
        onChange={vi.fn()}
        disabled={false}
      />,
    );
    const info = screen.getByTestId('workspace-image-info');
    expect(info).toHaveAccessibleName('What is installed in Python ML (CPU)');
    const tooltip = screen.getByRole('tooltip', { hidden: true });
    expect(info).toHaveAttribute('aria-describedby', tooltip.id);
    expect(within(tooltip).getByText('pandas')).toBeInTheDocument();
    expect(within(tooltip).getByText('2.2.3')).toBeInTheDocument();
    expect(within(tooltip).getByText('scikit-learn')).toBeInTheDocument();
    expect(within(tooltip).getByText(/sha256:aaaaaaaaaaaa…/)).toBeInTheDocument();
  });

  it('says when an environment has no published library list', () => {
    renderWithQuery(
      <WorkspaceImagePicker
        images={IMAGES}
        loadFailed={false}
        value="python-base"
        onChange={vi.fn()}
        disabled={false}
      />,
    );
    const tooltip = screen.getByRole('tooltip', { hidden: true });
    expect(
      within(tooltip).getByText('No library list was published for this environment.'),
    ).toBeInTheDocument();
  });

  it('keeps showing a retired environment on a published stage', () => {
    renderWithQuery(
      <WorkspaceImagePicker
        images={[IMAGES[1]]}
        loadFailed={false}
        value="python-ml"
        onChange={vi.fn()}
        disabled
      />,
    );
    expect(environment()).toHaveTextContent('python-ml (no longer offered)');
    expect(screen.queryByTestId('workspace-image-info')).toBeNull();
  });

  it('hides the info icon until an environment is chosen', () => {
    renderWithQuery(
      <WorkspaceImagePicker
        images={IMAGES}
        loadFailed={false}
        value=""
        onChange={vi.fn()}
        disabled={false}
      />,
    );
    expect(screen.queryByTestId('workspace-image-info')).toBeNull();
  });
});
