import { useQuery } from '@tanstack/react-query';
import api from '../services/ApiService';

export function useBackupsQuery() {
  return useQuery({
    queryKey: ['backups'],
    queryFn: async () => {
      const res = await api.get('/admin/backups');
      if (!res.ok) throw new Error(res.data?.error || 'Failed to load backups');
      return res.data;
    },
    staleTime: 10_000,
  });
}
