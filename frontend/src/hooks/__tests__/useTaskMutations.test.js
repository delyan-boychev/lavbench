import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import api from '../../services/ApiService';
import { useInvalidateTaskData, useSetEmergencyUpload } from '../useTaskMutations';

vi.mock('../../services/ApiService', () => ({
  default: { put: vi.fn(), delete: vi.fn() },
}));

function setup(hook) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const invalidate = vi.spyOn(qc, 'invalidateQueries');
  const wrapper = ({ children }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
  const { result } = renderHook(hook, { wrapper });
  return { result, invalidate };
}

describe('useSetEmergencyUpload', () => {
  it('saves the switch and refreshes the competitions, so a reopened task shows it', async () => {
    api.put.mockResolvedValue({ ok: true, status: 200, data: { emergency_upload_enabled: true } });
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const invalidate = vi.spyOn(qc, 'invalidateQueries');
    const wrapper = ({ children }) =>
      React.createElement(QueryClientProvider, { client: qc }, children);
    const { result } = renderHook(() => useSetEmergencyUpload(), { wrapper });

    await result.current.mutateAsync({ taskId: 't1', enabled: true, reason: 'outage' });

    expect(api.put).toHaveBeenCalledWith('/tasks/t1/emergency-upload', {
      enabled: true,
      reason: 'outage',
    });
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['admin-challenges'] }),
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['challenges'] });
  });

  it('reports a refusal', async () => {
    api.put.mockResolvedValue({ ok: false, status: 400, data: { code: 'ERR_REASON_REQUIRED' } });
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const wrapper = ({ children }) =>
      React.createElement(QueryClientProvider, { client: qc }, children);
    const { result } = renderHook(() => useSetEmergencyUpload(), { wrapper });
    await expect(
      result.current.mutateAsync({ taskId: 't1', enabled: true, reason: '' }),
    ).rejects.toMatchObject({ code: 'ERR_REASON_REQUIRED' });
  });
});

describe('useInvalidateTaskData', () => {
  it('refreshes the competitions and the environments', () => {
    const { result, invalidate } = setup(() => useInvalidateTaskData());
    result.current();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['admin-challenges'] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['challenges'] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['environment'] });
  });
});
