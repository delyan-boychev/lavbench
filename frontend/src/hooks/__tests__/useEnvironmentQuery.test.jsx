import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import EnvironmentService from '../../services/EnvironmentService';
import { environmentKeys, isEnvironmentHidden, useEnvironmentQuery } from '../useEnvironmentQuery';
import { useExtendEnvironment, useSaveEnvironment } from '../useEnvironmentMutations';

vi.mock('../../services/EnvironmentService', () => ({
  default: { get: vi.fn(), save: vi.fn(), extend: vi.fn() },
}));

function setup(retry = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry } } });
  const wrapper = ({ children }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

describe('environment queries', () => {
  beforeEach(() => vi.clearAllMocks());

  it('treats off, not enabled and forbidden as hidden, other failures as errors', () => {
    expect(isEnvironmentHidden({ status: 404 })).toBe(true);
    expect(isEnvironmentHidden({ status: 409 })).toBe(true);
    expect(isEnvironmentHidden({ status: 403 })).toBe(true);
    expect(isEnvironmentHidden({ status: 500 })).toBe(false);
    expect(isEnvironmentHidden(new Error('network'))).toBe(false);
  });

  it('does not retry a disabled feature', async () => {
    EnvironmentService.get.mockResolvedValue({
      ok: false,
      status: 404,
      data: { code: 'ERR_NANOCOLAB_DISABLED' },
    });
    const { wrapper } = setup(3);
    const { result } = renderHook(() => useEnvironmentQuery('c1', 's1'), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error.code).toBe('ERR_NANOCOLAB_DISABLED');
    expect(EnvironmentService.get).toHaveBeenCalledTimes(1);
  });

  it('stores the saved environment under its owner without a refetch', async () => {
    EnvironmentService.save.mockResolvedValue({ ok: true, status: 200, data: { id: 'e1' } });
    const { client, wrapper } = setup();
    const { result } = renderHook(() => useSaveEnvironment('c1', 's1'), { wrapper });
    await act(() => result.current.mutateAsync({ enabled: true }));
    expect(client.getQueryData(environmentKeys.owner('c1', 's1'))).toEqual({ id: 'e1' });
    expect(EnvironmentService.get).not.toHaveBeenCalled();
  });

  it('refreshes the competitions after an extension moves the end', async () => {
    EnvironmentService.extend.mockResolvedValue({ ok: true, status: 200, data: { id: 'e1' } });
    const { client, wrapper } = setup();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useExtendEnvironment('c1', null), { wrapper });
    await act(() =>
      result.current.mutateAsync({ environmentId: 'e1', end_time: 'x', reason: 'because' }),
    );
    expect(EnvironmentService.extend).toHaveBeenCalledWith('c1', 'e1', {
      end_time: 'x',
      reason: 'because',
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['admin-challenges'] });
    expect(client.getQueryData(environmentKeys.owner('c1', null))).toEqual({ id: 'e1' });
  });
});
