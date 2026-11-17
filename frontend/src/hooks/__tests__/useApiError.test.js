import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useApiError, useApiErrorText } from '../useApiError';
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
});
