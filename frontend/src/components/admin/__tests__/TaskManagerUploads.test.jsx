import React from 'react';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TaskManager from '../TaskManager';
import { renderWithProviders } from '../../../test-utils';

const { mockCreate, mockUpdate, mockRemove, mockUpload, mockShowToast, mockConfirm } = vi.hoisted(
  () => ({
    mockCreate: vi.fn(),
    mockUpdate: vi.fn(),
    mockRemove: vi.fn(),
    mockUpload: vi.fn(),
    mockShowToast: vi.fn(),
    mockConfirm: vi.fn(),
  }),
);

vi.mock('../../../context/NotificationsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useNotifications: () => ({ showToast: mockShowToast, confirm: mockConfirm }),
}));

vi.mock('../../../hooks/useTaskMutations', () => ({
  useCreateTask: () => ({ mutateAsync: mockCreate, isPending: false }),
  useUpdateTask: () => ({ mutateAsync: mockUpdate, isPending: false }),
  useSetEmergencyUpload: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useInvalidateTaskData: () => vi.fn(),
}));

vi.mock('../../../services/upload', () => ({
  uploadWithProgress: mockUpload,
  removeAt: mockRemove,
}));

const SHA = 'ab'.repeat(32);
const saved = {
  id: 't9',
  title: 'Sentiment',
  challenge_id: 1,
  evaluation_mode: 'notebook',
  baseline_notebook_path: 'tasks/t9/baseline.ipynb',
  files: [{ filename: 'baseline.ipynb', type: 'baseline', size_bytes: 100 }],
  hf_folders: [],
};
const withHf = {
  ...saved,
  hf_folders: ['models/demo-org/tiny-model'],
  hf_unpacked_bytes: 2048,
  hf_file_count: 3,
  hf_zip_sha256: SHA,
  hf_skipped_count: 0,
};
const zip = () => new File(['PK'], 'hf-data.zip', { type: 'application/zip' });
const ok = (data) => ({ ok: true, status: 200, data, res: { headers: { get: () => null } } });

/** Each upload waits until the test settles it. */
let pending = [];
function holdUploads() {
  mockUpload.mockImplementation(
    (path, _body, options) =>
      new Promise((resolve, reject) => {
        pending.push({ path, options, resolve, reject });
        options.signal?.addEventListener('abort', () =>
          reject(new DOMException('cancelled', 'AbortError')),
        );
      }),
  );
}

function renderManager({ mode = 'edit', task = saved, onClose = vi.fn(), isAdmin = true } = {}) {
  renderWithProviders(
    <TaskManager
      mode={mode}
      isAdmin={isAdmin}
      initialTask={mode === 'edit' ? task : undefined}
      challenges={[{ id: 1, title: 'C', stages: [] }]}
      selectedChallenge={{ id: 1, title: 'C' }}
      availableMetrics={{}}
      onClose={onClose}
    />,
  );
  return onClose;
}

const tab = (user, name) => user.click(screen.getByRole('button', { name: new RegExp(name) }));
const zoneInput = (testId) => screen.getByTestId(testId).querySelector('input[type="file"]');

