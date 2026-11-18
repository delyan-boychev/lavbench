import React from 'react';
import { screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TaskManager from '../TaskManager';
import { renderWithProviders } from '../../../test-utils';

const { mockUpdate, mockShowToast, mockConfirm, mockPut } = vi.hoisted(() => ({
  mockUpdate: vi.fn(),
  mockShowToast: vi.fn(),
  mockConfirm: vi.fn(),
  mockPut: vi.fn(),
}));

vi.mock('../../../context/NotificationsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useNotifications: () => ({ showToast: mockShowToast, confirm: mockConfirm }),
}));

vi.mock('../../../services/ApiService', async (importOriginal) => {
  const actual = /** @type {any} */ (await importOriginal());
  return { default: { ...actual.default, put: mockPut } };
});

vi.mock('../../../hooks/useTaskMutations', () => ({
  useCreateTask: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateTask: () => ({ mutateAsync: mockUpdate, isPending: false }),
}));

const task = {
  id: 7,
  title: 'Task',
  challenge_id: 1,
  baseline_notebook_path: 'tasks/7/baseline.ipynb',
  files: [
    { filename: 'baseline.ipynb', type: 'baseline', size_bytes: 100 },
    { filename: 'labels.parquet', type: 'data', size_bytes: 100 },
    { filename: 'train.csv', type: 'data', size_bytes: 100 },
  ],
};

const fileTask = {
  id: 8,
  title: 'File task',
  challenge_id: 1,
  evaluation_mode: 'notebook',
  emergency_upload_enabled: false,
  baseline_notebook_path: 'tasks/8/baseline.ipynb',
  files: [
    { filename: 'labels.parquet', size_bytes: 100, visibility: 'hidden' },
    { filename: 'baseline_submission.parquet', size_bytes: 100, visibility: 'hidden' },
  ],
};

const renderEditor = (initialTask = task, isAdmin = false) =>
  renderWithProviders(
    <TaskManager
      mode="edit"
      isAdmin={isAdmin}
      initialTask={initialTask}
      challenges={[{ id: 1, title: 'C', stages: [] }]}
      selectedChallenge={{ id: 1, title: 'C' }}
      availableMetrics={{}}
      onClose={vi.fn()}
    />,
  );

describe('TaskManager file deletions', () => {
  beforeEach(() => {
    mockUpdate.mockReset();
    mockUpdate.mockResolvedValue({ ok: true, data: {} });
    mockShowToast.mockReset();
    mockConfirm.mockReset();
    mockPut.mockReset();
  });

  it('sends a removed data file and a replaced baseline', async () => {
    const user = userEvent.setup();
    renderEditor();
    await user.click(screen.getByRole('button', { name: /Files/ }));

    const row = screen.getByTestId('existing-file-train.csv');
    await user.click(within(row).getByRole('button', { name: 'Delete' }));

    const notebook = new File(['{}'], 'new_baseline.ipynb', { type: 'application/json' });
    const input = document.querySelector('input[type="file"]');
    await user.upload(input, notebook);

    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    const formData = mockUpdate.mock.calls[0][0].formData;
    expect(JSON.parse(formData.get('deleted_files'))).toEqual(['train.csv']);
    expect(formData.get('baseline_notebook').name).toBe('new_baseline.ipynb');
  });

  it('keeps a deleted baseline from saving without a replacement', async () => {
    const user = userEvent.setup();
    renderEditor();
    await user.click(screen.getByRole('button', { name: /Files/ }));

    const baselineRow = screen.getByText('baseline.ipynb').closest('div.flex.items-center');
    await user.click(within(baselineRow.parentElement).getByRole('button', { name: 'Delete' }));
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    expect(await screen.findByText('Baseline notebook is required.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Files/ })).toHaveAttribute('aria-pressed', 'true');
    expect(mockUpdate).not.toHaveBeenCalled();
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  it('sends hidden files and the mode, and needs no baseline notebook for a file task', async () => {
    const user = userEvent.setup();
    renderEditor({ ...fileTask, evaluation_mode: 'file', baseline_notebook_path: null });
    await user.click(screen.getByRole('button', { name: /Files/ }));
    const hidden = new File(['x'], 'extra_labels.csv');
    const zone = screen.getByTestId('hidden-files');
    await user.upload(zone.querySelector('input[type="file"]'), hidden);
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    const formData = mockUpdate.mock.calls[0][0].formData;
    expect(formData.get('evaluation_mode')).toBe('file');
    expect(formData.get('hidden_file_0').name).toBe('extra_labels.csv');
    expect(formData.get('folder_name')).toBeNull();
  });

  it('asks for baseline_submission.parquet before saving a file task', async () => {
    const user = userEvent.setup();
    renderEditor({ ...fileTask, evaluation_mode: 'file', files: [fileTask.files[0]] });
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));
    expect(
      await screen.findByText(
        'A file task needs baseline_submission.parquet among the hidden files.',
      ),
    ).toBeInTheDocument();
    expect(mockUpdate).not.toHaveBeenCalled();
  });

  it('locks the mode when the server refuses the change', async () => {
    mockUpdate.mockResolvedValue({
      ok: false,
      data: {
        code: 'ERR_TASK_MODE_LOCKED',
        error: 'The evaluation mode cannot change once a competitor has submitted.',
      },
    });
    const user = userEvent.setup();
    renderEditor(fileTask);
    await user.click(screen.getByRole('combobox', { name: /Evaluation mode/ }));
    await user.click(screen.getByRole('option', { name: 'File' }));
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    expect(
      await screen.findByText('The evaluation mode cannot change once a competitor has submitted.'),
    ).toBeInTheDocument();
    const mode = screen.getByRole('combobox', { name: /Evaluation mode/ });
    expect(mode).toBeDisabled();
    expect(mode).toHaveTextContent('Notebook');
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  it('turns the emergency upload on with the reason the admin gives', async () => {
    mockConfirm.mockResolvedValue('nanoColab is down');
    mockPut.mockResolvedValue({ ok: true, status: 200, data: { emergency_upload_enabled: true } });
    const user = userEvent.setup();
    renderEditor({ ...fileTask, evaluation_mode: 'file' }, true);
    const toggle = screen.getByLabelText('Allow direct uploads (nanoColab outage)');
    await user.click(toggle);

    await waitFor(() =>
      expect(mockPut).toHaveBeenCalledWith('/tasks/8/emergency-upload', {
        enabled: true,
        reason: 'nanoColab is down',
      }),
    );
    await waitFor(() => expect(toggle).toBeChecked());
    expect(mockShowToast).toHaveBeenCalledWith('Direct uploads are allowed for this task.');
  });

  it('leaves the emergency upload off when the admin cancels', async () => {
    mockConfirm.mockResolvedValue(null);
    const user = userEvent.setup();
    renderEditor({ ...fileTask, evaluation_mode: 'file' }, true);
    await user.click(screen.getByLabelText('Allow direct uploads (nanoColab outage)'));
    expect(mockPut).not.toHaveBeenCalled();
  });
});
