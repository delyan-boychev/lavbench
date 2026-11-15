import { useQuery } from '@tanstack/react-query';
import api from '../services/ApiService';
import { LIVE_QUERY_OPTIONS } from './useSSEInvalidation';

/**
 * @param {{ refetchInterval?: number | false }} [options]
 */
export function useBackupsQuery(options = {}) {
  const { refetchInterval = false } = options;
  return useQuery({
    queryKey: ['backups'],
    queryFn: async () => {
      const res = await api.get('/admin/backups');
      if (!res.ok) throw new Error(res.data?.error || 'Failed to load backups');
      return res.data;
    },
    ...LIVE_QUERY_OPTIONS,
    refetchInterval,
  });
}
