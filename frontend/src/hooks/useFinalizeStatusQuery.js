import { useQuery } from '@tanstack/react-query';
import api from '../services/ApiService';
import { requireOk } from '../services/apiResult';

/**
 * @typedef {import('../types/api').paths['/api/challenges/{challenge_id}/finalize-status']['get']['responses']['200']['content']['application/json']} FinalizeStatus
 */

/**
 * Whether the competition and each stage can be finalised now, as the server decides it.
 * @param {string | undefined} challengeId
 * @param {{ enabled?: boolean }} [options]
 * @returns {import('@tanstack/react-query').UseQueryResult<FinalizeStatus, Error>}
 */
export function useFinalizeStatusQuery(challengeId, options = {}) {
  const { enabled = true } = options;
  return useQuery({
    queryKey: ['finalize-status', challengeId],
    queryFn: async ({ signal }) => {
      const res = requireOk(
        await api.get(`/challenges/${challengeId}/finalize-status`, { signal }),
      );
      return /** @type {FinalizeStatus} */ (res.data);
    },
    enabled: enabled && !!challengeId,
    // Runs finish and windows close while the dialog is open
    refetchInterval: 15_000,
    staleTime: 0,
  });
}

/** The error code whose text explains a readiness reason. */
export function finalizeReasonCode(reason, isStage) {
  if (reason === 'not_ended') return isStage ? 'ERR_STAGE_NOT_ENDED' : 'ERR_COMPETITION_NOT_ENDED';
  if (reason === 'runs_pending') return 'ERR_EVALUATIONS_PENDING';
  return 'ERR_FINAL_SELECTION_OPEN';
}
