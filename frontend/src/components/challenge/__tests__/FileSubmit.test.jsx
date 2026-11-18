import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, act, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../../test-utils';
import TaskService from '../../../services/TaskService';
import FileSubmit from '../FileSubmit';

const { mockShowToast, mockNavigate } = vi.hoisted(() => ({
  mockShowToast: vi.fn(),
  mockNavigate: vi.fn(),
}));

vi.mock('react-router', async (importOriginal) => ({
  ...(await importOriginal()),
  useNavigate: () => mockNavigate,
}));

vi.mock('../../../context/AppContext', () => ({
  useApp: () => ({ showToast: mockShowToast }),
}));

vi.mock('../../../services/TaskService', () => ({
  default: { submitWorkspace: vi.fn(), submitFile: vi.fn() },
}));

const task = {
  id: 't1',
  title: 'Image classification',
  evaluation_mode: 'file',
  folder_name: 'image-classification',
  emergency_upload_enabled: false,
};
const challenge = { id: 'c1', max_eval_requests: 5 };

/** A fetch-style result as ApiService returns it. */
function result(status, data, headers = {}) {
  return {
    ok: status < 400,
    status,
    data,
    res: { headers: { get: (name) => headers[name] ?? null } },
  };
}

describe('FileSubmit', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('names the two files and the folder', () => {
    renderWithProviders(<FileSubmit task={task} challenge={challenge} />);
    expect(screen.getByText(/image-classification\/ folder of your workspace/)).toBeInTheDocument();
    expect(screen.queryByTestId('emergency-upload-form')).not.toBeInTheDocument();
  });

  it('submits from the workspace and opens the new submission', async () => {
    TaskService.submitWorkspace.mockResolvedValue(
      result(202, { submission_id: 's9', status: 'queued' }),
    );
    renderWithProviders(<FileSubmit task={task} challenge={challenge} />);
    fireEvent.click(screen.getByRole('button', { name: 'Submit from workspace' }));

    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith('/challenges/c1/submissions', {
        state: { submissionId: 's9' },
      }),
    );
    expect(TaskService.submitWorkspace).toHaveBeenCalledWith('t1');
    expect(mockShowToast).toHaveBeenCalledWith('Submission queued for evaluation!');
  });

  it('shows a missing file next to the button with its file and folder', async () => {
    TaskService.submitWorkspace.mockResolvedValue(
      result(404, {
        code: 'ERR_WORKSPACE_FILE_MISSING',
        error: 'No submission.parquet in image-classification/ of your workspace.',
        file: 'submission.parquet',
        folder: 'image-classification',
      }),
    );
    renderWithProviders(<FileSubmit task={task} challenge={challenge} />);
    fireEvent.click(screen.getByRole('button', { name: 'Submit from workspace' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'No submission.parquet in image-classification/ of your workspace. Save it from solution.ipynb, then Submit again.',
    );
    expect(mockNavigate).not.toHaveBeenCalled();
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  it('waits out Retry-After without retrying on its own', async () => {
    TaskService.submitWorkspace.mockResolvedValue(
      result(
        503,
        { code: 'ERR_WORKSPACE_EXPORT_UNAVAILABLE', error: 'busy' },
        { 'Retry-After': '3' },
      ),
    );
    renderWithProviders(<FileSubmit task={task} challenge={challenge} />);
    const button = screen.getByRole('button', { name: 'Submit from workspace' });
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    try {
      fireEvent.click(button);
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
      });
      await vi.waitFor(() =>
        expect(screen.getByText('Try again in 3 seconds.')).toBeInTheDocument(),
      );
      expect(screen.getByRole('alert')).toHaveTextContent(
        'Your workspace files cannot be read right now. Please try again shortly.',
      );
      expect(button).toBeDisabled();
      await act(async () => {
        vi.advanceTimersByTime(1000);
      });
      expect(screen.getByText('Try again in 2 seconds.')).toBeInTheDocument();
      await act(async () => {
        vi.advanceTimersByTime(2500);
      });
      expect(screen.queryByText(/Try again in/)).not.toBeInTheDocument();
      expect(button).toBeEnabled();
      expect(TaskService.submitWorkspace).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('uploads both files while the emergency switch is on', async () => {
    TaskService.submitFile.mockResolvedValue(result(202, { submission_id: 's10' }));
    renderWithProviders(
      <FileSubmit task={{ ...task, emergency_upload_enabled: true }} challenge={challenge} />,
    );
    const upload = screen.getByRole('button', { name: 'Upload and submit' });
    expect(upload).toBeDisabled();

    const parquet = new File(['p'], 'submission.parquet');
    const notebook = new File(['{}'], 'solution.ipynb');
    const inputs = screen.getByTestId('emergency-upload-form').querySelectorAll('input[type=file]');
    fireEvent.change(inputs[0], { target: { files: [parquet] } });
    fireEvent.change(inputs[1], { target: { files: [notebook] } });
    fireEvent.click(upload);

    await waitFor(() =>
      expect(TaskService.submitFile).toHaveBeenCalledWith('t1', parquet, notebook),
    );
    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith('/challenges/c1/submissions', {
        state: { submissionId: 's10' },
      }),
    );
  });

  it('waits out a platform failure of the file check', async () => {
    TaskService.submitWorkspace.mockResolvedValue(
      result(
        503,
        { code: 'ERR_SUBMISSION_CHECK_FAILED', error: 'check failed' },
        { 'Retry-After': '5' },
      ),
    );
    renderWithProviders(<FileSubmit task={task} challenge={challenge} />);
    const button = screen.getByRole('button', { name: 'Submit from workspace' });
    fireEvent.click(button);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The file could not be checked because of a platform problem. Please try again shortly.',
    );
    expect(screen.getByText('Try again in 5 seconds.')).toBeInTheDocument();
    expect(button).toBeDisabled();
  });

  it('shows a size limit with its value', async () => {
    TaskService.submitWorkspace.mockResolvedValue(
      result(413, {
        code: 'ERR_WORKSPACE_FILE_TOO_LARGE',
        error: 'The file exceeds the 20 MB limit.',
        limit: '20 MB',
      }),
    );
    renderWithProviders(<FileSubmit task={task} challenge={challenge} />);
    fireEvent.click(screen.getByRole('button', { name: 'Submit from workspace' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The file exceeds the 20 MB limit.');
  });
});
