import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import TaskService from '../../services/TaskService';
import {
  ACTIVE_SUBMISSION_POLL_MS,
  isActiveSubmission,
  useSubmissionsQuery,
} from '../useSubmissionsQuery';

vi.mock('../../services/TaskService', () => ({
  default: { getSubmissions: vi.fn() },
}));

function wrapper({ children }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const page = (...statuses) => ({
  ok: true,
  data: { items: statuses.map((status, i) => ({ id: i + 1, status })), total: statuses.length },
});

describe('useSubmissionsQuery', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('polls every 5 s while a submission is queued or running, then stops', async () => {
    TaskService.getSubmissions
      .mockResolvedValueOnce(page('completed', 'queued'))
      .mockResolvedValueOnce(page('completed', 'running'))
      .mockResolvedValue(page('completed', 'failed'));

    renderHook(() => useSubmissionsQuery('task-1', 1, 10), { wrapper });
    await vi.advanceTimersByTimeAsync(0);
    expect(TaskService.getSubmissions).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(ACTIVE_SUBMISSION_POLL_MS);
    expect(TaskService.getSubmissions).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(ACTIVE_SUBMISSION_POLL_MS);
    expect(TaskService.getSubmissions).toHaveBeenCalledTimes(3);

    await vi.advanceTimersByTimeAsync(ACTIVE_SUBMISSION_POLL_MS * 6);
    expect(TaskService.getSubmissions).toHaveBeenCalledTimes(3);
  });

  it('does not poll when every submission is finished', async () => {
    TaskService.getSubmissions.mockResolvedValue(page('completed', 'failed'));
    renderHook(() => useSubmissionsQuery('task-1', 1, 10), { wrapper });
    await vi.advanceTimersByTimeAsync(ACTIVE_SUBMISSION_POLL_MS * 4);
    expect(TaskService.getSubmissions).toHaveBeenCalledTimes(1);
  });

  it('does not fetch when disabled', async () => {
    renderHook(() => useSubmissionsQuery('task-1', 1, 10, { enabled: false }), { wrapper });
    await vi.advanceTimersByTimeAsync(ACTIVE_SUBMISSION_POLL_MS);
    expect(TaskService.getSubmissions).not.toHaveBeenCalled();
  });

  it.each([
    ['queued', true],
    ['running', true],
    ['completed', false],
    ['failed', false],
  ])('treats %s as active: %s', (status, active) => {
    expect(isActiveSubmission({ status })).toBe(active);
  });
});
