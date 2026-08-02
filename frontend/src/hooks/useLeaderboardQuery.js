import { useQuery } from '@tanstack/react-query';
import ChallengeService from '../services/ChallengeService';

export function useLeaderboardQuery(challengeId) {
  return useQuery({
    queryKey: ['leaderboard', challengeId],
    queryFn: () =>
      ChallengeService.getLeaderboard(challengeId).then((res) => {
        if (!res.ok) throw new Error('Failed to load leaderboard');
        return res.data;
      }),
    enabled: !!challengeId,
    staleTime: 15_000,
  });
}
