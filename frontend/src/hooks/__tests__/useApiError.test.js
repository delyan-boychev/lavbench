import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useApiError, useApiErrorText, useTaskProblemText } from '../useApiError';
import { ApiRequestError } from '../../services/apiResult';

const mockShowToast = vi.fn();
vi.mock('../../context/NotificationsContext', () => ({
  useNotifications: () => ({ showToast: mockShowToast }),
}));

describe('useApiError', () => {
  beforeEach(() => mockShowToast.mockClear());

  it('shows the translated message with the size limit from the response', () => {
    const { result } = renderHook(() => useApiError());
    result.current.showApiError(
      {
        code: 'ERR_FILE_TOO_LARGE',
        error: 'The CSV file exceeds the 50 MB limit.',
        limit: '50 MB',
      },
      'admin.notifications.import_failed',
    );
    expect(mockShowToast).toHaveBeenCalledWith('The file exceeds the 50 MB limit.', 'rose');
  });

  it('reads the limit from an ApiRequestError body', () => {
    const { result } = renderHook(() => useApiError());
    const error = new ApiRequestError({
      ok: false,
      status: 413,
      data: { code: 'ERR_FILE_TOO_LARGE', error: 'too large', limit: '200 MB' },
    });
    result.current.showApiError(error, 'admin.notifications.import_challenge_failed');
    expect(mockShowToast).toHaveBeenCalledWith('The file exceeds the 200 MB limit.', 'rose');
  });

  it('falls back to the server message when there is no code', () => {
    const { result } = renderHook(() => useApiError());
    result.current.showApiError({ error: 'Plain failure' }, 'missing.key');
    expect(mockShowToast).toHaveBeenCalledWith('Plain failure', 'rose');
  });

  it('formats without a toast for inline texts, with the same interpolation', () => {
    const { result } = renderHook(() => useApiErrorText());
    expect(result.current({ code: 'ERR_FILE_TOO_LARGE', error: 'x', limit: '2 GiB' })).toBe(
      'The file exceeds the 2 GiB limit.',
    );
    expect(result.current({ error: 'Plain failure' })).toBe('Plain failure');
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  it('fills a task problem with the fields stored for its code', () => {
    const { result } = renderHook(() => useTaskProblemText());
    const detail = '1 of the 3 expected ids are missing and 1 ids are not in the task.';
    const task = {
      problem_fields: { ERR_BASELINE_SUBMISSION_MISMATCH: { detail, missing_ids: 1 } },
    };
    expect(result.current(task, 'ERR_BASELINE_SUBMISSION_MISMATCH')).toBe(
      `The stored baseline_submission.parquet does not match the new labels.parquet: ${detail} Upload a matching baseline.`,
    );
    expect(result.current(task, 'ERR_TASK_LABELS_MISSING')).toBe('The task has no labels.parquet.');
  });
});
