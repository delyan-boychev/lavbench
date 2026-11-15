import { useQuery } from '@tanstack/react-query';
import TaskService from '../services/TaskService';
import { LIVE_QUERY_OPTIONS } from './useSSEInvalidation';

/**
 * @param {number} [page]
 * @param {number} [perPage]
 * @param {{ refetchInterval?: number | false }} [options]
 */
export function useQueueQuery(page = 1, perPage = 20, options = {}) {
  const { refetchInterval = false } = options;
  return useQuery({
    queryKey: ['queue', page, perPage],
    queryFn: () =>
      TaskService.getQueue(page, perPage).then((res) => {
        if (!res.ok) throw new Error('Failed to load queue');
        return res.data;
      }),
    ...LIVE_QUERY_OPTIONS,
    refetchInterval,
  });
}
