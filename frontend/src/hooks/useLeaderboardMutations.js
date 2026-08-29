import { useMutation, useQueryClient } from '@tanstack/react-query';
import ChallengeService from '../services/ChallengeService';
import { requireOk } from '../services/apiResult';

export function useSaveManualPoints() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ payload) => {
      const { challengeId, ...body } = payload;
      return ChallengeService.saveManualPoints(challengeId, body).then(requireOk);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['leaderboard'] }),
  });
}
