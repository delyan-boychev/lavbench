import { useQuery } from '@tanstack/react-query';
import api from '../services/ApiService';

export function useCompetitorsQuery(challengeId, page = 1, search = '', perPage = 10) {
  const params = new URLSearchParams({
    page: String(page),
    per_page: String(perPage),
    role: 'competitor',
  });
  if (challengeId) params.set('challenge_id', String(challengeId));
  if (search) params.set('search', search);

  return useQuery({
    queryKey: ['admin-competitors', challengeId, page, search],
    queryFn: async () => {
      const res = await api.get(`/admin/users?${params.toString()}`);
      if (!res.ok) throw new Error(res.data?.error || 'Failed to load competitors');
      return res.data;
    },
    placeholderData: (prev) => prev,
    staleTime: 15_000,
    enabled: !!challengeId,
  });
}
