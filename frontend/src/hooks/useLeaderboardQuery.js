import { useQuery } from '@tanstack/react-query';
import ChallengeService from '../services/ChallengeService';
import { LIVE_QUERY_OPTIONS } from './useSSEInvalidation';

/**
 * @param {string | undefined} challengeId
 * @param {{ refetchInterval?: number | false }} [options]
 */
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
    ...LIVE_QUERY_OPTIONS,
    // React Query pauses interval refetches while the tab is hidden
    refetchInterval,
  });
}
