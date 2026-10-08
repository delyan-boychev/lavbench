import { useQuery } from '@tanstack/react-query';
import ChallengeService from '../services/ChallengeService';

export function useLeaderboardQuery(challengeId, options = {}) {
  const { refetchInterval = false } = options;
  return useQuery({
    queryKey: ['leaderboard', challengeId],
    queryFn: () =>
      ChallengeService.getLeaderboard(challengeId).then((res) => {
        if (!res.ok) throw new Error('Failed to load leaderboard');
        return res.data;
      }),
    enabled: !!challengeId,
    staleTime: 15_000,
    // React Query pauses interval refetches while the tab is hidden
    refetchInterval,
  });
}
