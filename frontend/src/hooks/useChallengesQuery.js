import { useQuery } from '@tanstack/react-query';
import api from '../services/ApiService';

export function useChallengesQuery() {
  return useQuery({
    queryKey: ['challenges'],
    queryFn: async () => {
      const res = await api.get('/challenges');
      if (!res.ok) throw new Error(res.data?.error || 'Failed to load challenges');
      return res.data.items || res.data;
    },
    staleTime: 30_000,
    retry: 1,
  });
}
