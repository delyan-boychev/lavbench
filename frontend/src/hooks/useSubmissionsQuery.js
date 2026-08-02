import { useQuery } from '@tanstack/react-query';
import TaskService from '../services/TaskService';

export function useSubmissionsQuery(taskId, page = 1, perPage = 10) {
  return useQuery({
    queryKey: ['submissions', taskId, page, perPage],
    queryFn: () =>
      TaskService.getSubmissions(taskId, page, perPage).then((res) => {
        if (!res.ok) throw new Error('Failed to load submissions');
        return res.data;
      }),
    enabled: !!taskId,
    staleTime: 10_000,
  });
}
