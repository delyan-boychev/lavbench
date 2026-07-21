import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import TaskService from '../../services/TaskService';
import { useSelectFinal, useKillSubmission, useClearQueue } from '../useSubmissionMutations';

vi.mock('../../services/TaskService', () => ({
  default: {
    killSubmission: vi.fn(),
    clearQueue: vi.fn(),
  },
}));

function createWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }) {
    return React.createElement(QueryClientProvider, { client: qc }, children);
  };
}

describe('useSubmissionMutations', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('useSelectFinal', () => {
    it('sends POST to select-final endpoint', async () => {
      const okResponse = { ok: true, json: () => Promise.resolve({ message: 'done' }) };
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(okResponse);
      const { result } = renderHook(() => useSelectFinal(), { wrapper: createWrapper() });
      result.current.mutate('sub-1');
      await waitFor(() =>
        expect(globalThis.fetch).toHaveBeenCalledWith(
          '/api/submissions/sub-1/select-final',
          expect.objectContaining({ method: 'POST' }),
        ),
      );
    });

    it('rejects on non-ok response', async () => {
      const errorResponse = { ok: false, json: () => Promise.resolve({ code: 'ERR_NOT_FOUND' }) };
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(errorResponse);
      const { result } = renderHook(() => useSelectFinal(), { wrapper: createWrapper() });
      result.current.mutate('sub-missing');
      await waitFor(() => {
        expect(result.current.isError).toBe(true);
      });
    });
  });

  describe('useKillSubmission', () => {
    it('calls TaskService.killSubmission', async () => {
      TaskService.killSubmission.mockResolvedValue({ ok: true });
      const { result } = renderHook(() => useKillSubmission(), { wrapper: createWrapper() });
      result.current.mutate('sub-1');
      await waitFor(() => expect(TaskService.killSubmission).toHaveBeenCalledWith('sub-1'));
    });
  });

  describe('useClearQueue', () => {
    it('calls TaskService.clearQueue', async () => {
      TaskService.clearQueue.mockResolvedValue({ ok: true });
      const { result } = renderHook(() => useClearQueue(), { wrapper: createWrapper() });
      result.current.mutate();
      await waitFor(() => expect(TaskService.clearQueue).toHaveBeenCalledWith());
    });
  });
});
