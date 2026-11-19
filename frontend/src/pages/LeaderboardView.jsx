import React, { useEffect } from 'react';
import { useParams } from 'react-router';
import { useApp } from '../context/AppContext';
import useSSEInvalidation, { LEADERBOARD_REFETCH_SPREAD_MS } from '../hooks/useSSEInvalidation';
import { useLeaderboardQuery } from '../hooks/useLeaderboardQuery';
import LeaderboardTable from '../components/leaderboard/LeaderboardTable';
import EmptyState from '../components/ui/EmptyState';
import ChallengeNotFound from '../components/challenge/ChallengeNotFound';
import useChallengeNotFound from '../hooks/useChallengeNotFound';
import QueryErrorState from '../components/ui/QueryErrorState';
import { useTranslation } from 'react-i18next';

export default function LeaderboardView() {
  const { challengeId } = useParams();
  const { selectedChallenge, setSelectedChallengeById } = useApp();
  const { t } = useTranslation();
  const notFound = useChallengeNotFound(challengeId);

  const activeId = challengeId || selectedChallenge?.id;

  // The stream only signals that the leaderboard changed; polling covers the gaps
  const { refetchInterval } = useSSEInvalidation(
    activeId ? `/api/challenges/${activeId}/leaderboard/live` : '',
    ['leaderboard', activeId],
    { spreadMs: LEADERBOARD_REFETCH_SPREAD_MS },
  );
  const { data, isLoading, isError, refetch } = useLeaderboardQuery(activeId, { refetchInterval });

  useEffect(() => {
    if (challengeId) setSelectedChallengeById(challengeId);
  }, [challengeId, setSelectedChallengeById]);

  if (notFound) return <ChallengeNotFound />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }} className="animate-fadein">
      {selectedChallenge && isError ? (
        <QueryErrorState onRetry={refetch} />
      ) : selectedChallenge ? (
        <LeaderboardTable
          // Remount per challenge so tab state from another challenge never leaks in
          key={selectedChallenge.id}
          data={data?.leaderboard || []}
          tasks={data?.tasks || []}
          challenge={selectedChallenge}
          loading={isLoading}
          metricName={data?.metric_name || 'Score'}
          isNormalized={data?.is_normalized || false}
          onRefresh={() => refetch()}
        />
      ) : (
        <EmptyState message={t('challenge.no_competition_selected_brief')} minHeight={200} />
      )}
    </div>
  );
}
