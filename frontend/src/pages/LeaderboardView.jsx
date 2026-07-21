import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import useSSE from '../hooks/useSSE';
import { useLeaderboardQuery } from '../hooks/useLeaderboardQuery';
import LeaderboardTable from '../components/leaderboard/LeaderboardTable';
import EmptyState from '../components/ui/EmptyState';
import { useTranslation } from 'react-i18next';

export default function LeaderboardView() {
  const { challengeId } = useParams();
  const { selectedChallenge, setSelectedChallengeById } = useApp();
  const { t } = useTranslation();

  const [useSse, setUseSse] = useState(true);
  const activeId = challengeId || selectedChallenge?.id;
  const hasSse = typeof EventSource !== 'undefined';

  const { data, isLoading, refetch } = useLeaderboardQuery(activeId);

  useSSE(useSse && hasSse && activeId ? `/api/challenges/${activeId}/leaderboard/live` : '', {
    onMessage: (msg) => {
      if (msg.info === 'connected') return;
      refetch();
    },
    onError: () => setUseSse(false),
  });

  useEffect(() => {
    if (challengeId) setSelectedChallengeById(challengeId);
  }, [challengeId, setSelectedChallengeById]);

  useEffect(() => {
    setUseSse(true);
  }, [challengeId, selectedChallenge?.id]);

  useEffect(() => {
    if (!activeId) return;
    if (!hasSse || !useSse) {
      const interval = setInterval(() => refetch(), 15000);
      return () => clearInterval(interval);
    }
  }, [activeId, useSse, hasSse, refetch]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }} className="animate-fadein">
      {selectedChallenge ? (
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
