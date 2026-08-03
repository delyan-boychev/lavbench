import { useQuery } from '@tanstack/react-query';
import api from '../services/ApiService';

export function useAdminMetricsQuery() {
  return useQuery({
    queryKey: ['admin-metrics'],
    queryFn: async () => {
      const res = await api.get('/admin/metrics');
      if (!res.ok) throw new Error(res.data?.error || 'Failed to load metrics');
      return res.data;
    },
    staleTime: 30_000,
  });
}
