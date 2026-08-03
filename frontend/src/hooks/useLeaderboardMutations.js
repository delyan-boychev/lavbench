import { useMutation, useQueryClient } from '@tanstack/react-query';
import ChallengeService from '../services/ChallengeService';

export function useSaveManualPoints() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (/** @type {any} */ payload) => ChallengeService.saveManualPoints(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['leaderboard'] }),
  });
}
