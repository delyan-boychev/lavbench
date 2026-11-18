import React from 'react';
import { screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TaskManager from '../TaskManager';
import { renderWithProviders } from '../../../test-utils';

const { mockUpdate, mockShowToast, mockConfirm, mockSetEmergency, mockDeleteFile, mockUpload } =
  vi.hoisted(() => ({
    mockUpdate: vi.fn(),
    mockShowToast: vi.fn(),
    mockConfirm: vi.fn(),
    mockSetEmergency: vi.fn(),
    mockDeleteFile: vi.fn(),
    mockUpload: vi.fn(),
  }));

vi.mock('../../../context/NotificationsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useNotifications: () => ({ showToast: mockShowToast, confirm: mockConfirm }),
}));

vi.mock('../../../hooks/useTaskMutations', () => ({
  useCreateTask: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateTask: () => ({ mutateAsync: mockUpdate, isPending: false }),
  useSetEmergencyUpload: () => ({ mutateAsync: mockSetEmergency, isPending: false }),
  useRemoveHfZip: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteTaskFile: () => ({ mutateAsync: mockDeleteFile, isPending: false }),
  useInvalidateTaskData: () => vi.fn(),
}));

vi.mock('../../../services/upload', () => ({ uploadWithProgress: mockUpload }));

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

const STAGES = [
  {
    id: 11,
    stage_number: 1,
    title: 'Round one',
    start_time: '2026-11-18T09:00:00Z',
    end_time: '2026-11-19T09:00:00Z',
  },
  {
    id: 12,
    stage_number: 2,
    title: 'Round two',
    start_time: '2026-11-20T09:00:00Z',
    end_time: '2026-11-21T09:00:00Z',
  },
];

