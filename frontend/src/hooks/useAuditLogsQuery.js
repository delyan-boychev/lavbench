import { useQuery } from '@tanstack/react-query';
import api from '../services/ApiService';

export function useAuditLogsQuery(challengeId, page = 1, action = '') {
  let url = `/admin/audit-logs?page=${page}&per_page=15`;
  if (challengeId) url += `&challenge_id=${challengeId}`;
  if (action) url += `&action_type=${action}`;

  return useQuery({
    queryKey: ['audit-logs', challengeId, page, action],
    queryFn: async () => {
      const res = await api.get(url);
      if (!res.ok) throw new Error(res.data?.error || 'Failed to load audit logs');
      return res.data;
    },
    placeholderData: (prev) => prev,
    staleTime: 15_000,
  });
}
