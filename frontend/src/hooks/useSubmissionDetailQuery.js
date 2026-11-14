import { useQuery } from '@tanstack/react-query';
import TaskService from '../services/TaskService';

/**
 * @param {string | null | undefined} submissionId
 * @param {{ refetchInterval?: number | false | ((query: any) => number | false) }} [options]
 */
export function useSubmissionDetailQuery(submissionId, options = {}) {
  const { refetchInterval = false } = options;
  return useQuery({
    queryKey: ['submission-detail', submissionId],
    queryFn: async () => {
      const res = await TaskService.getSubmissionDetail(submissionId);
      if (!res.ok) throw new Error('Failed to load submission');
      return res.data;
    },
    enabled: !!submissionId,
    staleTime: 10_000,
    refetchInterval,
  });
}
