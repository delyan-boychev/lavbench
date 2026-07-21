import { useQuery } from '@tanstack/react-query';
import TaskService from '../services/TaskService';

export function useSubmissionDetailQuery(submissionId) {
  return useQuery({
    queryKey: ['submission-detail', submissionId],
    queryFn: async () => {
      const res = await TaskService.getSubmissionDetail(submissionId);
      if (!res.ok) throw new Error('Failed to load submission');
      return res.data;
    },
    enabled: !!submissionId,
    staleTime: 10_000,
  });
}
