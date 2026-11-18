import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import EnvironmentService from '../../services/EnvironmentService';
import {
  environmentKeys,
  isEnvironmentHidden,
  useEnvironmentListQuery,
  useEnvironmentsQuery,
  useWorkspaceCatalogQuery,
} from '../useEnvironmentQuery';
import { useExtendEnvironment, usePublishEnvironment } from '../useEnvironmentMutations';

vi.mock('../../services/EnvironmentService', () => ({
  default: { list: vi.fn(), getCatalog: vi.fn(), publish: vi.fn(), extend: vi.fn() },
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
    EnvironmentService.getCatalog.mockResolvedValue({
      ok: false,
      status: 404,
      data: { code: 'ERR_NANOCOLAB_DISABLED' },
    });
    const { wrapper } = setup(3);
    const { result } = renderHook(() => useWorkspaceCatalogQuery(true), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error.code).toBe('ERR_NANOCOLAB_DISABLED');
    expect(EnvironmentService.getCatalog).toHaveBeenCalledTimes(1);
  });

  it('lists the environments of a competition', async () => {
    EnvironmentService.list.mockResolvedValue({
      ok: true,
      status: 200,
      data: { environments: [{ id: 'e1' }] },
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => useEnvironmentsQuery('c1'), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual([{ id: 'e1' }]));
    expect(EnvironmentService.list).toHaveBeenCalledWith('c1');
  });

  it('carries the setting lock next to the environments', async () => {
    EnvironmentService.list.mockResolvedValue({
      ok: true,
      status: 200,
      data: { environments: [{ id: 'e1' }], setting_locked: true },
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => useEnvironmentListQuery('c1'), { wrapper });
    await waitFor(() =>
      expect(result.current.data).toEqual({ environments: [{ id: 'e1' }], setting_locked: true }),
    );
  });

  it('puts the published environment into the list without a refetch', async () => {
    EnvironmentService.publish.mockResolvedValue({
      ok: true,
      status: 200,
      data: { id: 'e1', published_at: 'now' },
    });
    const { client, wrapper } = setup();
    client.setQueryData(environmentKeys.list('c1'), {
      environments: [{ id: 'e1' }, { id: 'e2' }],
      setting_locked: false,
    });
    const { result } = renderHook(() => usePublishEnvironment('c1'), { wrapper });
    await act(() => result.current.mutateAsync('e1'));
    expect(client.getQueryData(environmentKeys.list('c1'))).toEqual({
      environments: [{ id: 'e1', published_at: 'now' }, { id: 'e2' }],
      setting_locked: false,
    });
    expect(EnvironmentService.list).not.toHaveBeenCalled();
  });

  it('refreshes the competitions after an extension moves the end', async () => {
    EnvironmentService.extend.mockResolvedValue({ ok: true, status: 200, data: { id: 'e1' } });
    const { client, wrapper } = setup();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useExtendEnvironment('c1'), { wrapper });
    await act(() =>
      result.current.mutateAsync({ environmentId: 'e1', end_time: 'x', reason: 'because' }),
    );
    expect(EnvironmentService.extend).toHaveBeenCalledWith('c1', 'e1', {
      end_time: 'x',
      reason: 'because',
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['admin-challenges'] });
  });
});
