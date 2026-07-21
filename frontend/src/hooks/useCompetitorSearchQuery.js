import { useQuery } from '@tanstack/react-query';
import api from '../services/ApiService';

export function useCompetitorSearchQuery(challengeId, search = '', page = 1) {
  return useQuery({
    queryKey: ['competitor-search', challengeId, search, page],
    queryFn: async () => {
      const params = new URLSearchParams({
        role: 'competitor',
        challenge_id: String(challengeId),
        page: String(page),
        per_page: '10',
      });
      if (search) params.set('search', search);
      const res = await api.get(`/admin/users?${params.toString()}`);
      if (!res.ok) throw new Error(res.data?.error || 'Failed to search competitors');
      return res.data;
    },
    enabled: !!challengeId,
    staleTime: 15_000,
  });
}
