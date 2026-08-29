import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import api from '../../services/ApiService';
import {
  useCreateChallenge,
  useUpdateChallenge,
  useDeleteChallenge,
  useFinalizeChallenge,
  useToggleRevealChallenge,
  useArchiveToggle,
  useImportChallenge,
} from '../useChallengeMutations';

vi.mock('../../services/ApiService', () => ({
  default: {
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    get: vi.fn(),
    postForm: vi.fn(),
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

describe('useChallengeMutations', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.post.mockResolvedValue({ ok: true, data: {} });
    api.put.mockResolvedValue({ ok: true, data: {} });
    api.delete.mockResolvedValue({ ok: true, data: {} });
    api.postForm.mockResolvedValue({ ok: true, data: {} });
  });

  it('useCreateChallenge calls api.post', async () => {
    const { result } = renderHook(() => useCreateChallenge(), { wrapper: createWrapper() });
    result.current.mutate({ title: 'Test' });
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/challenges', { title: 'Test' }));
  });

  it('useUpdateChallenge calls api.put', async () => {
    const { result } = renderHook(() => useUpdateChallenge(), { wrapper: createWrapper() });
    result.current.mutate({ id: 'c1', title: 'Updated' });
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith('/challenges/c1', { title: 'Updated' }),
    );
  });

  it('useDeleteChallenge calls api.delete', async () => {
    const { result } = renderHook(() => useDeleteChallenge(), { wrapper: createWrapper() });
    result.current.mutate('c1');
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/challenges/c1'));
  });

  it('useFinalizeChallenge calls api.post', async () => {
    const { result } = renderHook(() => useFinalizeChallenge(), { wrapper: createWrapper() });
    result.current.mutate({ id: 'c1', reveal_results: false });
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/challenges/c1/finalize', {
        reveal_results: false,
      }),
    );
  });

  it('useToggleRevealChallenge calls api.put', async () => {
    const { result } = renderHook(() => useToggleRevealChallenge(), { wrapper: createWrapper() });
    result.current.mutate({ id: 'c1', reveal_results: true });
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith('/challenges/c1/reveal-results', {
        reveal_results: true,
      }),
    );
  });

  it('useArchiveToggle calls api.post', async () => {
    const { result } = renderHook(() => useArchiveToggle(), { wrapper: createWrapper() });
    result.current.mutate('c1');
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/challenges/c1/archive'));
  });

  it('useImportChallenge calls api.postForm', async () => {
    const fd = new FormData();
    const { result } = renderHook(() => useImportChallenge(), { wrapper: createWrapper() });
    result.current.mutate(fd);
    await waitFor(() => expect(api.postForm).toHaveBeenCalledWith('/challenges/import', fd));
  });

  it('preserves backend errors and enters the error state', async () => {
    api.post.mockResolvedValue({
      ok: false,
      status: 422,
      data: { code: 'ERR_VALIDATION', error: 'Invalid challenge' },
    });
    const { result } = renderHook(() => useCreateChallenge(), { wrapper: createWrapper() });
    result.current.mutate({ title: '' });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toMatchObject({
      code: 'ERR_VALIDATION',
      error: 'Invalid challenge',
      status: 422,
    });
  });
});
