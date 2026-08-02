import { useQuery } from '@tanstack/react-query';
import api from '../services/ApiService';

export function useAdminChallengesQuery(page = 1, perPage = 5) {
  return useQuery({
    queryKey: ['admin-challenges', page],
    queryFn: async () => {
      const res = await api.get(`/challenges?page=${page}&per_page=${perPage}`);
      if (!res.ok) throw new Error(res.data?.error || 'Failed to load challenges');
      return res.data;
    },
    placeholderData: (prev) => prev,
    staleTime: 15_000,
  });
}
