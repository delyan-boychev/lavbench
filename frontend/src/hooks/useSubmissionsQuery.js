import { useQuery } from '@tanstack/react-query';
import TaskService from '../services/TaskService';

export const ACTIVE_SUBMISSION_POLL_MS = 5_000;

/** @param {{ status?: string } | null | undefined} submission */
export function isActiveSubmission(submission) {
  return submission?.status === 'queued' || submission?.status === 'running';
}

/**
 * The signed-in competitor's own submissions for a task. The page polls while any of
 * its submissions is queued or running, and stops once all of them are finished.
 * @param {string | undefined} taskId
 * @param {number} [page]
 * @param {number} [perPage]
 * @param {{ enabled?: boolean }} [options]
 */
export function useSubmissionsQuery(taskId, page = 1, perPage = 10, options = {}) {
  const { enabled = true } = options;
  return useQuery({
    queryKey: ['submissions', taskId, page, perPage],
    queryFn: () =>
      TaskService.getSubmissions(taskId, page, perPage).then((res) => {
        if (!res.ok) throw new Error('Failed to load submissions');
        return res.data;
      }),
    enabled: enabled && !!taskId,
    staleTime: 10_000,
    // React Query pauses interval refetches while the tab is hidden
    refetchInterval: (query) =>
      query.state.data?.items?.some(isActiveSubmission) ? ACTIVE_SUBMISSION_POLL_MS : false,
  });
}
