import { useQuery } from '@tanstack/react-query';
import api from '../services/ApiService';
import { requireOk } from '../services/apiResult';

// Local copies of backend/schemas/responses/status.py until src/types/api.d.ts is regenerated
/**
 * @typedef {'operational' | 'degraded_performance' | 'partial_outage' | 'major_outage' | 'under_maintenance'} StatusWord
 * @typedef {{ api: StatusWord, scoring: StatusWord }} StatusComponents
 * @typedef {{ status: StatusWord, components: StatusComponents, updated_at: string }} PublicStatus
 * @typedef {{ name: string, consumers: number, queued: number }} QueueStatus
 * @typedef {{
 *   name: string,
 *   type: string,
 *   queues: string[],
 *   online: boolean,
 *   last_seen: string | null,
 *   concurrency: number | null,
 *   cpu_cores: number | null,
 *   ram_gb: number | null,
 *   gpu_type: string | null,
 *   vram_gb: number | null,
 * }} WorkerHeartbeat
 * @typedef {{
 *   queued: number,
 *   running: number,
 *   oldest_queued_seconds: number | null,
 *   completed_last_15m: number,
 *   failed_last_15m: number,
 * }} SubmissionCounts
 * @typedef {{
 *   status: StatusWord,
 *   components: StatusComponents,
 *   queues: QueueStatus[],
 *   workers: WorkerHeartbeat[],
 *   submissions: SubmissionCounts,
 *   updated_at: string,
 * }} SystemStatus
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
