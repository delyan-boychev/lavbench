import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import api from '../../services/ApiService';
import {
  useDeleteTaskFile,
  useInvalidateTaskData,
  useRemoveHfZip,
  useSetEmergencyUpload,
} from '../useTaskMutations';

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

describe('useRemoveHfZip', () => {
  it('deletes the ZIP and refreshes the task and environment data', async () => {
    api.delete.mockResolvedValue({ ok: true, status: 200, data: { id: 't1', hf_folders: [] } });
    const { result, invalidate } = setup(() => useRemoveHfZip());
    const res = await result.current.mutateAsync({ taskId: 't1' });
    expect(api.delete).toHaveBeenCalledWith('/tasks/t1/hf-zip');
    expect(res.data.hf_folders).toEqual([]);
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['environment'] }));
  });

  it('reports a lock refusal', async () => {
    api.delete.mockResolvedValue({
      ok: false,
      status: 409,
      data: { code: 'ERR_TASK_FILES_LOCKED' },
    });
    const { result } = setup(() => useRemoveHfZip());
    await expect(result.current.mutateAsync({ taskId: 't1' })).rejects.toMatchObject({
      code: 'ERR_TASK_FILES_LOCKED',
    });
  });
});

describe('useDeleteTaskFile', () => {
  it('removes one file, with the reason for a hidden file after publish', async () => {
    api.delete.mockResolvedValue({ ok: true, status: 200, data: { id: 't1', files: [] } });
    const { result, invalidate } = setup(() => useDeleteTaskFile());
    await result.current.mutateAsync({ taskId: 't1', filename: 'a b.csv', reason: 'Fix ids' });
    expect(api.delete).toHaveBeenCalledWith('/tasks/t1/files/a%20b.csv?reason=Fix+ids');
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['environment'] }));
  });

  it('sends no reason when none is needed', async () => {
    api.delete.mockResolvedValue({ ok: true, status: 200, data: {} });
    const { result } = setup(() => useDeleteTaskFile());
    await result.current.mutateAsync({ taskId: 't1', filename: 'train.csv', reason: '' });
    expect(api.delete).toHaveBeenCalledWith('/tasks/t1/files/train.csv');
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
