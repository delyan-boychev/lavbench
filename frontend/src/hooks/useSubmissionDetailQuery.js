import { useQuery } from '@tanstack/react-query';
import TaskService from '../services/TaskService';
import { requireOk, retryUnlessClientError } from '../services/apiResult';

/**
 * @param {string | null | undefined} submissionId
 * @param {{ refetchInterval?: number | false | ((query: any) => number | false) }} [options]
 */
export function useSubmissionDetailQuery(submissionId, options = {}) {
  const { refetchInterval = false } = options;
  return useQuery({
    queryKey: ['submission-detail', submissionId],
    // The thrown ApiRequestError keeps the response code and message
    queryFn: () =>
      TaskService.getSubmissionDetail(submissionId)
        .then(requireOk)
        .then((res) => res.data),
    enabled: !!submissionId,
    retry: retryUnlessClientError,
    staleTime: 10_000,
    refetchInterval,
  });
}
