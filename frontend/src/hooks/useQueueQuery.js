import { useQuery } from '@tanstack/react-query';
import TaskService from '../services/TaskService';

export function useQueueQuery(page = 1, perPage = 20) {
  return useQuery({
    queryKey: ['queue', page, perPage],
    queryFn: () =>
      TaskService.getQueue(page, perPage).then((res) => {
        if (!res.ok) throw new Error('Failed to load queue');
        return res.data;
      }),
    staleTime: 10_000,
  });
}