describe('TaskManager upload list', () => {
  beforeEach(() => {
    pending = [];
    [mockCreate, mockUpdate, mockRemove, mockUpload, mockShowToast, mockConfirm].forEach((mock) =>
      mock.mockReset(),
    );
    mockCreate.mockResolvedValue({ ok: true, data: saved });
    mockUpdate.mockResolvedValue({ ok: true, data: saved });
    mockUpload.mockResolvedValue(ok(saved));
  });

  it('creates the task with its notebook, then streams the data files and the ZIP in order', async () => {
    const user = userEvent.setup();
    const onClose = renderManager({ mode: 'create' });
    await user.type(screen.getByRole('textbox', { name: /Task Title/ }), 'Sentiment');
    await tab(user, 'Files');
    await user.upload(zoneInput('public-files'), [
      new File(['{}'], 'baseline.ipynb'),
      new File(['a'], 'train.csv'),
    ]);
    await user.upload(zoneInput('hidden-files'), new File(['l'], 'labels.parquet'));
    await tab(user, 'Environment');
    await user.upload(zoneInput('hf-data'), zip());
    await user.click(screen.getByRole('button', { name: 'Create Task' }));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    const formData = mockCreate.mock.calls[0][0].formData;
    expect(formData.get('baseline_notebook').name).toBe('baseline.ipynb');
    expect([...formData.keys()].filter((k) => /^(hidden_)?file_/.test(k))).toEqual([]);

    await waitFor(() => expect(mockUpload).toHaveBeenCalledTimes(3));
    expect(mockUpload.mock.calls.map((c) => c[0])).toEqual([
      '/tasks/t9/files/train.csv?visibility=public',
      '/tasks/t9/files/labels.parquet?visibility=hidden',
      '/tasks/t9/hf-zip',
    ]);
    expect(mockUpload.mock.calls[2][2].contentType).toBe('application/zip');
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(mockShowToast).toHaveBeenCalledWith('Task created successfully!');
  });

  it('sends labels.parquet before baseline_submission.parquet, which is checked against them', async () => {
    const user = userEvent.setup();
    renderManager({ task: { ...saved, evaluation_mode: 'file' } });
    await tab(user, 'Files');
    await user.upload(zoneInput('hidden-files'), [
      new File(['b'], 'baseline_submission.parquet'),
      new File(['l'], 'labels.parquet'),
    ]);
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));
    await waitFor(() => expect(mockUpload).toHaveBeenCalledTimes(2));
    expect(mockUpload.mock.calls.map((c) => c[0])).toEqual([
      '/tasks/t9/files/labels.parquet?visibility=hidden',
      '/tasks/t9/files/baseline_submission.parquet?visibility=hidden',
    ]);
  });

  it('keeps a created task open as an edit when an upload fails, so a retry never duplicates it', async () => {
    mockUpload.mockResolvedValue({
      ok: false,
      status: 422,
      data: { code: 'ERR_INVALID_LABELS_SCHEMA', error: 'bad labels' },
      res: { headers: { get: () => null } },
    });
    const user = userEvent.setup();
    const onClose = renderManager({ mode: 'create' });
    await user.type(screen.getByRole('textbox', { name: /Task Title/ }), 'Sentiment');
    await tab(user, 'Files');
    await user.upload(zoneInput('public-files'), new File(['{}'], 'baseline.ipynb'));
    await user.upload(zoneInput('hidden-files'), new File(['l'], 'labels.parquet'));
    await user.click(screen.getByRole('button', { name: 'Create Task' }));

    const row = await screen.findByTestId('upload-row-labels.parquet');
    await waitFor(() => expect(row).toHaveTextContent('Invalid labels.parquet schema.'));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText('Edit Task: Sentiment')).toBeInTheDocument();
    expect(mockShowToast).toHaveBeenCalledWith(
      'The task is saved, but some files were not uploaded or removed. Retry them in the upload list.',
      'rose',
    );

    // The row retries on its own; Save now updates the saved task
    mockUpload.mockResolvedValue(ok(saved));
    await user.click(within(row).getByRole('button', { name: 'Upload labels.parquet again' }));
    await waitFor(() => expect(row).toHaveTextContent('Done'));
    expect(mockUpload).toHaveBeenLastCalledWith(
      '/tasks/t9/files/labels.parquet?visibility=hidden',
      expect.any(File),
      expect.any(Object),
    );
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    expect(mockCreate).toHaveBeenCalledTimes(1);
  });

  it('updates the task, then uploads a new ZIP, and keeps going after a failed file', async () => {
    mockUpload
      .mockResolvedValueOnce({
        ok: false,
        status: 413,
        data: { code: 'ERR_FILE_TOO_LARGE', error: 'too large', limit: '10 GB' },
        res: { headers: { get: () => null } },
      })
      .mockResolvedValueOnce(ok(withHf));
    const user = userEvent.setup();
    const onClose = renderManager();
    await tab(user, 'Files');
    await user.upload(zoneInput('public-files'), new File(['a'], 'huge.csv'));
    await tab(user, 'Environment');
    await user.upload(zoneInput('hf-data'), zip());
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(mockUpload).toHaveBeenCalledTimes(2));
    expect(mockUpdate).toHaveBeenCalledTimes(1);
    expect(mockUpload.mock.calls[1][0]).toBe('/tasks/t9/hf-zip');
    expect(await screen.findByTestId('upload-row-hf-data.zip')).toHaveTextContent('Done');
    expect(screen.getByTestId('upload-row-huge.csv')).toHaveTextContent('Failed');
    // The finished upload's answer shows the stored data
    expect(screen.getByTestId('hf-current')).toHaveTextContent('models/demo-org/tiny-model/');
    expect(onClose).not.toHaveBeenCalled();
  });

  it('cancels one upload from its row', async () => {
    holdUploads();
    const user = userEvent.setup();
    const onClose = renderManager();
    await tab(user, 'Environment');
    await user.upload(zoneInput('hf-data'), zip());
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));
    await waitFor(() => expect(pending).toHaveLength(1));
    expect(screen.getByRole('button', { name: 'Save Changes' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Cancel the upload of hf-data.zip' }));
    await waitFor(() =>
      expect(screen.getByTestId('upload-row-hf-data.zip')).toHaveTextContent('Cancelled'),
    );
    expect(pending[0].options.signal.aborted).toBe(true);
    expect(onClose).not.toHaveBeenCalled();
  });

  it('asks before closing while files upload, and cancels them on yes', async () => {
    holdUploads();
    const user = userEvent.setup();
    const onClose = renderManager();
    await tab(user, 'Environment');
    await user.upload(zoneInput('hf-data'), zip());
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));
    await waitFor(() => expect(pending).toHaveLength(1));

    mockConfirm.mockResolvedValueOnce(false);
    await user.click(screen.getAllByRole('button', { name: 'Back' })[0]);
    await waitFor(() =>
      expect(mockConfirm).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Stop the uploads?' }),
      ),
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(pending[0].options.signal.aborted).toBe(false);

    mockConfirm.mockResolvedValueOnce(true);
    await user.click(screen.getAllByRole('button', { name: 'Back' })[0]);
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(pending[0].options.signal.aborted).toBe(true);
  });

  it('removes a stored file in a row of the upload list, with the admin reason after publish', async () => {
    const published = {
      ...saved,
      files_locked: true,
      files: [
        ...saved.files,
        { filename: 'labels.parquet', size_bytes: 10, visibility: 'hidden' },
        { filename: 'old_labels.csv', size_bytes: 10, visibility: 'hidden' },
      ],
    };
    mockUpdate.mockResolvedValue({ ok: true, data: published });
    mockRemove.mockResolvedValue(ok({ ...published, files: published.files.slice(0, 2) }));
    const user = userEvent.setup();
    renderManager({ task: published });
    await tab(user, 'Files');
    const row = screen.getByTestId('existing-file-old_labels.csv');
    await user.click(within(row).getByRole('button', { name: 'Delete' }));
    await user.type(
      screen.getByRole('textbox', { name: /Reason for changing hidden files/ }),
      'Old copy',
    );
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));
    await waitFor(() =>
      expect(mockRemove).toHaveBeenCalledWith('/tasks/t9/files/old_labels.csv?reason=Old+copy'),
    );
    expect(mockUpdate.mock.calls[0][0].formData.get('deleted_files')).toBeNull();
    const removal = await screen.findByTestId('remove-row-old_labels.csv');
    expect(removal).toHaveTextContent('Remove old_labels.csv');
    await waitFor(() => expect(removal).toHaveTextContent('Done'));
    await waitFor(() => expect(screen.queryByTestId('existing-file-old_labels.csv')).toBeNull());
  });

  it('runs the removals before the uploads of the same save', async () => {
    const order = [];
    mockRemove.mockImplementation(async (path) => {
      order.push(`DELETE ${path}`);
      return ok(withHf);
    });
    mockUpload.mockImplementation(async (path) => {
      order.push(`PUT ${path}`);
      return ok(withHf);
    });
    const user = userEvent.setup();
    renderManager({
      task: { ...withHf, files: [...saved.files, { filename: 'old.csv', size_bytes: 1 }] },
    });
    await tab(user, 'Files');
    await user.upload(zoneInput('public-files'), new File(['a'], 'new.csv'));
    await user.click(
      within(screen.getByTestId('existing-file-old.csv')).getByRole('button', { name: 'Delete' }),
    );
    await tab(user, 'Environment');
    await user.click(screen.getByRole('button', { name: 'Remove' }));
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));
    await waitFor(() => expect(order).toHaveLength(3));
    expect(order).toEqual([
      'DELETE /tasks/t9/files/old.csv',
      'DELETE /tasks/t9/hf-zip',
      'PUT /tasks/t9/files/new.csv?visibility=public',
    ]);
  });

  it('removes the HF data on Save, not at once, and shows the row of the removal', async () => {
    mockRemove.mockResolvedValue(ok({ ...saved, hf_zip_sha256: null }));
    const user = userEvent.setup();
    const onClose = renderManager({ task: withHf });
    await tab(user, 'Environment');
    await user.click(screen.getByRole('button', { name: 'Remove' }));
    expect(mockRemove).not.toHaveBeenCalled();
    expect(mockConfirm).not.toHaveBeenCalled();
    expect(screen.getByTestId('hf-current')).toHaveTextContent(/Removed when you save/);

    await user.click(screen.getByRole('button', { name: 'Save Changes' }));
    await waitFor(() => expect(mockRemove).toHaveBeenCalledWith('/tasks/t9/hf-zip'));
    expect(mockUpload).not.toHaveBeenCalled();
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(mockShowToast).toHaveBeenCalledWith('Task updated successfully!');
  });

  it('keeps a refused HF removal as a failed row with Retry', async () => {
    mockRemove.mockResolvedValueOnce({
      ok: false,
      status: 409,
      data: { code: 'ERR_TASK_FILES_LOCKED', error: 'locked' },
      res: { headers: { get: () => null } },
    });
    const user = userEvent.setup();
    const onClose = renderManager({ task: withHf });
    await tab(user, 'Environment');
    await user.click(screen.getByRole('button', { name: 'Remove' }));
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    const row = await screen.findByTestId('remove-row-Hugging Face data');
    await waitFor(() => expect(row).toHaveTextContent('Failed'));
    expect(onClose).not.toHaveBeenCalled();
    // The stored data stays on screen without the mark, since the save went through
    expect(screen.getByTestId('hf-current')).not.toHaveTextContent(/Removed when you save/);

    mockRemove.mockResolvedValueOnce(ok({ ...saved, hf_zip_sha256: null }));
    await user.click(
      within(row).getByRole('button', { name: 'Try to remove Hugging Face data again' }),
    );
    await waitFor(() => expect(row).toHaveTextContent('Done'));
    expect(await screen.findByText('No Hugging Face data yet.')).toBeInTheDocument();
  });

  it('keeps the HF data of a published task fixed, for the jury too', async () => {
    const user = userEvent.setup();
    renderManager({ task: { ...withHf, files_locked: true }, isAdmin: false });
    await tab(user, 'Environment');
    const section = screen.getByTestId('hf-data');
    expect(section).toHaveTextContent(
      'The workspace environment is published, so these files are fixed.',
    );
    expect(section.querySelector('input[type="file"]')).toBeNull();
    expect(within(section).queryByRole('button', { name: 'Remove' })).toBeNull();
  });

  it('gives a file task an environment tab with only the HF data', async () => {
    const user = userEvent.setup();
    renderManager({ task: { ...saved, evaluation_mode: 'file' }, isAdmin: false });
    await tab(user, 'Environment');
    expect(screen.getByTestId('hf-data')).toBeInTheDocument();
    expect(screen.queryByText('Docker Sandbox')).toBeNull();
  });

  it('shows the readiness problems the latest upload answered with', async () => {
    mockUpdate.mockResolvedValue({ ok: true, data: { ...saved, problem_codes: [] } });
    mockUpload.mockResolvedValue(ok({ ...saved, problem_codes: ['ERR_INVALID_LABELS_SCHEMA'] }));
    const user = userEvent.setup();
    renderManager();
    await tab(user, 'Files');
    await user.upload(zoneInput('public-files'), new File(['a'], 'a.csv'));
    await user.upload(zoneInput('public-files'), new File(['b'], 'b.csv'));
    mockUpload.mockResolvedValueOnce(
      ok({ ...saved, problem_codes: ['ERR_INVALID_LABELS_SCHEMA'] }),
    );
    mockUpload.mockResolvedValueOnce({
      ok: false,
      status: 400,
      data: { code: 'ERR_INVALID_FILENAME', error: 'bad' },
      res: { headers: { get: () => null } },
    });
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));
    expect(await screen.findByText('Invalid labels.parquet schema.')).toBeInTheDocument();
  });
});
