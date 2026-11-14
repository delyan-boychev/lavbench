import { useQuery } from '@tanstack/react-query';
import api from '../services/ApiService';
import { requireOk } from '../services/apiResult';

/**
 * @typedef {import('../types/api').paths['/api/admin/system-status']['get']['responses']['200']['content']['application/json']} SystemStatus
 */

export const SYSTEM_STATUS_POLL_MS = 15_000;

/**
 * Poll GET /api/admin/system-status for the workers panel (admin and jury).
 * @returns {import('@tanstack/react-query').UseQueryResult<SystemStatus, Error>}
 */
export function useSystemStatusQuery() {
  return useQuery({
    queryKey: ['system-status'],
    queryFn: async ({ signal }) => {
      const res = requireOk(await api.get('/admin/system-status', { signal }));
      return /** @type {SystemStatus} */ (res.data);
    },
    staleTime: SYSTEM_STATUS_POLL_MS,
    refetchInterval: SYSTEM_STATUS_POLL_MS,
    // A hidden tab does not poll; focusing it refetches once the data is stale
    refetchIntervalInBackground: false,
  });
}
