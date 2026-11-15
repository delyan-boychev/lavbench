import { useQuery } from '@tanstack/react-query';
import TaskService from '../services/TaskService';
import { requireOk, retryUnlessClientError } from '../services/apiResult';

export const ACTIVE_SUBMISSION_POLL_MS = 5_000;

/** @param {{ status?: string } | null | undefined} submission */
export function isActiveSubmission(submission) {
  return submission?.status === 'queued' || submission?.status === 'running';
}

/**
 * Whether a submissions query failed because the finalised competition locks the
 * competitor's own submissions
 * @param {unknown} error
 */
export function isSubmissionsLocked(error) {
  return /** @type {{ code?: string } | null} */ (error)?.code === 'ERR_SUBMISSIONS_LOCKED';
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
    // The thrown ApiRequestError keeps the response code and message
    queryFn: () =>
      TaskService.getSubmissions(taskId, page, perPage)
        .then(requireOk)
        .then((res) => res.data),
    enabled: enabled && !!taskId,
    retry: retryUnlessClientError,
    staleTime: 10_000,
    // React Query pauses interval refetches while the tab is hidden
    refetchInterval: (query) =>
      query.state.data?.items?.some(isActiveSubmission) ? ACTIVE_SUBMISSION_POLL_MS : false,
  });
}
