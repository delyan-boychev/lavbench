import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router';
import { useApp } from '../context/AppContext';
import useSSE, { isLifecycleMessage } from '../hooks/useSSE';
import useThrottledCallback from '../hooks/useThrottledCallback';
import { useLeaderboardQuery } from '../hooks/useLeaderboardQuery';
import LeaderboardTable from '../components/leaderboard/LeaderboardTable';
import EmptyState from '../components/ui/EmptyState';
import QueryErrorState from '../components/ui/QueryErrorState';
import { useTranslation } from 'react-i18next';

const POLL_INTERVAL_MS = 15_000;
const SSE_RETRY_MS = 60_000;

export default function LeaderboardView() {
  const { challengeId } = useParams();
  const { selectedChallenge, setSelectedChallengeById } = useApp();
  const { t } = useTranslation();

  const [useSse, setUseSse] = useState(true);
  const activeId = challengeId || selectedChallenge?.id;
  const hasSse = typeof EventSource !== 'undefined';

  const polling = !hasSse || !useSse;

  const { data, isLoading, isError, refetch } = useLeaderboardQuery(activeId, {
    refetchInterval: polling ? POLL_INTERVAL_MS : false,
  });

  const throttledRefetch = useThrottledCallback(() => {
    refetch();
  }, 1500);

  useSSE(useSse && hasSse && activeId ? `/api/challenges/${activeId}/leaderboard/live` : '', {
    storeData: false,
    onMessage: (msg) => {
      if (isLifecycleMessage(msg)) return;
      throttledRefetch();
    },
    onError: () => setUseSse(false),
  });

  useEffect(() => {
    if (challengeId) setSelectedChallengeById(challengeId);
  }, [challengeId, setSelectedChallengeById]);

  useEffect(() => {
    setUseSse(true);
  }, [challengeId, selectedChallenge?.id]);

  // Polling is only a fallback; give the live stream another chance after a while
  useEffect(() => {
    if (!hasSse || useSse) return;
    const timer = setTimeout(() => setUseSse(true), SSE_RETRY_MS);
    return () => clearTimeout(timer);
  }, [hasSse, useSse]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }} className="animate-fadein">
      {selectedChallenge && isError ? (
        <QueryErrorState onRetry={refetch} />
      ) : selectedChallenge ? (
        <LeaderboardTable
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