const renderEditor = (initialTask = task, isAdmin = false) =>
  renderWithProviders(
    <TaskManager
      mode="edit"
      isAdmin={isAdmin}
      initialTask={initialTask}
      challenges={[{ id: 1, title: 'C', stages: STAGES }]}
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
    mockSetEmergency.mockReset();
    mockDeleteFile.mockReset();
    mockDeleteFile.mockResolvedValue({ ok: true, data: { id: 7, files: [] } });
    mockUpload.mockReset();
    mockUpload.mockResolvedValue({ ok: true, status: 200, data: { id: 8, files: [] } });
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
    expect(formData.get('deleted_files')).toBeNull();
    expect(formData.get('baseline_notebook').name).toBe('new_baseline.ipynb');
    await waitFor(() =>
      expect(mockDeleteFile).toHaveBeenCalledWith({ taskId: 7, filename: 'train.csv', reason: '' }),
    );
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

  it('streams hidden files after the save, and needs no baseline notebook for a file task', async () => {
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
    expect(formData.get('hidden_file_0')).toBeNull();
    expect(formData.get('folder_name')).toBeNull();
    await waitFor(() => expect(mockUpload).toHaveBeenCalledTimes(1));
    expect(mockUpload.mock.calls[0][0]).toBe('/tasks/8/files/extra_labels.csv?visibility=hidden');
    expect(mockUpload.mock.calls[0][1].name).toBe('extra_labels.csv');
  });

  it('saves a file task whose scoring files are missing and shows its readiness problems', async () => {
    mockUpdate.mockResolvedValue({
      ok: true,
      data: { ...fileTask, problem_codes: ['ERR_LABELS_MISSING'] },
    });
    const user = userEvent.setup();
    renderEditor({ ...fileTask, evaluation_mode: 'file', files: [] });
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    expect(mockShowToast).toHaveBeenCalledWith('Task updated successfully!');
  });

  it.each([
    [
      {
        code: 'ERR_LABELS_TOO_LARGE',
        error: 'labels.parquet holds too many ids',
        limit: '512 MB',
        field: 'labels.parquet',
      },
      'labels.parquet holds more ids than a submission can be checked against (512 MB).',
    ],
    [
      { code: 'ERR_INVALID_LABELS_SCHEMA', error: 'Invalid labels.parquet: duplicate ids' },
      'Invalid labels.parquet schema.',
    ],
  ])('shows a refused labels file in its upload row', async (data, text) => {
    mockUpdate.mockResolvedValue({ ok: true, data: fileTask });
    mockUpload.mockResolvedValue({ ok: false, status: 422, data });
    const user = userEvent.setup();
    renderEditor(fileTask);
    await user.click(screen.getByRole('button', { name: /Files/ }));
    const zone = screen.getByTestId('hidden-files');
    await user.upload(zone.querySelector('input[type="file"]'), new File(['x'], 'labels.parquet'));
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    const row = await screen.findByTestId('upload-row-labels.parquet');
    await waitFor(() => expect(row).toHaveTextContent(text));
    expect(row).toHaveTextContent('Failed');
    expect(mockShowToast).toHaveBeenCalledWith(
      'The task is saved, but some files were not uploaded. Retry them in the upload list.',
      'rose',
    );
  });

  it('shows the mode read-only when the server reports it locked', () => {
    renderEditor({ ...fileTask, mode_locked: true });
    const mode = screen.getByRole('combobox', { name: /Evaluation mode/ });
    expect(mode).toBeDisabled();
    expect(
      screen.getByText('Locked: competitors have already submitted to this task.'),
    ).toBeInTheDocument();
  });

  it('still shows a refused mode change under the field', async () => {
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
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  it('fixes the folder and public files of a published task and asks for a reason', async () => {
    const user = userEvent.setup();
    renderEditor({ ...fileTask, folder_name: 'file-task', files_locked: true }, true);
    expect(screen.getByRole('textbox', { name: /Workspace folder/ })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: /Files/ }));
    expect(
      screen.getByText('The workspace environment is published, so these files are fixed.'),
    ).toBeInTheDocument();

    const zone = screen.getByTestId('hidden-files');
    await user.upload(zone.querySelector('input[type="file"]'), new File(['x'], 'labels.parquet'));
    const reason = screen.getByRole('textbox', { name: /Reason for changing hidden files/ });
    expect(reason).toBeRequired();
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));
    expect(mockUpdate).not.toHaveBeenCalled();

    await user.type(reason, 'Corrected two labels');
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    expect(mockUpdate.mock.calls[0][0].formData.get('reason')).toBe('Corrected two labels');
    // The admin's reason goes with the hidden file it covers
    await waitFor(() =>
      expect(mockUpload.mock.calls[0][0]).toBe(
        '/tasks/8/files/labels.parquet?visibility=hidden&reason=Corrected+two+labels',
      ),
    );
  });

  it('turns the emergency upload on with the reason the admin gives', async () => {
    mockConfirm.mockResolvedValue('nanoColab is down');
    mockSetEmergency.mockResolvedValue({ ok: true, data: { emergency_upload_enabled: true } });
    const user = userEvent.setup();
    renderEditor({ ...fileTask, evaluation_mode: 'file' }, true);
    const toggle = screen.getByLabelText('Allow the emergency upload (nanoColab outage)');
    await user.click(toggle);

    await waitFor(() =>
      expect(mockSetEmergency).toHaveBeenCalledWith({
        taskId: 8,
        enabled: true,
        reason: 'nanoColab is down',
      }),
    );
    await waitFor(() => expect(toggle).toBeChecked());
    expect(mockShowToast).toHaveBeenCalledWith('The emergency upload is allowed for this task.');
  });

  it('leaves the emergency upload off when the admin cancels', async () => {
    mockConfirm.mockResolvedValue(null);
    const user = userEvent.setup();
    renderEditor({ ...fileTask, evaluation_mode: 'file' }, true);
    await user.click(screen.getByLabelText('Allow the emergency upload (nanoColab outage)'));
    expect(mockSetEmergency).not.toHaveBeenCalled();
  });

  it('does not turn the emergency upload on without a reason', async () => {
    mockConfirm.mockResolvedValue('   ');
    const user = userEvent.setup();
    renderEditor({ ...fileTask, evaluation_mode: 'file' }, true);
    await user.click(screen.getByLabelText('Allow the emergency upload (nanoColab outage)'));
    expect(mockSetEmergency).not.toHaveBeenCalled();
    expect(mockShowToast).toHaveBeenCalledWith(
      'Give a reason to allow the emergency upload.',
      'rose',
    );
  });

  it('offers the emergency switch only on a stored file task', async () => {
    const user = userEvent.setup();
    renderEditor(fileTask, true);
    await user.click(screen.getByRole('combobox', { name: /Evaluation mode/ }));
    await user.click(screen.getByRole('option', { name: 'File' }));
    expect(screen.queryByLabelText('Allow the emergency upload (nanoColab outage)')).toBeNull();
  });

  it('keeps a published task in its stage, with the reason shown', () => {
    renderEditor({ ...fileTask, stage_id: 11, files_locked: true }, true);
    const stage = screen.getByRole('combobox', { name: /Competition Stage/ });
    expect(stage).toBeDisabled();
    expect(screen.getAllByText('Fixed: the workspace environment is published.').length).toBe(2);
  });

  it('shows a refused stage move under the stage field', async () => {
    mockUpdate.mockResolvedValue({
      ok: false,
      data: { code: 'ERR_TASK_FILES_LOCKED', error: 'locked' },
    });
    const user = userEvent.setup();
    renderEditor({ ...fileTask, stage_id: 11 });
    await user.click(screen.getByRole('combobox', { name: /Competition Stage/ }));
    await user.click(screen.getByRole('option', { name: /Round two/ }));
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    const stage = screen.getByRole('combobox', { name: /Competition Stage/ });
    await waitFor(() => expect(stage).toHaveAttribute('aria-invalid', 'true'));
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  it('shows a refused hidden file name in its upload row after publish', async () => {
    mockUpdate.mockResolvedValue({ ok: true, data: { ...fileTask, files_locked: true } });
    mockUpload.mockResolvedValue({
      ok: false,
      status: 400,
      data: { code: 'ERR_INVALID_FILENAME', error: 'bad name' },
    });
    const user = userEvent.setup();
    renderEditor({ ...fileTask, files_locked: true }, true);
    await user.click(screen.getByRole('button', { name: /Files/ }));
    const zone = screen.getByTestId('hidden-files');
    await user.upload(zone.querySelector('input[type="file"]'), new File(['x'], 'bad name.csv'));
    await user.type(
      screen.getByRole('textbox', { name: /Reason for changing hidden files/ }),
      'Fix',
    );
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));
    const row = await screen.findByTestId('upload-row-bad name.csv');
    await waitFor(() => expect(row).toHaveTextContent('Invalid filename'));
  });

  it('tells the jury why a mode switch on a published task failed', async () => {
    mockUpdate.mockResolvedValue({
      ok: false,
      data: { code: 'ERR_TASK_FILES_LOCKED', error: 'locked' },
    });
    const user = userEvent.setup();
    renderEditor({ ...fileTask, evaluation_mode: 'file', files_locked: true });
    await user.click(screen.getByRole('combobox', { name: /Evaluation mode/ }));
    await user.click(screen.getByRole('option', { name: 'Notebook' }));
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));
    await waitFor(() =>
      expect(mockShowToast).toHaveBeenCalledWith(
        expect.stringMatching(/published|locked/i),
        'rose',
      ),
    );
  });

  it('sends no sandbox fields for a file task, so a stale image cannot block it', async () => {
    const user = userEvent.setup();
    renderEditor({ ...fileTask, evaluation_mode: 'file', base_docker_image: 'Not A Valid Image' });
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    const formData = mockUpdate.mock.calls[0][0].formData;
    expect(formData.get('base_docker_image')).toBeNull();
    expect(formData.get('gpu_required')).toBeNull();
  });

  it('locks the evaluator for the jury after publish', async () => {
    const user = userEvent.setup();
    renderEditor({
      ...fileTask,
      evaluation_mode: 'file',
      files_locked: true,
      evaluator_script_path: 'tasks/8/evaluator.py',
    });
    await user.click(screen.getByRole('button', { name: /Evaluation/ }));
    expect(
      screen.getByText(
        'The workspace environment is published: only an administrator can replace hidden files or the evaluator now.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Remove/ })).toBeNull();
    expect(document.getElementById('evaluator-script-upload')).toBeNull();
  });
});
