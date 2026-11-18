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

  it('composes the text of a machine reason with its values, never the English detail', () => {
    const { result } = renderHook(() => useApiErrorText());
    expect(
      result.current({
        code: 'ERR_HF_ZIP_INVALID',
        error: 'weights/a.bin is outside models/ and datasets/.',
        detail: 'weights/a.bin is outside models/ and datasets/.',
        reason: 'outside_folders',
        file: 'weights/a.bin',
      }),
    ).toBe('The Hugging Face ZIP cannot be used: weights/a.bin is outside models/ and datasets/.');
    expect(
      result.current({
        code: 'ERR_SUBMISSION_FILE_INVALID',
        error: 'x',
        detail: 'English',
        reason: 'ids_mismatch',
        expected_ids: 4,
        missing_ids: 1,
        unexpected_ids: 2,
      }),
    ).toBe(
      'The submission file cannot be scored: 1 of the 4 expected ids are missing and 2 ids are not in the task.',
    );
    expect(
      result.current({
        code: 'ERR_ENVIRONMENT_PACKAGE_TOO_LARGE',
        error: 'x',
        detail: '2001',
        limit: '2000',
        reason: 'package_files',
      }),
    ).toBe('The workspace package is too large: it would hold 2001 files, more than 2000.');
  });

  it('fills a task problem with the fields stored for its code', () => {
    const { result } = renderHook(() => useTaskProblemText());
    const fields = {
      detail: 'English',
      reason: 'ids_mismatch',
      expected_ids: 3,
      missing_ids: 1,
      unexpected_ids: 1,
    };
    const task = { problem_fields: { ERR_BASELINE_SUBMISSION_MISMATCH: fields } };
    expect(result.current(task, 'ERR_BASELINE_SUBMISSION_MISMATCH')).toBe(
      'The stored baseline_submission.parquet does not match the new labels.parquet: 1 of the 3 expected ids are missing and 1 ids are not in the task. Upload a matching baseline.',
    );
    expect(result.current(task, 'ERR_TASK_LABELS_MISSING')).toBe('The task has no labels.parquet.');
  });

  it("fills a server time in the viewer's language and the plural count", () => {
    const { result } = renderHook(() => useApiErrorText());
    const text = result.current({
      code: 'ERR_FINAL_SELECTION_OPEN',
      error: 'open',
      available_at: '2026-06-13T12:06:00Z',
    });
    expect(text).toMatch(/^Competitors can still choose their final submissions until /);
    expect(text).not.toContain('2026-06-13T12:06:00Z');
    expect(text).toContain('2026');
    expect(result.current({ code: 'ERR_EVALUATIONS_PENDING', error: 'x', count: 1 })).toBe(
      '1 submission is still waiting to be scored. Finalizing is possible once it is scored.',
    );
    expect(result.current({ code: 'ERR_EVALUATIONS_PENDING', error: 'x', count: 3 })).toMatch(
      /^3 submissions are still waiting/,
    );
  });
});
